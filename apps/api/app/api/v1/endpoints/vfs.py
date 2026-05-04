"""VFS (Virtual Filesystem) HTTP API endpoints."""

import re
import unicodedata

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.models.vfs_models import VFSListResponse, VFSNodeResponse
from app.services.vfs import VFSAccessError, get_vfs

router = APIRouter()

# Reject path components containing Unicode look-alike traversal characters
# (e.g. ``․․`` U+2024 ONE DOT LEADER, ``‥`` U+2025 TWO DOT LEADER) and
# bidi-control codepoints used for filename spoofing. NFKC normalize the
# whole path first so the canonical comparison sees ASCII dots.
# Covers LRM/RLM (U+200E/U+200F), ALM (U+061C), formatting controls
# (U+202A–U+202E), and isolates (U+2066–U+2069).
_VFS_BIDI_CONTROL_RE = re.compile(r"[‎‏؜‪-‮⁦-⁩]")


def _validate_vfs_path(path: str, user_id: str) -> str:
    """Defence-in-depth path normalization at the endpoint layer.

    Rejects obvious path-traversal attempts (``..`` segments, null bytes,
    backslash separators, Unicode bidi-controls, NFKC-equivalent dot
    look-alikes) before handing the string to the VFS service. Also
    enforces that the path lives under the caller's own namespace
    (``/users/{user_id}/...``) or the read-only ``/system/...`` tree.
    The service still does its own confinement; this is belt-and-braces.
    """
    if not path:
        raise HTTPException(status_code=400, detail="path is required")
    if "\x00" in path:
        raise HTTPException(status_code=400, detail="null byte in path")
    if "\\" in path:
        raise HTTPException(status_code=400, detail="backslash not allowed in path")
    if _VFS_BIDI_CONTROL_RE.search(path):
        raise HTTPException(
            status_code=400, detail="bidi control characters not allowed"
        )
    # NFKC compatibility decomposition collapses dot look-alikes (U+2024,
    # U+2025, fullwidth dot, etc.) onto ASCII dots, so the ``..`` segment
    # check below catches them too.
    path = unicodedata.normalize("NFKC", path)
    # Block ".." as a path segment. Allow dots inside filenames (e.g. "foo.txt").
    segments = path.split("/")
    if any(seg == ".." for seg in segments):
        raise HTTPException(status_code=400, detail="'..' segments not allowed")
    # VFS paths are namespaced under ``/users/{user_id}/`` per
    # ``vfs/path_resolver.py``. Anything else is either an attempt to read
    # another user's tree or a malformed request — reject before the
    # service does, so we don't leak existence via differing error shapes.
    allowed_prefix = f"/users/{user_id}/"
    system_prefix = "/system/"
    if not (path.startswith(allowed_prefix) or path.startswith(system_prefix)):
        raise HTTPException(status_code=400, detail="invalid path namespace")
    return path


class VFSReadResponse(BaseModel):
    """Response model for VFS file reads."""

    path: str
    filename: str
    content: str
    content_type: str
    size_bytes: int


@router.get("/read", response_model=VFSReadResponse)
async def read_vfs_file(
    path: str = Query(..., description="Full VFS path to a file"),
    user: dict = Depends(get_current_user),
) -> VFSReadResponse:
    """Read file content from VFS for the authenticated user."""
    user_id = str(user["user_id"])
    path = _validate_vfs_path(path, user_id)
    vfs = await get_vfs()

    try:
        content = await vfs.read(path, user_id=user_id)
        if content is None:
            raise HTTPException(status_code=404, detail=f"File not found: {path}")

        info = await vfs.info(path, user_id=user_id)
        if info is None:
            raise HTTPException(status_code=404, detail=f"File not found: {path}")

        filename = path.rsplit("/", 1)[-1]
        return VFSReadResponse(
            path=path,
            filename=filename,
            content=content,
            content_type=info.content_type or "text/plain",
            size_bytes=info.size_bytes,
        )
    except VFSAccessError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e


@router.get("/info", response_model=VFSNodeResponse)
async def get_vfs_info(
    path: str = Query(..., description="Full VFS path to a file/folder"),
    user: dict = Depends(get_current_user),
) -> VFSNodeResponse:
    """Get metadata for a VFS file or folder."""
    user_id = str(user["user_id"])
    path = _validate_vfs_path(path, user_id)
    vfs = await get_vfs()

    try:
        info = await vfs.info(path, user_id=user_id)
        if info is None:
            raise HTTPException(status_code=404, detail=f"Not found: {path}")
        return info
    except VFSAccessError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e


@router.get("/list", response_model=VFSListResponse)
async def list_vfs_dir(
    path: str = Query(..., description="Full VFS directory path"),
    recursive: bool = Query(False, description="List nested files recursively"),
    user: dict = Depends(get_current_user),
) -> VFSListResponse:
    """List contents of a VFS directory."""
    user_id = str(user["user_id"])
    path = _validate_vfs_path(path, user_id)
    vfs = await get_vfs()

    try:
        return await vfs.list_dir(path, user_id=user_id, recursive=recursive)
    except VFSAccessError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
