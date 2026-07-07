"""Session file endpoints — serve a conversation's workspace artifacts.

`GET .../artifacts` is also the defense-in-depth recovery path: the frontend
polls it on tab-focus / message-complete to reconcile anything the live
artifact stream missed. All listing is host-side JuiceFS (zero R2 ops).
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from app.agents.workspace.paths import detect_content_type
from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.db.mongodb.collections import conversations_collection
from app.decorators import tiered_rate_limit
from app.services.storage import (
    JuiceFSUnavailable,
    list_artifacts,
    list_user_uploaded,
    pin_session_artifact,
    resolve_session_path,
)
from shared.py.wide_events import log

router = APIRouter(prefix="/sessions", tags=["Sessions"])

_DOWNLOAD_OCTET = "application/octet-stream"
# Content types a browser executes script from when navigated to top-level —
# served with a sandbox CSP so agent-authored artifacts can't run JS on the API
# origin (which holds the session cookie). Covers HTML and every XML flavour
# detect_content_type emits.
_ACTIVE_CONTENT_TYPES = (
    "text/html",
    "image/svg+xml",
    "application/xhtml+xml",
    "application/xml",
)
# Known-safe types rendered inline in-app via the served URL (<img>/<iframe
# src>). Everything else — active content, octet-stream, etc. — is force-
# downloaded so a direct/shared link can't execute on the API origin. HTML is
# deliberately absent: its in-app preview fetches the text and renders it in a
# sandboxed srcDoc iframe, so forcing download here doesn't affect preview.
_SAFE_INLINE_TYPES = (
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/webp",
    "application/pdf",
)


class PinRequest(BaseModel):
    path: str = Field(..., description="Path relative to the session's artifacts/")
    target_name: str | None = Field(
        default=None, description="Optional filename for the pinned copy"
    )


async def _assert_owns(user_id: str, conv_id: str) -> None:
    """403 unless (user_id, conv_id) is a conversation owned by this user."""
    doc = await conversations_collection.find_one(
        {"user_id": user_id, "conversation_id": conv_id},
        projection={"_id": 1},
    )
    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Conversation not found or not owned by this user",
        )


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
    # Force download for anything not a known-safe inline type so a direct/shared
    # artifact link can't execute JS on the API origin. FileResponse's filename=
    # emits an RFC-encoded `Content-Disposition: attachment`, so an agent-chosen
    # name with quotes or CR/LF can't inject or break the header.
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
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid path")
    except JuiceFSUnavailable:
        raise HTTPException(status_code=503, detail="Workspace storage offline")
    if not host_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return host_path


@router.get("/{conv_id}/artifacts")
@tiered_rate_limit("session_files")
async def list_session_artifacts(
    conv_id: str, user: Annotated[dict, Depends(get_current_user)]
) -> JSONResponse:
    user_id = user["user_id"]
    log.set(user={"id": user_id}, session={"conv": conv_id, "op": "list_artifacts"})
    await _assert_owns(user_id, conv_id)
    try:
        items = await list_artifacts(user_id, conv_id)
    except JuiceFSUnavailable:
        items = []
    return JSONResponse(content=[asdict(i) for i in items])


@router.get(
    "/{conv_id}/artifacts/{path:path}",
    responses={
        400: {"description": "Invalid path"},
        404: {"description": "File not found"},
        503: {"description": "Workspace storage offline"},
    },
)
@tiered_rate_limit("session_files")
async def get_artifact_file(
    conv_id: str, path: str, user: Annotated[dict, Depends(get_current_user)]
) -> FileResponse:
    user_id = user["user_id"]
    log.set(user={"id": user_id}, session={"conv": conv_id, "op": "get_artifact"})
    await _assert_owns(user_id, conv_id)
    host_path = await _resolve_file(user_id, conv_id, "artifacts", path)
    return _serve(host_path, is_artifact=True, filename=path.rsplit("/", 1)[-1])


@router.get("/{conv_id}/uploads")
@tiered_rate_limit("session_files")
async def list_uploads(
    conv_id: str, user: Annotated[dict, Depends(get_current_user)]
) -> JSONResponse:
    user_id = user["user_id"]
    log.set(user={"id": user_id}, session={"conv": conv_id, "op": "list_uploads"})
    await _assert_owns(user_id, conv_id)
    try:
        items = await list_user_uploaded(user_id, conv_id)
    except JuiceFSUnavailable:
        items = []
    return JSONResponse(content=[asdict(i) for i in items])


@router.get(
    "/{conv_id}/uploads/{path:path}",
    responses={
        400: {"description": "Invalid path"},
        404: {"description": "File not found"},
        503: {"description": "Workspace storage offline"},
    },
)
@tiered_rate_limit("session_files")
async def get_upload_file(
    conv_id: str, path: str, user: Annotated[dict, Depends(get_current_user)]
) -> FileResponse:
    user_id = user["user_id"]
    log.set(user={"id": user_id}, session={"conv": conv_id, "op": "get_upload"})
    await _assert_owns(user_id, conv_id)
    host_path = await _resolve_file(user_id, conv_id, "uploaded", path)
    return _serve(host_path, is_artifact=False, filename=path.rsplit("/", 1)[-1])


@router.post(
    "/{conv_id}/pin",
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {"description": "Invalid path"},
        404: {"description": "Artifact not found"},
        503: {"description": "Workspace storage offline"},
    },
)
@tiered_rate_limit("session_files")
async def pin_artifact(
    conv_id: str,
    payload: PinRequest,
    user: Annotated[dict, Depends(get_current_user)],
) -> JSONResponse:
    user_id = user["user_id"]
    log.set(user={"id": user_id}, session={"conv": conv_id, "op": "pin"})
    await _assert_owns(user_id, conv_id)
    try:
        pinned_path = await pin_session_artifact(
            user_id, conv_id, payload.path, payload.target_name
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid path")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Artifact not found")
    except JuiceFSUnavailable:
        raise HTTPException(status_code=503, detail="Workspace storage offline")
    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content={"pinned_path": pinned_path},
    )
