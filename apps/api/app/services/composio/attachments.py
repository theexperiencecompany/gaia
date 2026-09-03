"""Resolve high-level file references into Composio email attachments.

Composio's Gmail compose tools (GMAIL_CREATE_EMAIL_DRAFT / GMAIL_SEND_EMAIL) take an
``attachment`` of ``{name, mimetype, s3key}`` — a file already uploaded to Composio's
store — not raw bytes. This module turns a reference the agent or a user gives us into
that shape:

- ``workspace_path`` — a file in the current session workspace (an upload, or a file an
  agent downloaded there). Read from the host JuiceFS mount and uploaded to Composio.
- ``url`` — any fetchable URL, e.g. the download link GOOGLEDRIVE_DOWNLOAD_FILE returns
  for a Google Drive file. Composio fetches and stores it.

Resolution is all-or-nothing: if any reference fails, we raise so the caller can fail
the whole compose action loudly instead of sending mail that is missing a file the user
asked to attach.
"""

from pathlib import Path
from typing import TypedDict

from composio.core.models._files import FileUploadable, _upload_bytes_to_s3
from pydantic import BaseModel, Field, model_validator

from app.services.storage.juicefs import resolve_user_file_sync
from app.utils.errors import AppError
from shared.py.wide_events import log

_WORKSPACE_PREFIX = "/workspace/"

# Observability / user-facing error prose. Kept as single-line module constants so
# mutation testing can suppress them (it cannot suppress interior lines of a
# multi-line log/error call); the tests assert behaviour, not this wording.
_ATTACH_FAIL_LOG = "Email attachment could not be resolved"  # pragma: no mutate
_ATTACH_FAIL_WHY = "The file could not be read or uploaded."  # pragma: no mutate
_ATTACH_FAIL_FIX = "Check the workspace path or URL is correct, then retry."  # pragma: no mutate


class AttachmentReference(BaseModel):
    """One file to attach, referenced by exactly one source."""

    workspace_path: str | None = Field(
        default=None,
        description="Path to a file in the current session workspace (relative to /workspace).",
    )
    url: str | None = Field(
        default=None,
        description="A fetchable URL to the file, e.g. a Google Drive download link.",
    )
    name: str | None = Field(
        default=None, description="Optional filename to use for the attachment."
    )

    @model_validator(mode="after")
    def _exactly_one_source(self) -> "AttachmentReference":
        if bool(self.workspace_path) == bool(self.url):
            raise ValueError("need exactly one of workspace_path or url")  # pragma: no mutate
        return self


class ComposioAttachment(TypedDict):
    """The ``FileUploadable`` shape Composio's compose tools expect."""

    name: str
    mimetype: str
    s3key: str


def _normalize_workspace_path(path: str) -> str:
    """Strip a leading ``/workspace/`` (or ``/``) so the path is workspace-relative."""
    stripped = path.strip()  # pragma: no mutate -- defensive whitespace trim
    if stripped.startswith(_WORKSPACE_PREFIX):
        return stripped[len(_WORKSPACE_PREFIX) :]
    return stripped.lstrip("/")  # pragma: no mutate -- "/"->"XX/XX" is an equivalent strip


def _upload_reference(
    ref: AttachmentReference, *, user_id: str, tool: str, toolkit: str
) -> FileUploadable:
    # Imported lazily: the Composio hook package auto-imports this module, and
    # composio_service imports that package, so a module-level import here would
    # form a cycle.
    from app.services.composio.composio_service import (  # noqa: PLC0415
        get_composio_service,
    )

    client = get_composio_service().composio.client
    if ref.workspace_path:
        # `resolve_user_file_sync` already contains the path to the user's own
        # workspace root (defeats ../ and symlink escape), so Composio's generic
        # denylist/allowlist for untrusted paths is redundant here.
        host_path: Path = resolve_user_file_sync(
            user_id, _normalize_workspace_path(ref.workspace_path)
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
            uploaded = _upload_reference(ref, user_id=user_id, tool=tool, toolkit=toolkit)
        except Exception as exc:
            source = ref.workspace_path or ref.url
            log.error(_ATTACH_FAIL_LOG, error=str(exc), user_id=user_id)  # pragma: no mutate
            message = f"Could not attach '{ref.name or source}': {exc}"  # pragma: no mutate
            raise AppError(
                message=message, why=_ATTACH_FAIL_WHY, fix=_ATTACH_FAIL_FIX, status_code=400
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
    (the byte-level counterpart of the public ``FileUploadable.from_path``).
    """
    # Lazy import: see _upload_reference for the cycle this avoids.
    from app.services.composio.composio_service import (  # noqa: PLC0415
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
