"""BLOB_STORE=s3 against a real MinIO server: the boto3 calls, the boot probe and the blob route.

The unit tier proves the store against an in-process fake; this proves the
real client's request signing, path-style URLs, metadata and error codes.
Each run starts its own MinIO container and skips where the docker CLI is unavailable.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
import shutil
import time
import uuid

import boto3
import httpx
from httpx import AsyncClient
import pytest

from app.config.deployment import BlobStoreKind
from app.config.settings import settings
from app.constants.files import S3_WRITE_PROBE_KEY, BlobKind, S3AddressingStyle
from app.services.blob_store import blob_store, ensure_blob_store_ready, s3_blob_store
from app.utils.errors import AppError
from tests.conftest import FAKE_USER

pytestmark = pytest.mark.skipif(
    shutil.which("docker") is None, reason="requires the docker CLI + daemon"
)

# minio/minio is no longer published on Docker Hub; pgsty builds the community edition.
MINIO_IMAGE = "pgsty/minio@sha256:b6bfe7239bfc83fb90d31612d9704d86039dd714f7904b3f1ad68f211e602372"
ACCESS_KEY = "gaia-test-access"
SECRET_KEY = "gaia-test-secret-key"
READY_DEADLINE_SECONDS = 30.0


@dataclass(frozen=True)
class MinioServer:
    endpoint_url: str


async def _docker(*args: str) -> str:
    proc = await asyncio.create_subprocess_exec(
        "docker", *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await proc.communicate()
    assert proc.returncode == 0, stderr.decode()
    return stdout.decode().strip()


async def _wait_until_live(endpoint_url: str) -> None:
    deadline = time.monotonic() + READY_DEADLINE_SECONDS
    async with httpx.AsyncClient(timeout=2.0) as http:
        while time.monotonic() < deadline:
            try:
                if (await http.get(f"{endpoint_url}/minio/health/live")).status_code == 200:
                    return
            except httpx.TransportError:
                pass
            await asyncio.sleep(0.2)
    raise AssertionError(f"MinIO at {endpoint_url} was not live within {READY_DEADLINE_SECONDS}s")


@pytest.fixture
async def minio() -> AsyncIterator[MinioServer]:
    name = f"gaia-test-minio-{uuid.uuid4().hex[:12]}"
    await _docker(
        "run", "-d", "--rm", "--name", name,
        "-e", f"MINIO_ROOT_USER={ACCESS_KEY}",
        "-e", f"MINIO_ROOT_PASSWORD={SECRET_KEY}",
        "-p", "127.0.0.1::9000",
        MINIO_IMAGE, "server", "/data",
    )  # fmt: skip
    try:
        host_port = (await _docker("port", name, "9000/tcp")).splitlines()[0]
        server = MinioServer(endpoint_url=f"http://{host_port}")
        await _wait_until_live(server.endpoint_url)
        yield server
    finally:
        await _docker("rm", "-f", name)


@pytest.fixture
def s3_deployment(minio: MinioServer, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """Point a self-host instance at a fresh MinIO bucket; yield the bucket's name."""
    bucket = f"gaia-{uuid.uuid4().hex[:12]}"
    boto3.client(
        "s3",
        endpoint_url=minio.endpoint_url,
        aws_access_key_id=ACCESS_KEY,
        aws_secret_access_key=SECRET_KEY,
        region_name="us-east-1",
    ).create_bucket(Bucket=bucket)
    monkeypatch.setattr(settings, "ENV", "selfhost")
    monkeypatch.setattr(settings, "BLOB_STORE", BlobStoreKind.S3)
    monkeypatch.setattr(settings, "S3_ENDPOINT_URL", minio.endpoint_url)
    monkeypatch.setattr(settings, "S3_BUCKET", bucket)
    monkeypatch.setattr(settings, "S3_ACCESS_KEY_ID", ACCESS_KEY)
    monkeypatch.setattr(settings, "S3_SECRET_ACCESS_KEY", SECRET_KEY)
    monkeypatch.setattr(settings, "S3_REGION", None)
    monkeypatch.setattr(settings, "S3_ADDRESSING_STYLE", S3AddressingStyle.PATH)
    s3_blob_store.cache_clear()
    yield bucket
    s3_blob_store.cache_clear()


async def test_an_upload_is_served_back_through_the_blob_route_then_deleted(
    s3_deployment: str, client: AsyncClient
) -> None:
    owner = FAKE_USER.user_id
    store = blob_store()
    await ensure_blob_store_ready()

    url = await store.put(
        owner,
        "photo.png",
        b"\x89PNG-real-bytes",
        resource_type="image",
        kind=BlobKind.CHAT_UPLOAD,
        content_type="image/png",
    )
    served = await client.get(url)
    await store.delete(owner, "photo.png")
    after_delete = await client.get(url)

    assert url == f"/api/v1/blobs/{owner}/photo.png"
    assert served.status_code == 200
    assert served.content == b"\x89PNG-real-bytes"
    assert served.headers["content-type"] == "image/png"
    assert served.headers["content-disposition"] == 'inline; filename="photo.png"'
    assert after_delete.status_code == 404


async def test_another_members_upload_stays_private(
    s3_deployment: str, client: AsyncClient
) -> None:
    await blob_store().put(
        "someone-else",
        "private.txt",
        b"secret",
        resource_type="raw",
        kind=BlobKind.CHAT_UPLOAD,
        content_type="text/plain",
    )

    resp = await client.get("/api/v1/blobs/someone-else/private.txt")

    assert resp.status_code == 404


async def test_the_boot_probe_leaves_no_object_behind(s3_deployment: str) -> None:
    await ensure_blob_store_ready()

    listed = s3_blob_store().client.list_objects_v2(Bucket=s3_deployment)  # type: ignore[attr-defined]  # why: boto3's generated client, outside the narrow protocol
    assert all(o["Key"] != S3_WRITE_PROBE_KEY for o in listed.get("Contents", []))


async def test_a_wrong_secret_stops_the_boot_naming_the_credentials(
    s3_deployment: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "S3_SECRET_ACCESS_KEY", "not-the-secret")
    s3_blob_store.cache_clear()

    with pytest.raises(AppError) as raised:
        await ensure_blob_store_ready()

    assert raised.value.code == "s3_credentials_rejected"


async def test_a_missing_bucket_stops_the_boot_naming_the_bucket(
    s3_deployment: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "S3_BUCKET", "no-such-bucket")
    s3_blob_store.cache_clear()

    with pytest.raises(AppError) as raised:
        await ensure_blob_store_ready()

    assert raised.value.code == "s3_bucket_missing"
    assert "'no-such-bucket'" in raised.value.message
