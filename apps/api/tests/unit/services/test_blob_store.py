"""The blob store backends and which one each deployment gets."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
import io
from pathlib import Path
import threading
from unittest.mock import MagicMock, patch

from fastapi import HTTPException
import httpx
import pytest

from app.config.deployment import BlobStoreKind
from app.config.settings import settings
from app.constants.files import BLOB_AUDIENCE, BlobKind
from app.services.blob_store import (
    CloudinaryBlobStore,
    LocalBlobMeta,
    LocalVolumeBlobStore,
    blob_store,
    ensure_local_blob_store_ready,
    local_blob_key,
    open_readable_blob,
)
from app.utils.errors import AppError
from tests.helpers import captured_wide_event


@pytest.fixture(autouse=True)
def mounted_volume(monkeypatch: pytest.MonkeyPatch) -> None:
    """Treat the tmpdir as a mounted volume; the unmounted-volume test overrides this."""
    monkeypatch.setattr("app.services.blob_store._is_mountpoint", lambda _p: True)


@pytest.fixture
def cloudinary_sdk() -> Iterator[MagicMock]:
    with patch("app.services.blob_store.cloudinary.uploader") as sdk:
        yield sdk


@pytest.mark.parametrize("env", ["production", "development"])
def test_hosted_deployments_keep_cloudinary(env: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ENV", env)
    assert isinstance(blob_store(), CloudinaryBlobStore)


def test_selfhost_stores_on_the_local_volume(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ENV", "selfhost")
    monkeypatch.setattr(settings, "LOCAL_FILE_STORAGE_PATH", "/data/files")
    store = blob_store()
    assert isinstance(store, LocalVolumeBlobStore)
    assert store.root == Path("/data/files")


def test_selfhost_may_choose_cloudinary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ENV", "selfhost")
    monkeypatch.setattr(settings, "BLOB_STORE", BlobStoreKind.CLOUDINARY)
    assert isinstance(blob_store(), CloudinaryBlobStore)


class TestBootCheck:
    def test_an_unwritable_local_volume_stops_the_boot(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "ENV", "selfhost")
        monkeypatch.setattr(settings, "LOCAL_FILE_STORAGE_PATH", str(tmp_path))
        tmp_path.chmod(0o500)
        try:
            with pytest.raises(AppError) as raised:
                ensure_local_blob_store_ready()
        finally:
            tmp_path.chmod(0o700)
        assert raised.value.code == "file_storage_not_writable"

    def test_a_writable_local_volume_boots(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "ENV", "selfhost")
        monkeypatch.setattr(settings, "LOCAL_FILE_STORAGE_PATH", str(tmp_path))
        ensure_local_blob_store_ready()

    def test_cloudinary_never_checks_a_local_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "ENV", "selfhost")
        monkeypatch.setattr(settings, "BLOB_STORE", BlobStoreKind.CLOUDINARY)
        monkeypatch.setattr(settings, "LOCAL_FILE_STORAGE_PATH", "/nonexistent/gaia-files")
        ensure_local_blob_store_ready()


class TestCloudinaryBlobStore:
    async def test_put_makes_the_same_sdk_call_and_returns_the_secure_url(
        self, cloudinary_sdk: MagicMock
    ) -> None:
        cloudinary_sdk.upload.return_value = {"secure_url": "https://res.cloudinary.com/x.png"}

        url = await CloudinaryBlobStore().put(
            "u1",
            "file_1_a.png",
            b"bytes",
            resource_type="image",
            kind=BlobKind.CHAT_UPLOAD,
            content_type="image/png",
        )

        assert url == "https://res.cloudinary.com/x.png"
        (source,), kwargs = cloudinary_sdk.upload.call_args
        assert isinstance(source, io.BytesIO) and source.getvalue() == b"bytes"
        assert kwargs == {"resource_type": "image", "public_id": "file_1_a.png", "overwrite": True}

    async def test_put_without_a_secure_url_is_a_500(self, cloudinary_sdk: MagicMock) -> None:
        cloudinary_sdk.upload.return_value = {"public_id": "x"}
        async with captured_wide_event() as event:
            with pytest.raises(HTTPException) as raised:
                await CloudinaryBlobStore().put(
                    "u1",
                    "x",
                    b"b",
                    resource_type="auto",
                    kind=BlobKind.CHAT_UPLOAD,
                    content_type="image/png",
                )
        assert raised.value.status_code == 500
        assert raised.value.detail == "Invalid response from file upload service"
        assert event["errors"] == [
            {"msg": "[blobs] cloudinary upload returned no secure_url", "public_id": "x"}
        ]

    def test_an_unconfigured_account_refuses_with_the_fix(self) -> None:
        with (
            patch("app.config.cloudinary.providers.get", return_value=None),
            pytest.raises(AppError) as raised,
        ):
            CloudinaryBlobStore().ensure_ready()
        assert raised.value.status_code == 503
        assert raised.value.code == "file_storage_not_configured"

    async def test_delete_destroys_by_public_id_off_the_event_loop(
        self, cloudinary_sdk: MagicMock
    ) -> None:
        loop_thread = threading.current_thread()
        threads: list[threading.Thread] = []

        def destroy(public_id: str) -> dict[str, str]:
            threads.append(threading.current_thread())
            return {"result": "ok"}

        cloudinary_sdk.destroy.side_effect = destroy
        await CloudinaryBlobStore().delete("u1", "support/T_a.png")

        cloudinary_sdk.destroy.assert_called_once_with("support/T_a.png")
        assert threads and threads[0] is not loop_thread

    async def test_a_failed_delete_is_logged_not_raised(self, cloudinary_sdk: MagicMock) -> None:
        cloudinary_sdk.destroy.side_effect = RuntimeError("network")
        async with captured_wide_event() as event:
            await CloudinaryBlobStore().delete("u1", "x")
        assert event["errors"] == [
            {
                "msg": "[blobs] cloudinary delete failed",
                "public_id": "x",
                "error": "network",
                "error_type": "RuntimeError",
            }
        ]

    async def test_an_unconfirmed_delete_is_a_warning(self, cloudinary_sdk: MagicMock) -> None:
        cloudinary_sdk.destroy.return_value = {"result": "not found"}
        async with captured_wide_event() as event:
            await CloudinaryBlobStore().delete("u1", "support/T_a.png")
        assert event["warnings"] == [
            {"msg": "[blobs] cloudinary delete did not confirm", "public_id": "support/T_a.png"}
        ]

    async def test_a_confirmed_delete_logs_nothing(self, cloudinary_sdk: MagicMock) -> None:
        cloudinary_sdk.destroy.return_value = {"result": "ok"}
        async with captured_wide_event() as event:
            await CloudinaryBlobStore().delete("u1", "x")
        assert "warnings" not in event
        assert "errors" not in event

    async def test_a_stalled_download_times_out_instead_of_hanging(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def _accept_and_stall(
            _reader: asyncio.StreamReader, writer: asyncio.StreamWriter
        ) -> None:
            await asyncio.Event().wait()

        server = await asyncio.start_server(_accept_and_stall, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        monkeypatch.setattr("app.services.blob_store.BLOB_DOWNLOAD_TIMEOUT_SECONDS", 0.05)
        try:
            with pytest.raises(httpx.ReadTimeout):
                await asyncio.wait_for(
                    CloudinaryBlobStore().read("u1", "x", f"http://127.0.0.1:{port}/x.png"),
                    timeout=5,
                )
        finally:
            server.close()


class TestLocalVolumeBlobStore:
    async def test_put_then_open_and_read_round_trip(self, tmp_path: Path) -> None:
        store = LocalVolumeBlobStore(tmp_path)

        url = await store.put(
            "u1",
            "support/T 1_a.png",
            b"png",
            resource_type="auto",
            kind=BlobKind.CHAT_UPLOAD,
            content_type="image/png",
        )

        assert url == "/api/v1/blobs/u1/support_T_1_a.png"
        blob = await store.open("u1", "support_T_1_a.png")
        assert blob is not None
        assert blob.content_type == "image/png"
        assert await store.read("u1", "support/T 1_a.png", url) == b"png"

    async def test_one_owner_cannot_open_anothers_blob(self, tmp_path: Path) -> None:
        store = LocalVolumeBlobStore(tmp_path)
        await store.put(
            "alice",
            "k",
            b"secret",
            resource_type="auto",
            kind=BlobKind.CHAT_UPLOAD,
            content_type="text/plain",
        )

        assert await store.open("bob", "k") is None

    @pytest.mark.parametrize("key", ["../alice/k", "..", "a/b"])
    async def test_a_key_that_is_not_one_flat_segment_never_resolves(
        self, tmp_path: Path, key: str
    ) -> None:
        store = LocalVolumeBlobStore(tmp_path)
        await store.put(
            "alice",
            "k",
            b"secret",
            resource_type="auto",
            kind=BlobKind.CHAT_UPLOAD,
            content_type="text/plain",
        )

        assert await store.open("bob", key) is None

    async def test_public_ids_cannot_escape_the_owner_directory(self, tmp_path: Path) -> None:
        assert local_blob_key("../../etc/passwd") == "_.._etc_passwd"
        (tmp_path / "files").mkdir()
        store = LocalVolumeBlobStore(tmp_path / "files")
        await store.put(
            "u1",
            "../../x",
            b"b",
            resource_type="auto",
            kind=BlobKind.CHAT_UPLOAD,
            content_type="text/plain",
        )
        assert [p.name for p in (tmp_path / "files" / "u1").iterdir()] == ["_.._x"]

    async def test_an_unsafe_owner_id_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="owner"):
            await LocalVolumeBlobStore(tmp_path).put(
                "../u1",
                "k",
                b"b",
                resource_type="auto",
                kind=BlobKind.CHAT_UPLOAD,
                content_type="text/plain",
            )

    async def test_delete_removes_the_blob_and_tolerates_a_missing_one(
        self, tmp_path: Path
    ) -> None:
        store = LocalVolumeBlobStore(tmp_path)
        await store.put(
            "u1",
            "k",
            b"b",
            resource_type="auto",
            kind=BlobKind.CHAT_UPLOAD,
            content_type="text/plain",
        )

        await store.delete("u1", "k")
        await store.delete("u1", "k")

        assert await store.open("u1", "k") is None

    async def test_reading_a_missing_blob_is_loud(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            await LocalVolumeBlobStore(tmp_path).read("u1", "nope", "/api/v1/blobs/u1/nope")

    async def test_an_unmounted_volume_refuses_instead_of_writing_into_the_container(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("app.services.blob_store._is_mountpoint", lambda _p: False)
        with pytest.raises(AppError) as raised:
            await LocalVolumeBlobStore(tmp_path).put(
                "u1",
                "k",
                b"b",
                resource_type="auto",
                kind=BlobKind.CHAT_UPLOAD,
                content_type="text/plain",
            )
        assert raised.value.status_code == 503
        assert raised.value.code == "file_storage_not_mounted"
        assert list(tmp_path.iterdir()) == []


def test_every_blob_kind_has_an_audience() -> None:
    assert set(BLOB_AUDIENCE) == set(BlobKind)


def _write_raw_blob(blob_dir: Path, *, meta: bool = True) -> None:
    blob_dir.mkdir(parents=True)
    (blob_dir / "data").write_bytes(b"raw")
    if meta:
        (blob_dir / "meta.json").write_text(
            LocalBlobMeta(content_type="text/plain", kind=BlobKind.CHAT_UPLOAD).model_dump_json()
        )


class TestLocalVolumeBlobStoreEdges:
    def test_a_key_keeps_every_safe_character_and_drops_leading_dots(self) -> None:
        assert local_blob_key("Xray-1_v2.png") == "Xray-1_v2.png"
        assert local_blob_key("..hidden") == "hidden"

    def test_a_public_id_with_nothing_usable_is_refused(self) -> None:
        with pytest.raises(ValueError) as raised:
            local_blob_key("...")
        assert str(raised.value) == "blob public_id has no usable characters"

    def test_the_mount_check_inspects_the_stores_own_root(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root = tmp_path / "volume"
        root.mkdir()
        monkeypatch.setattr("app.services.blob_store._is_mountpoint", lambda p: p == root)

        LocalVolumeBlobStore(root).ensure_ready()

    def test_an_unmounted_volume_names_the_path_and_the_fix(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("app.services.blob_store._is_mountpoint", lambda _p: False)
        with pytest.raises(AppError) as raised:
            LocalVolumeBlobStore(tmp_path).ensure_ready()
        assert raised.value.status_code == 503
        assert raised.value.to_dict() == {
            "message": "File uploads are not set up on this instance.",
            "why": f"{tmp_path} is not a mounted volume, so files would vanish with the container.",
            "fix": (
                "Mount a persistent volume at LOCAL_FILE_STORAGE_PATH; the self-host "
                "compose file mounts gaia-selfhost_files there."
            ),
            "code": "file_storage_not_mounted",
        }

    def test_an_unwritable_volume_names_the_path_and_the_fix(self, tmp_path: Path) -> None:
        tmp_path.chmod(0o500)
        try:
            with pytest.raises(AppError) as raised:
                LocalVolumeBlobStore(tmp_path).ensure_ready()
        finally:
            tmp_path.chmod(0o700)
        assert raised.value.status_code == 503
        assert raised.value.to_dict() == {
            "message": "File uploads are not set up on this instance.",
            "why": f"{tmp_path} is not writable by the API's user.",
            "fix": (
                "Give the API's user write access to LOCAL_FILE_STORAGE_PATH, or set "
                "BLOB_STORE=cloudinary with Cloudinary credentials."
            ),
            "code": "file_storage_not_writable",
        }

    async def test_an_unsafe_owner_id_names_the_owner(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError) as raised:
            await LocalVolumeBlobStore(tmp_path).delete("../u1", "k")
        assert str(raised.value) == "unsafe blob owner id"

    async def test_putting_the_same_blob_again_replaces_it(self, tmp_path: Path) -> None:
        store = LocalVolumeBlobStore(tmp_path)
        url = ""
        for content, content_type in ((b"v1", "text/plain"), (b"v2", "text/csv")):
            url = await store.put(
                "u1",
                "k",
                content,
                resource_type="auto",
                kind=BlobKind.CHAT_UPLOAD,
                content_type=content_type,
            )

        blob = await store.open("u1", "k")
        assert blob is not None
        assert blob.content_type == "text/csv"
        assert await store.read("u1", "k", url) == b"v2"

    async def test_reading_a_missing_blob_names_it(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError) as raised:
            await LocalVolumeBlobStore(tmp_path).read("u1", "nope", "/api/v1/blobs/u1/nope")
        assert str(raised.value) == "no local blob 'nope' for owner u1"

    async def test_deleting_a_missing_blob_is_a_warning(self, tmp_path: Path) -> None:
        async with captured_wide_event() as event:
            await LocalVolumeBlobStore(tmp_path).delete("u1", "gone")
        assert event["warnings"] == [
            {"msg": "[blobs] local blob to delete is missing", "owner_id": "u1", "key": "gone"}
        ]

    async def test_a_dot_key_never_resolves_even_when_its_directory_exists(
        self, tmp_path: Path
    ) -> None:
        _write_raw_blob(tmp_path / "u1" / ".hidden")

        assert await LocalVolumeBlobStore(tmp_path).open("u1", ".hidden") is None

    async def test_a_blob_without_its_metadata_does_not_resolve(self, tmp_path: Path) -> None:
        _write_raw_blob(tmp_path / "u1" / "k", meta=False)

        assert await LocalVolumeBlobStore(tmp_path).open("u1", "k") is None


async def test_a_blob_that_does_not_resolve_is_a_plain_not_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "ENV", "selfhost")
    monkeypatch.setattr(settings, "LOCAL_FILE_STORAGE_PATH", str(tmp_path))

    with pytest.raises(AppError) as raised:
        await open_readable_blob("u2", "u1", "missing")

    assert raised.value.status_code == 404
    assert raised.value.to_dict() == {"message": "File not found", "code": "blob_not_found"}
