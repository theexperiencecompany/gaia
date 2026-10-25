"""Durable blob storage: Cloudinary on hosted deployments, a local volume or S3 bucket on self-host.

Every uploaded or generated blob (chat uploads, generated images, profile
pictures, support attachments) goes through blob_store(). The deployment's
blob_store (BLOB_STORE) picks the backend; callers never branch on it.
Local and S3 blobs stay private and are served by the authenticated blob route.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
import io
import os
from pathlib import Path
import re
import shutil
from typing import Protocol, TypedDict, assert_never, cast

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
import cloudinary.uploader
from fastapi import HTTPException
import httpx
from pydantic import BaseModel, Field

from app.config.cloudinary import require_cloudinary
from app.config.deployment import BlobStoreKind
from app.config.settings import settings
from app.constants.files import (
    BLOB_AUDIENCE,
    BLOB_DOWNLOAD_TIMEOUT_SECONDS,
    BLOB_ROUTE_URL_PREFIX,
    LOCAL_BLOB_DATA_FILENAME,
    LOCAL_BLOB_META_FILENAME,
    S3_BAD_CREDENTIAL_CODES,
    S3_MAX_ATTEMPTS,
    S3_MISSING_BUCKET_CODES,
    S3_MISSING_OBJECT_CODES,
    S3_TIMEOUT_SECONDS,
    S3_WRITE_PROBE_KEY,
    BlobAudience,
    BlobKind,
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
        kind: BlobKind,
        content_type: str,
    ) -> str: ...

    async def read(self, owner_id: str, public_id: str, url: str) -> bytes:
        """Return a stored blob's bytes; url is what put returned for it."""
        ...

    async def delete(self, owner_id: str, public_id: str) -> None:
        """Best-effort removal: a failure is logged, never raised."""
        ...


class CloudinaryBlobStore:
    """Public Cloudinary URLs; owner_id, kind and content_type play no part in the call."""

    def ensure_ready(self) -> None:
        require_cloudinary()

    async def put(
        self,
        owner_id: str,
        public_id: str,
        content: bytes,
        *,
        resource_type: str,
        kind: BlobKind,
        content_type: str,
    ) -> str:
        del owner_id, kind, content_type
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
    kind: BlobKind


@dataclass(frozen=True, slots=True)
class LocalBlob:
    """A stored local blob, resolved for serving."""

    path: Path
    content_type: str
    kind: BlobKind


@dataclass(frozen=True, slots=True)
class S3Blob:
    """A stored S3 blob, read in full for serving."""

    content: bytes
    content_type: str
    kind: BlobKind


ServedBlob = LocalBlob | S3Blob


class ServedBlobStore(BlobStore, Protocol):
    """A private store whose blobs the authenticated blob route serves back."""

    async def open(self, owner_id: str, key: str) -> ServedBlob | None:
        """Resolve a stored blob, or None when it does not exist."""
        ...


def _is_mountpoint(path: Path) -> bool:
    return path.is_mount()


def blob_key(public_id: str) -> str:
    """Flatten a public id into one safe path segment (the URL's last segment)."""
    key = _UNSAFE_KEY_CHARS.sub("_", public_id).lstrip(".")
    if not key:
        raise ValueError("blob public_id has no usable characters")
    return key


def _is_safe_key(key: str) -> bool:
    return not (_UNSAFE_KEY_CHARS.search(key) or key.startswith("."))


def _require_safe_owner(owner_id: str) -> None:
    if not _SAFE_ID_RE.match(owner_id):
        raise ValueError("unsafe blob owner id")


