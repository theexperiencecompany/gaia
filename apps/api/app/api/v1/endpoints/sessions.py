"""Session file endpoints — serve a conversation's workspace artifacts.

`GET .../artifacts` is also the defense-in-depth recovery path: the frontend
polls it on tab-focus / message-complete to reconcile anything the live
artifact stream missed. All listing is host-side JuiceFS (zero R2 ops).
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.agents.workspace.paths import detect_content_type
from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.decorators import tiered_rate_limit
from app.models.user_models import AuthenticatedUser
from app.schemas.errors import error_responses
from app.services.analytics_service import capture
from app.services.conversation_service import require_owned_conversation
from app.services.storage import (
    ArtifactInfo,
    JuiceFSUnavailable,
    list_artifacts,
    list_user_uploaded,
    pin_session_artifact,
    resolve_session_path,
)
from shared.py.analytics import UserId
from shared.py.analytics.catalog.chat import SessionArtifactPinned
from shared.py.wide_events import log

router = APIRouter(prefix="/sessions", tags=["Sessions"])

_DOWNLOAD_OCTET = "application/octet-stream"
# Content types a browser executes script from when navigated to top-level;
# served with a sandbox CSP so artifacts can't run JS on the API origin
# (which holds the session cookie). Covers every XML flavour detect_content_type emits.
_ACTIVE_CONTENT_TYPES = (
    "text/html",
    "image/svg+xml",
    "application/xhtml+xml",
    "application/xml",
)
# Known-safe types rendered inline via the served URL; everything else is
# force-downloaded so a direct/shared link can't execute on the API origin.
# HTML is deliberately absent: its preview renders in a sandboxed srcDoc iframe.
_SAFE_INLINE_TYPES = (
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/webp",
    "application/pdf",
)


class PinRequest(BaseModel):
    """An artifact to copy into the user's pinned workspace folder."""

    path: str = Field(..., description="Path relative to the session's artifacts/")
    target_name: str | None = Field(
        default=None, description="Optional filename for the pinned copy"
    )


class PinResponse(BaseModel):
    """Where the pinned copy now lives."""

    pinned_path: str = Field(..., description="/workspace/... path of the pinned copy")


def _serve(host_path: Path, *, is_artifact: bool, filename: str) -> FileResponse:
    """FileResponse with content-type, sandboxing + cache headers.

    FileResponse natively handles Range / 206 / Accept-Ranges.
    """
    content_type = detect_content_type(filename) or _DOWNLOAD_OCTET
    headers = {
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": ("private, max-age=60" if is_artifact else "private, max-age=3600"),
    }
    if content_type in _ACTIVE_CONTENT_TYPES:
        # Agent-generated HTML/SVG/XML is untrusted — neuter scripts/same-origin.
        headers["Content-Security-Policy"] = "sandbox"
    # Force download for anything not a known-safe inline type so a shared link
    # can't execute JS on the API origin. filename= emits an RFC-encoded
    # Content-Disposition, so a quoted/CR-LF filename can't inject the header.
    force_download = content_type not in _SAFE_INLINE_TYPES
    return FileResponse(
        path=str(host_path),
        media_type=content_type,
        headers=headers,
        filename=filename if force_download else None,
    )


async def _resolve_file(
    user_id: str,
    conv_id: str,
    role: Literal["artifacts", "uploaded"],
    path: str,
) -> Path:
    try:
        host_path = await resolve_session_path(user_id, conv_id, role, path)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="Invalid path") from e
    except JuiceFSUnavailable as e:
        raise HTTPException(status_code=503, detail="Workspace storage offline") from e
    if not host_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return host_path


@router.get("/{conv_id}/artifacts")
@tiered_rate_limit("session_files")
async def list_session_artifacts(
    conv_id: str, user: Annotated[AuthenticatedUser, Depends(get_current_user)]
) -> list[ArtifactInfo]:
    """List the files the agent produced in this conversation's workspace."""
    user_id = user.user_id
    log.set(user={"id": user_id}, session={"conv": conv_id, "op": "list_artifacts"})
    await require_owned_conversation(conv_id, user_id)
    try:
        items = await list_artifacts(user_id, conv_id)
    except JuiceFSUnavailable as e:
        log.warning(
            "workspace storage offline — returning empty artifact list",
            error_type=type(e).__name__,
        )
        items = []
    return items


@router.get(
    "/{conv_id}/artifacts/{path:path}",
    response_class=FileResponse,
    responses=error_responses(
        {
            400: "Invalid path",
            404: "File not found",
            503: "Workspace storage offline",
        }
    ),
)
@tiered_rate_limit("session_files")
async def get_artifact_file(
    conv_id: str, path: str, user: Annotated[AuthenticatedUser, Depends(get_current_user)]
) -> FileResponse:
    """Serve one agent-produced file from this conversation's workspace."""
    user_id = user.user_id
    log.set(user={"id": user_id}, session={"conv": conv_id, "op": "get_artifact"})
    await require_owned_conversation(conv_id, user_id)
    host_path = await _resolve_file(user_id, conv_id, "artifacts", path)
    return _serve(host_path, is_artifact=True, filename=path.rsplit("/", 1)[-1])


@router.get("/{conv_id}/uploads")
@tiered_rate_limit("session_files")
async def list_uploads(
    conv_id: str, user: Annotated[AuthenticatedUser, Depends(get_current_user)]
) -> list[ArtifactInfo]:
    """List the files the user attached in this conversation."""
    user_id = user.user_id
    log.set(user={"id": user_id}, session={"conv": conv_id, "op": "list_uploads"})
    await require_owned_conversation(conv_id, user_id)
    try:
        items = await list_user_uploaded(user_id, conv_id)
    except JuiceFSUnavailable as e:
        log.warning(
            "workspace storage offline — returning empty upload list",
            error_type=type(e).__name__,
        )
        items = []
    return items


@router.get(
    "/{conv_id}/uploads/{path:path}",
    response_class=FileResponse,
    responses=error_responses(
        {
            400: "Invalid path",
            404: "File not found",
            503: "Workspace storage offline",
        }
    ),
)
@tiered_rate_limit("session_files")
async def get_upload_file(
    conv_id: str, path: str, user: Annotated[AuthenticatedUser, Depends(get_current_user)]
) -> FileResponse:
    """Serve one file the user attached in this conversation."""
    user_id = user.user_id
    log.set(user={"id": user_id}, session={"conv": conv_id, "op": "get_upload"})
    await require_owned_conversation(conv_id, user_id)
    host_path = await _resolve_file(user_id, conv_id, "uploaded", path)
    return _serve(host_path, is_artifact=False, filename=path.rsplit("/", 1)[-1])


@router.post(
    "/{conv_id}/pin",
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(
        {
            400: "Invalid path",
            404: "Artifact not found",
            503: "Workspace storage offline",
        }
    ),
)
@tiered_rate_limit("session_files")
async def pin_artifact(
    conv_id: str,
    payload: PinRequest,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> PinResponse:
    """Copy an artifact into the user's pinned folder so it outlives the conversation."""
    user_id = user.user_id
    log.set(user={"id": user_id}, session={"conv": conv_id, "op": "pin"})
    await require_owned_conversation(conv_id, user_id)
    try:
        pinned_path = await pin_session_artifact(
            user_id, conv_id, payload.path, payload.target_name
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail="Invalid path") from e
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail="Artifact not found") from e
    except JuiceFSUnavailable as e:
        raise HTTPException(status_code=503, detail="Workspace storage offline") from e
    capture(UserId(user_id), SessionArtifactPinned())
    return PinResponse(pinned_path=pinned_path)
