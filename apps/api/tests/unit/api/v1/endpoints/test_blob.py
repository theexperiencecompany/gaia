"""GET /api/v1/blobs/{owner_id}/{key}: a self-hosted blob, to whoever its kind allows."""

from __future__ import annotations

from pathlib import Path

from httpx import AsyncClient
import pytest
from tests.conftest import FAKE_USER
from tests.helpers import captured_wide_event

from app.api.v1.endpoints.blob import get_blob
from app.config.settings import settings
from app.constants.files import BlobKind
from app.services.blob_store import LocalVolumeBlobStore

OWNER = FAKE_USER.user_id


@pytest.fixture
async def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> LocalVolumeBlobStore:
    monkeypatch.setattr(settings, "ENV", "selfhost")
    monkeypatch.setattr(settings, "LOCAL_FILE_STORAGE_PATH", str(tmp_path))
    monkeypatch.setattr("app.services.blob_store._is_mountpoint", lambda _p: True)
    return LocalVolumeBlobStore(tmp_path)


async def test_the_owner_gets_the_bytes_with_inert_headers(
    client: AsyncClient, store: LocalVolumeBlobStore
) -> None:
    url = await store.put(
        OWNER,
        "pic",
        b"\x89PNG-bytes",
        resource_type="image",
        kind=BlobKind.CHAT_UPLOAD,
        content_type="image/png",
    )

    resp = await client.get(url)

    assert resp.status_code == 200
    assert resp.content == b"\x89PNG-bytes"
    assert resp.headers["content-type"] == "image/png"
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert "sandbox" in resp.headers["content-security-policy"]
    assert resp.headers["content-disposition"] == 'inline; filename="pic"'


async def test_a_range_request_gets_only_that_slice(
    client: AsyncClient, store: LocalVolumeBlobStore
) -> None:
    url = await store.put(
        OWNER,
        "clip",
        b"0123456789",
        resource_type="video",
        kind=BlobKind.CHAT_UPLOAD,
        content_type="video/mp4",
    )

    resp = await client.get(url, headers={"Range": "bytes=2-5"})

    assert resp.status_code == 206
    assert resp.content == b"2345"


async def test_html_downloads_instead_of_rendering(
    client: AsyncClient, store: LocalVolumeBlobStore
) -> None:
    url = await store.put(
        OWNER,
        "page",
        b"<script>x</script>",
        resource_type="raw",
        kind=BlobKind.CHAT_UPLOAD,
        content_type="text/html",
    )

    resp = await client.get(url)

    assert resp.headers["content-disposition"].startswith("attachment")


@pytest.mark.parametrize(
    ("kind", "status"),
    [
        (BlobKind.AVATAR, 200),
        (BlobKind.CHAT_UPLOAD, 404),
        (BlobKind.GENERATED_IMAGE, 404),
        (BlobKind.SUPPORT_ATTACHMENT, 404),
    ],
)
async def test_only_avatars_reach_other_members_of_the_instance(
    client: AsyncClient, store: LocalVolumeBlobStore, kind: BlobKind, status: int
) -> None:
    url = await store.put(
        "another-member",
        "blob",
        b"bytes",
        resource_type="image",
        kind=kind,
        content_type="image/png",
    )

    resp = await client.get(url)

    assert resp.status_code == status
    assert (resp.content == b"bytes") is (status == 200)


async def test_another_users_blob_is_a_404(
    client: AsyncClient, store: LocalVolumeBlobStore
) -> None:
    url = await store.put(
        "someone-else",
        "secret",
        b"theirs",
        resource_type="raw",
        kind=BlobKind.CHAT_UPLOAD,
        content_type="text/plain",
    )

    resp = await client.get(url)

    assert resp.status_code == 404
    assert b"theirs" not in resp.content


async def test_hosted_deployments_serve_nothing_from_disk(
    client: AsyncClient, store: LocalVolumeBlobStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = await store.put(
        OWNER,
        "pic",
        b"x",
        resource_type="image",
        kind=BlobKind.CHAT_UPLOAD,
        content_type="image/png",
    )
    monkeypatch.setattr(settings, "ENV", "production")

    assert (await client.get(url)).status_code == 404


async def test_a_missing_blob_is_a_404(client: AsyncClient, store: LocalVolumeBlobStore) -> None:
    assert (await client.get(f"/api/v1/blobs/{OWNER}/nope")).status_code == 404


async def test_requires_auth(unauthed_client: AsyncClient, store: LocalVolumeBlobStore) -> None:
    url = await store.put(
        OWNER,
        "pic",
        b"x",
        resource_type="image",
        kind=BlobKind.CHAT_UPLOAD,
        content_type="image/png",
    )
    assert (await unauthed_client.get(url)).status_code == 401


async def test_a_read_records_who_read_whose_blob_and_its_type(
    store: LocalVolumeBlobStore,
) -> None:
    await store.put(
        OWNER,
        "pic",
        b"png",
        resource_type="image",
        kind=BlobKind.CHAT_UPLOAD,
        content_type="image/png",
    )

    async with captured_wide_event() as event:
        await get_blob(OWNER, "pic", FAKE_USER)

    assert event["user"] == {"id": OWNER}
    assert event["blob"] == {"operation": "read", "owner_id": OWNER, "content_type": "image/png"}