def _blob_route_url(owner_id: str, key: str) -> str:
    return f"{BLOB_ROUTE_URL_PREFIX}/{owner_id}/{key}"


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
        if not os.access(self.root, os.W_OK):
            raise AppError(
                message="File uploads are not set up on this instance.",
                why=f"{self.root} is not writable by the API's user.",
                fix=(
                    "Give the API's user write access to LOCAL_FILE_STORAGE_PATH, or set "
                    "BLOB_STORE=cloudinary with Cloudinary credentials."
                ),
                status_code=503,
                code="file_storage_not_writable",
            )

    def _blob_dir(self, owner_id: str, key: str) -> Path:
        _require_safe_owner(owner_id)
        return self.root / owner_id / key

    async def put(
        self,
        owner_id: str,
        public_id: str,
        content: bytes,
        *,
        resource_type: str,
        kind: BlobKind,
        content_type: str,
    ) -> str:
        del resource_type
        self.ensure_ready()
        key = blob_key(public_id)
        blob_dir = self._blob_dir(owner_id, key)
        meta = LocalBlobMeta(content_type=content_type, kind=kind).model_dump_json().encode()

        def _write() -> None:
            blob_dir.mkdir(parents=True, exist_ok=True)
            (blob_dir / LOCAL_BLOB_DATA_FILENAME).write_bytes(content)
            (blob_dir / LOCAL_BLOB_META_FILENAME).write_bytes(meta)

        await asyncio.to_thread(_write)
        return _blob_route_url(owner_id, key)

    async def read(self, owner_id: str, public_id: str, url: str) -> bytes:
        del url
        blob = await self.open(owner_id, blob_key(public_id))
        if blob is None:
            raise FileNotFoundError(f"no local blob {public_id!r} for owner {owner_id}")
        return await asyncio.to_thread(blob.path.read_bytes)

    async def delete(self, owner_id: str, public_id: str) -> None:
        blob_dir = self._blob_dir(owner_id, blob_key(public_id))
        if not blob_dir.is_dir():
            log.warning(
                "[blobs] local blob to delete is missing", owner_id=owner_id, key=blob_dir.name
            )
            return
        await asyncio.to_thread(shutil.rmtree, blob_dir)

    async def open(self, owner_id: str, key: str) -> LocalBlob | None:
        """Resolve a stored blob, or None when it does not exist."""
        if not _is_safe_key(key):
            return None
        blob_dir = self._blob_dir(owner_id, key)

        def _read_meta() -> LocalBlob | None:
            data = blob_dir / LOCAL_BLOB_DATA_FILENAME
            meta = blob_dir / LOCAL_BLOB_META_FILENAME
            if not (data.is_file() and meta.is_file()):
                return None
            parsed = LocalBlobMeta.model_validate_json(meta.read_bytes())
            return LocalBlob(path=data, content_type=parsed.content_type, kind=parsed.kind)

        return await asyncio.to_thread(_read_meta)


class S3Body(Protocol):
    """The streaming body of a fetched object."""

    def read(self) -> bytes: ...


class S3BlobMetadata(TypedDict):
    """The user metadata the store writes on every object."""

    kind: str


class S3Object(TypedDict):
    """The get_object fields the store reads."""

    Body: S3Body
    ContentType: str
    Metadata: S3BlobMetadata


class S3Client(Protocol):
    """The boto3 S3 methods the store calls (boto3 clients are generated at runtime and untyped)."""

    def put_object(
        self, *, Bucket: str, Key: str, Body: bytes, ContentType: str, Metadata: Mapping[str, str]
    ) -> object: ...

    def get_object(self, *, Bucket: str, Key: str) -> S3Object: ...

    def delete_object(self, *, Bucket: str, Key: str) -> object: ...


class _S3ErrorDetail(BaseModel):
    code: str = Field(alias="Code")


class _S3ErrorResponse(BaseModel):
    """The part of a botocore ClientError response that names the S3 error."""

    error: _S3ErrorDetail = Field(alias="Error")


def _s3_error_code(error: ClientError) -> str:
    return _S3ErrorResponse.model_validate(error.response).error.code


