"""Durable blob storage: Cloudinary on hosted deployments, a local volume on self-host.

Every uploaded or generated blob (chat uploads, generated images, profile
pictures, support attachments) goes through blob_store(). The deployment's
local_file_storage capability picks the backend; callers never branch on it.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import io
from pathlib import Path
import re
import shutil
from typing import Protocol

import cloudinary.uploader
from fastapi import HTTPException
import httpx
from pydantic import BaseModel

from app.config.cloudinary import require_cloudinary
from app.config.settings import settings
from app.constants.files import (
    BLOB_DOWNLOAD_TIMEOUT_SECONDS,
    LOCAL_BLOB_DATA_FILENAME,
    LOCAL_BLOB_META_FILENAME,
    LOCAL_BLOB_URL_PREFIX,
)
from app.constants.vfs import SAFE_PATH_ID_PATTERN
from app.models.integrations.cloudinary import CloudinaryDestroyResult, CloudinaryUploadResult
from app.utils.errors import AppError
from shared.py.wide_events import log

_SAFE_ID_RE = re.compile(SAFE_PATH_ID_PATTERN)
_UNSAFE_KEY_CHARS = re.compile(r"[^A-Za-z0-9._-]+")


class BlobStore(Protocol):
    """Stores a blob under its owner and returns the URL clients load it from."""

    def ensure_ready(self) -> None:
        """Raise an AppError naming the fix when this store cannot accept uploads."""
        ...

    async def put(
        self,
        owner_id: str,
        public_id: str,
        content: bytes,
        *,
        resource_type: str,
        content_type: str,
    ) -> str: ...

    async def read(self, owner_id: str, public_id: str, url: str) -> bytes:
        """Return a stored blob's bytes; url is what put returned for it."""
        ...

    async def delete(self, owner_id: str, public_id: str) -> None:
        """Best-effort removal: a failure is logged, never raised."""
        ...


class CloudinaryBlobStore:
    """Public Cloudinary URLs; owner_id and content_type play no part in the call."""

    def ensure_ready(self) -> None:
        require_cloudinary()

    async def put(
        self,
        owner_id: str,
        public_id: str,
        content: bytes,
        *,
        resource_type: str,
        content_type: str,
    ) -> str:
        del owner_id, content_type
        result = await asyncio.to_thread(
            cloudinary.uploader.upload,
            io.BytesIO(content),
            resource_type=resource_type,
            public_id=public_id,
            overwrite=True,
        )
        url = CloudinaryUploadResult.model_validate(result).secure_url
        if not url:
            log.error("[blobs] cloudinary upload returned no secure_url", public_id=public_id)
            raise HTTPException(status_code=500, detail="Invalid response from file upload service")
        return url

    async def read(self, owner_id: str, public_id: str, url: str) -> bytes:
        del owner_id, public_id
        async with httpx.AsyncClient(timeout=BLOB_DOWNLOAD_TIMEOUT_SECONDS) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.content

    async def delete(self, owner_id: str, public_id: str) -> None:
        del owner_id
        try:
            response = await asyncio.to_thread(cloudinary.uploader.destroy, public_id)
            if CloudinaryDestroyResult.model_validate(response).result != "ok":
                log.warning("[blobs] cloudinary delete did not confirm", public_id=public_id)
        except Exception as e:
            log.error(
                "[blobs] cloudinary delete failed",
                public_id=public_id,
                error=str(e),
                error_type=type(e).__name__,
            )


class LocalBlobMeta(BaseModel):
    """What the blob route needs to serve a local blob back."""

    content_type: str


@dataclass(frozen=True, slots=True)
class LocalBlob:
    """A stored local blob, resolved for serving."""

    path: Path
    content_type: str


def _is_mountpoint(path: Path) -> bool:
    return path.is_mount()


def local_blob_key(public_id: str) -> str:
    """Flatten a public id into one safe path segment (the URL's last segment)."""
    key = _UNSAFE_KEY_CHARS.sub("_", public_id).lstrip(".")
    if not key:
        raise ValueError("blob public_id has no usable characters")
    return key


