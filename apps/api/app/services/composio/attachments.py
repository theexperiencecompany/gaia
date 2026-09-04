"""Resolve high-level file references into Composio file uploads.

Composio's file-accepting tools (Gmail compose today — GMAIL_CREATE_EMAIL_DRAFT /
GMAIL_SEND_EMAIL — any future toolkit with the same ``attachment`` of
``{name, mimetype, s3key}``) take a file already uploaded to Composio's store,
not raw bytes. This module turns a reference the agent or a user gives us into
that shape:

- ``workspace_path`` — a file in the current session workspace (an upload, or a file an
  agent downloaded there). Read from the host JuiceFS mount and uploaded to Composio.
- ``url`` — any fetchable URL, e.g. the download link GOOGLEDRIVE_DOWNLOAD_FILE returns
  for a Google Drive file. Composio fetches and stores it.
- raw ``bytes`` — via ``upload_bytes_sync`` for the REST multipart path, where the
  file arrives as bytes rather than a reference.

Resolution is all-or-nothing: if any reference fails, we raise so the caller can fail
the whole action loudly instead of proceeding with a file the user asked for missing.
"""

from pathlib import Path

from composio.core.models._files import FileUploadable, _upload_bytes_to_s3

from app.constants.email import (
    EMAIL_ATTACHMENT_FAIL_FIX,
    EMAIL_ATTACHMENT_FAIL_LOG,
    EMAIL_ATTACHMENT_FAIL_WHY,
)
from app.models.mail_models import AttachmentReference, ComposioAttachment
from app.services.storage.juicefs import resolve_user_file_sync, to_workspace_relative_path
from app.utils.errors import AppError
from shared.py.wide_events import log


def upload_file_reference(
    ref: AttachmentReference, *, user_id: str, tool: str, toolkit: str
) -> FileUploadable:
    """Upload one file reference to Composio's store for any toolkit's use.

    General capability, not email-specific: ``tool``/``toolkit`` name the invoking
    Composio tool so uploads are attributed correctly (Gmail today, Outlook/Slack
    or any file-accepting tool tomorrow).
    """
    # Imported lazily: the Composio hook package auto-imports this module, and
    # composio_service imports that package, so a module-level import here would
    # form a cycle.
    from app.services.composio.composio_service import (  # noqa: PLC0415 -- lazy: avoids an import cycle
        get_composio_service,
    )

    client = get_composio_service().composio.client
    if ref.workspace_path:
        # `resolve_user_file_sync` already contains the path to the user's own
        # workspace root (defeats ../ and symlink escape), so Composio's generic
        # denylist/allowlist for untrusted paths is redundant here.
        host_path: Path = resolve_user_file_sync(
            user_id, to_workspace_relative_path(ref.workspace_path)
        )
        return FileUploadable.from_path(
            client=client,
            file=str(host_path),
            tool=tool,
            toolkit=toolkit,
            sensitive_file_upload_protection=False,
            file_upload_allowlist=None,
        )
    # ``url`` is guaranteed present here by AttachmentReference's validator; the
    # ``or ""`` only satisfies the type checker and is therefore unreachable.
    url = ref.url or ""  # pragma: no mutate
    return FileUploadable.from_url(client=client, url=url, tool=tool, toolkit=toolkit)


def resolve_attachments_sync(
    user_id: str,
    references: list[AttachmentReference],
    *,
    tool: str,
    toolkit: str,
) -> list[ComposioAttachment]:
    """Upload each referenced file to Composio and return the attachment objects.

    Raises ``AppError`` if any reference cannot be resolved (all-or-nothing).
    """
    resolved: list[ComposioAttachment] = []
    for ref in references:
        try:
            uploaded = upload_file_reference(ref, user_id=user_id, tool=tool, toolkit=toolkit)
        except Exception as exc:
            source = ref.workspace_path or ref.url
            log.error(EMAIL_ATTACHMENT_FAIL_LOG, error=str(exc), user_id=user_id)  # pragma: no mutate
            message = f"Could not attach '{ref.name or source}': {exc}"  # pragma: no mutate
            raise AppError(
                message=message,
                why=EMAIL_ATTACHMENT_FAIL_WHY,
                fix=EMAIL_ATTACHMENT_FAIL_FIX,
                status_code=400,
            ) from exc
        resolved.append(
            {
                "name": ref.name or uploaded.name,
                "mimetype": uploaded.mimetype,
                "s3key": uploaded.s3key,
            }
        )
    return resolved


def map_sandbox_path_for_upload(path: str, *, user_id: str) -> str:
    """Map a model-supplied file reference to a host path Composio can upload.

    Spike helper evaluating Composio-native auto-upload (``FileHelper`` +
    ``before_file_upload``): ``/workspace/...`` sandbox paths resolve against
    the user's own contained root (same guarantee as the manual upload path —
    ``..``/symlink escape raises inside ``resolve_user_file_sync``); http(s)
    URLs pass through for Composio to fetch itself. Anything else (absolute
    host paths, ``/mnt/...`` cross-user reaches) raises instead of leaking into
    the uploader — the static-dir allowlist alone cannot express per-user
    containment, so this function is the boundary.
    """
    stripped = path.strip()
    if stripped.startswith(("http://", "https://")):
        return stripped
    if stripped.startswith("/workspace/") or not stripped.startswith("/"):
        return str(resolve_user_file_sync(user_id, to_workspace_relative_path(stripped)))
    raise ValueError(f"refusing to upload non-workspace path: {stripped}")


def upload_bytes_sync(
    content: bytes,
    filename: str,
    mimetype: str | None,
    *,
    tool: str,
    toolkit: str,
) -> ComposioAttachment:
    """Upload raw bytes (e.g. a multipart upload) to Composio and return the attachment.

    Used by the REST send path, where the file arrives as bytes rather than a
    workspace path or URL. ``_upload_bytes_to_s3`` is Composio's own bytes uploader
    (the byte-level counterpart of the public ``FileUploadable.from_path``).
    """
    # Lazy import: see upload_file_reference for the cycle this avoids.
    from app.services.composio.composio_service import (  # noqa: PLC0415 -- lazy: avoids an import cycle
        get_composio_service,
    )

    resolved_mimetype = mimetype or "application/octet-stream"
    s3key = _upload_bytes_to_s3(
        client=get_composio_service().composio.client,
        filename=filename,
        content=content,
        mimetype=resolved_mimetype,
        tool=tool,
        toolkit=toolkit,
    )
    return {"name": filename, "mimetype": resolved_mimetype, "s3key": s3key}