class S3BlobStore:
    """Private objects at <owner_id>/<key> in one bucket, served by the authenticated blob route."""

    def __init__(self, client: S3Client, bucket: str, endpoint_url: str) -> None:
        self.client = client
        self.bucket = bucket
        self.endpoint_url = endpoint_url

    def ensure_ready(self) -> None:
        """Nothing to check per upload: s3_blob_store needs every key, and boot probes the bucket."""

    async def verify_bucket(self) -> None:
        """Write then delete a probe object; raise an AppError naming what is wrong when either fails."""
        try:
            await asyncio.to_thread(
                self.client.put_object,
                Bucket=self.bucket,
                Key=S3_WRITE_PROBE_KEY,
                Body=b"",
                ContentType="application/octet-stream",
                Metadata={},
            )
            await asyncio.to_thread(
                self.client.delete_object, Bucket=self.bucket, Key=S3_WRITE_PROBE_KEY
            )
        except ClientError as e:
            raise self._probe_error(_s3_error_code(e), str(e)) from e
        except BotoCoreError as e:
            raise AppError(
                message=(
                    f"File uploads are not set up: the S3 endpoint {self.endpoint_url} "
                    "is unreachable."
                ),
                why=str(e),
                fix="Set S3_ENDPOINT_URL to the bucket service's S3 API URL, reachable from the API.",
                status_code=503,
                code="s3_endpoint_unreachable",
            ) from e

    def _probe_error(self, code: str, detail: str) -> AppError:
        if code in S3_MISSING_BUCKET_CODES:
            return AppError(
                message=(
                    f"File uploads are not set up: the S3 bucket {self.bucket!r} does not "
                    f"exist at {self.endpoint_url}."
                ),
                why=detail,
                fix="Create the bucket, or set S3_BUCKET to the name of one that exists.",
                status_code=503,
                code="s3_bucket_missing",
            )
        if code in S3_BAD_CREDENTIAL_CODES:
            return AppError(
                message=(
                    "File uploads are not set up: the S3 credentials cannot write to the "
                    f"bucket {self.bucket!r}."
                ),
                why=detail,
                fix=(
                    "Check S3_ACCESS_KEY_ID and S3_SECRET_ACCESS_KEY, and that the key may "
                    "write and delete objects."
                ),
                status_code=503,
                code="s3_credentials_rejected",
            )
        return AppError(
            message=(
                f"File uploads are not set up: the S3 bucket {self.bucket!r} refused a test "
                f"write ({code})."
            ),
            why=detail,
            fix="Check S3_ENDPOINT_URL, S3_REGION and S3_ADDRESSING_STYLE match the bucket service.",
            status_code=503,
            code="s3_write_failed",
        )

    def _object_key(self, owner_id: str, key: str) -> str:
        _require_safe_owner(owner_id)
        return f"{owner_id}/{key}"

    async def put(
        self,
        owner_id: str,
        public_id: str,
        content: bytes,
        *,
        resource_type: str,
        kind: BlobKind,
        content_type: str,
    ) -> str:
        del resource_type
        key = blob_key(public_id)
        await asyncio.to_thread(
            self.client.put_object,
            Bucket=self.bucket,
            Key=self._object_key(owner_id, key),
            Body=content,
            ContentType=content_type,
            Metadata={"kind": kind.value},
        )
        return _blob_route_url(owner_id, key)

    async def read(self, owner_id: str, public_id: str, url: str) -> bytes:
        del url
        blob = await self.open(owner_id, blob_key(public_id))
        if blob is None:
            raise FileNotFoundError(f"no S3 blob {public_id!r} for owner {owner_id}")
        return blob.content

    async def delete(self, owner_id: str, public_id: str) -> None:
        object_key = self._object_key(owner_id, blob_key(public_id))
        try:
            await asyncio.to_thread(self.client.delete_object, Bucket=self.bucket, Key=object_key)
        except (ClientError, BotoCoreError) as e:
            log.error(
                "[blobs] s3 delete failed",
                owner_id=owner_id,
                key=object_key,
                error=str(e),
                error_type=type(e).__name__,
            )

    async def open(self, owner_id: str, key: str) -> S3Blob | None:
        """Read a stored blob in full, or None when it does not exist."""
        if not _is_safe_key(key):
            return None
        object_key = self._object_key(owner_id, key)

        def _get() -> S3Blob | None:
            try:
                stored: S3Object = self.client.get_object(Bucket=self.bucket, Key=object_key)
            except ClientError as e:
                if _s3_error_code(e) in S3_MISSING_OBJECT_CODES:
                    return None
                raise
            metadata: S3BlobMetadata = stored["Metadata"]
            return S3Blob(
                content=stored["Body"].read(),
                content_type=stored["ContentType"],
                kind=BlobKind(metadata["kind"]),
            )

        return await asyncio.to_thread(_get)