class LocalVolumeBlobStore:
    """Blobs under <root>/<owner_id>/<key>/, served by the authenticated blob route."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def ensure_ready(self) -> None:
        if not _is_mountpoint(self.root):
            raise AppError(
                message="File uploads are not set up on this instance.",
                why=f"{self.root} is not a mounted volume, so files would vanish with the container.",
                fix=(
                    "Mount a persistent volume at LOCAL_FILE_STORAGE_PATH; the self-host "
                    "compose file mounts gaia-selfhost_files there."
                ),
                status_code=503,
                code="file_storage_not_mounted",
            )

    def _blob_dir(self, owner_id: str, key: str) -> Path:
        if not _SAFE_ID_RE.match(owner_id):
            raise ValueError("unsafe blob owner id")
        return self.root / owner_id / key

    async def put(
        self,
        owner_id: str,
        public_id: str,
        content: bytes,
        *,
        resource_type: str,
        content_type: str,
    ) -> str:
        del resource_type
        self.ensure_ready()
        key = local_blob_key(public_id)
        blob_dir = self._blob_dir(owner_id, key)
        meta = LocalBlobMeta(content_type=content_type).model_dump_json()

        def _write() -> None:
            blob_dir.mkdir(parents=True, exist_ok=True)
            (blob_dir / LOCAL_BLOB_DATA_FILENAME).write_bytes(content)
            (blob_dir / LOCAL_BLOB_META_FILENAME).write_text(meta, encoding="utf-8")

        await asyncio.to_thread(_write)
        return f"{LOCAL_BLOB_URL_PREFIX}/{owner_id}/{key}"

    async def read(self, owner_id: str, public_id: str, url: str) -> bytes:
        del url
        blob = await self.open(owner_id, local_blob_key(public_id))
        if blob is None:
            raise FileNotFoundError(f"no local blob {public_id!r} for owner {owner_id}")
        return await asyncio.to_thread(blob.path.read_bytes)

    async def delete(self, owner_id: str, public_id: str) -> None:
        blob_dir = self._blob_dir(owner_id, local_blob_key(public_id))
        if not blob_dir.is_dir():
            log.warning(
                "[blobs] local blob to delete is missing", owner_id=owner_id, key=blob_dir.name
            )
            return
        await asyncio.to_thread(shutil.rmtree, blob_dir)

    async def open(self, owner_id: str, key: str) -> LocalBlob | None:
        """Resolve a stored blob, or None when it does not exist."""
        if _UNSAFE_KEY_CHARS.search(key) or key.startswith("."):
            return None
        blob_dir = self._blob_dir(owner_id, key)

        def _read_meta() -> LocalBlob | None:
            data = blob_dir / LOCAL_BLOB_DATA_FILENAME
            meta = blob_dir / LOCAL_BLOB_META_FILENAME
            if not (data.is_file() and meta.is_file()):
                return None
            parsed = LocalBlobMeta.model_validate_json(meta.read_text(encoding="utf-8"))
            return LocalBlob(path=data, content_type=parsed.content_type)

        return await asyncio.to_thread(_read_meta)


def local_blob_store() -> LocalVolumeBlobStore:
    return LocalVolumeBlobStore(Path(settings.LOCAL_FILE_STORAGE_PATH))


def blob_store() -> BlobStore:
    """Return the deployment's blob store."""
    if settings.deployment.local_file_storage:
        return local_blob_store()
    return CloudinaryBlobStore()


async def open_owned_blob(requester_id: str, owner_id: str, key: str) -> LocalBlob:
    """Resolve a local blob for its owner; anyone else, or a hosted deployment, gets a 404."""
    blob = (
        await local_blob_store().open(owner_id, key)
        if settings.deployment.local_file_storage and requester_id == owner_id
        else None
    )
    if blob is None:
        raise AppError(message="File not found", status_code=404, code="blob_not_found")
    return blob
