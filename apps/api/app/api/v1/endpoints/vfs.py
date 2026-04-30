"""VFS (Virtual Filesystem) HTTP API endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.models.vfs_models import VFSListResponse, VFSNodeResponse
from app.services.vfs import VFSAccessError, get_vfs

router = APIRouter()


def _validate_vfs_path(path: str) -> str:
    """Defence-in-depth path normalization at the endpoint layer.

    Rejects obvious path-traversal attempts (``..`` segments, null bytes,
    backslash separators) and absolute OS-style paths before handing the
    string to the VFS service. The service is expected to confine access
    to the caller's namespace, but we refuse to rely on that alone.
    """
    if not path:
        raise HTTPException(status_code=400, detail="path is required")
    if "\x00" in path:
        raise HTTPException(status_code=400, detail="null byte in path")
    if "\\" in path:
        raise HTTPException(status_code=400, detail="backslash not allowed in path")
    if path.startswith("/"):
        # VFS paths are relative; a leading slash may mean "escape to filesystem
        # root" in the underlying implementation. Always reject.
        raise HTTPException(status_code=400, detail="absolute paths not allowed")
    # Block ".." as a path segment. Allow dots inside filenames (e.g. "foo.txt").
    segments = path.split("/")
    if any(seg == ".." for seg in segments):
        raise HTTPException(status_code=400, detail="'..' segments not allowed")
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
    path = _validate_vfs_path(path)
    user_id = str(user["user_id"])
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
    path = _validate_vfs_path(path)
    user_id = str(user["user_id"])
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
    path = _validate_vfs_path(path)
    user_id = str(user["user_id"])
    vfs = await get_vfs()

    try:
        return await vfs.list_dir(path, user_id=user_id, recursive=recursive)
    except VFSAccessError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
