"""Resolve high-level file references into Composio file uploads.

Composio's file-accepting tools (Gmail compose today — GMAIL_CREATE_EMAIL_DRAFT /
GMAIL_SEND_EMAIL — any future toolkit with the same ``attachment`` of
``{name, mimetype, s3key}``) take a file already uploaded to Composio's store,
not raw bytes. This module turns a reference the agent or a user gives us into
that shape:

- ``workspace_path`` — a file in the current session workspace (an upload, or a file an
  agent downloaded there). Read from the host JuiceFS mount and uploaded to Composio.
- ``url`` — any *publicly* fetchable URL, e.g. the download link
  GOOGLEDRIVE_DOWNLOAD_FILE returns for a Google Drive file. Composio fetches and
  stores it, from inside this process, so the URL passes our SSRF guard first.
- raw ``bytes`` — via ``upload_bytes_sync`` for the REST multipart path, where the
  file arrives as bytes rather than a reference.

Resolution is all-or-nothing: if any reference fails, we raise so the caller can fail
the whole action loudly instead of proceeding with a file the user asked for missing.
"""

from pathlib import Path

from composio.core.models._files import FileUploadable

from app.constants.email import (
    EMAIL_ATTACHMENT_FAIL_FIX,
    EMAIL_ATTACHMENT_FAIL_LOG,
    EMAIL_ATTACHMENT_FAIL_WHY,
)
from app.models.mail_models import AttachmentReference, ComposioAttachment
from app.services.storage.juicefs import resolve_user_file_sync, to_workspace_relative_path
from app.utils.errors import AppError
from app.utils.url_safety import assert_public_http_url_sync
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
    # The URL is model-supplied and Composio fetches it from *this* process with
    # no scheme or address policy of its own, so the SSRF guard has to run here:
    # without it, "attach http://169.254.169.254/..." exfiltrates instance
    # metadata as a mail attachment. Composio's fetcher refuses redirects, so one
    # pre-flight check covers the whole fetch (a DNS rebind between this resolve
    # and Composio's remains theoretically possible; the redirect refusal is what
    # keeps that window to a single re-resolution).
    assert_public_http_url_sync(url)
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
    for index, ref in enumerate(references):
        try:
            uploaded = upload_file_reference(ref, user_id=user_id, tool=tool, toolkit=toolkit)
        except Exception as exc:
            # The label never falls back to ``url``: a Drive download link is
            # presigned, and this message becomes the tool error the model reads
            # and the conversation stores. The raw URL belongs on the wide event,
            # which is not user-visible. ``exc`` is safe to quote — both the SSRF
            # guard and Composio's fetcher sanitize the URL out of their own
            # messages, and the reason is what makes the failure actionable.
            label = ref.name or ref.workspace_path or f"file {index + 1}"
            log.error(
                EMAIL_ATTACHMENT_FAIL_LOG,
                error=str(exc),
                user_id=user_id,
                source=ref.workspace_path or ref.url,
            )  # pragma: no mutate
            message = f"Could not attach '{label}': {exc}"  # pragma: no mutate
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
    (the byte-level counterpart of the public ``FileUploadable.from_path``); it is
    private and has no public equivalent that preserves the caller's mimetype, so
    it is imported here rather than at module scope — a Composio release that moves
    it then breaks this one upload path loudly instead of the whole API's boot.
    """
    # Lazy imports: see upload_file_reference for the cycle the first one avoids.
    from composio.core.models._files import (  # noqa: PLC0415 -- lazy: scopes a private-API break to this path
        _upload_bytes_to_s3,
    )

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