def local_blob_store() -> LocalVolumeBlobStore:
    return LocalVolumeBlobStore(Path(settings.LOCAL_FILE_STORAGE_PATH))


@lru_cache(maxsize=1)
def s3_blob_store() -> S3BlobStore:
    """Build the BLOB_STORE=s3 store; raise an AppError when an S3 setting is missing."""
    endpoint_url = settings.S3_ENDPOINT_URL
    bucket = settings.S3_BUCKET
    if not (
        endpoint_url and bucket and settings.S3_ACCESS_KEY_ID and settings.S3_SECRET_ACCESS_KEY
    ):
        raise AppError(
            message="File uploads are not set up: BLOB_STORE=s3 is missing its bucket settings.",
            fix="Set S3_ENDPOINT_URL, S3_BUCKET, S3_ACCESS_KEY_ID and S3_SECRET_ACCESS_KEY.",
            status_code=503,
            code="s3_not_configured",
        )
    client = boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=settings.S3_ACCESS_KEY_ID,
        aws_secret_access_key=settings.S3_SECRET_ACCESS_KEY,
        region_name=settings.S3_REGION,
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": settings.S3_ADDRESSING_STYLE.value},
            connect_timeout=S3_TIMEOUT_SECONDS,
            read_timeout=S3_TIMEOUT_SECONDS,
            retries={"max_attempts": S3_MAX_ATTEMPTS},
        ),
    )
    return S3BlobStore(cast(S3Client, client), bucket, endpoint_url)


def _served_blob_store() -> ServedBlobStore | None:
    """Return the private store the blob route serves from; None when blobs live in Cloudinary."""
    match settings.deployment.blob_store:
        case BlobStoreKind.LOCAL:
            return local_blob_store()
        case BlobStoreKind.S3:
            return s3_blob_store()
        case BlobStoreKind.CLOUDINARY:
            return None
        case unknown:
            assert_never(unknown)


def blob_store() -> BlobStore:
    """Return the deployment's blob store."""
    return _served_blob_store() or CloudinaryBlobStore()


async def ensure_blob_store_ready() -> None:
    """Refuse to boot when the local volume or the S3 bucket cannot take uploads."""
    match settings.deployment.blob_store:
        case BlobStoreKind.LOCAL:
            local_blob_store().ensure_ready()
        case BlobStoreKind.S3:
            await s3_blob_store().verify_bucket()
        case BlobStoreKind.CLOUDINARY:
            return
        case unknown:
            assert_never(unknown)


def _may_read(blob: ServedBlob, requester_id: str, owner_id: str) -> bool:
    return requester_id == owner_id or BLOB_AUDIENCE[blob.kind] is BlobAudience.INSTANCE_MEMBERS


async def open_readable_blob(requester_id: str, owner_id: str, key: str) -> ServedBlob:
    """Resolve a served blob its kind lets the requester read; otherwise, or under Cloudinary, a 404."""
    store = _served_blob_store()
    blob = await store.open(owner_id, key) if store is not None else None
    if blob is None or not _may_read(blob, requester_id, owner_id):
        raise AppError(message="File not found", status_code=404, code="blob_not_found")
    return blob
