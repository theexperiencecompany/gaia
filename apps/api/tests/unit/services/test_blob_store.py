"""The blob store backends and which one each deployment gets."""

from __future__ import annotations

from collections.abc import Iterator
import io
from pathlib import Path
import threading
from unittest.mock import MagicMock, patch

from fastapi import HTTPException
import pytest

from app.config.deployment import BlobStoreKind
from app.config.settings import settings
from app.services.blob_store import (
    CloudinaryBlobStore,
    LocalVolumeBlobStore,
    blob_store,
    ensure_local_blob_store_ready,
    local_blob_key,
)
from app.utils.errors import AppError


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
            "u1", "file_1_a.png", b"bytes", resource_type="image", content_type="image/png"
        )

        assert url == "https://res.cloudinary.com/x.png"
        (source,), kwargs = cloudinary_sdk.upload.call_args
        assert isinstance(source, io.BytesIO) and source.getvalue() == b"bytes"
        assert kwargs == {"resource_type": "image", "public_id": "file_1_a.png", "overwrite": True}

    async def test_put_without_a_secure_url_is_a_500(self, cloudinary_sdk: MagicMock) -> None:
        cloudinary_sdk.upload.return_value = {"public_id": "x"}
        with pytest.raises(HTTPException) as raised:
            await CloudinaryBlobStore().put(
                "u1", "x", b"b", resource_type="auto", content_type="image/png"
            )
        assert raised.value.status_code == 500

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
        with patch("app.services.blob_store.log") as log:
            await CloudinaryBlobStore().delete("u1", "x")
        assert log.error.call_args.kwargs["error"] == "network"


class TestLocalVolumeBlobStore:
    async def test_put_then_open_and_read_round_trip(self, tmp_path: Path) -> None:
        store = LocalVolumeBlobStore(tmp_path)

        url = await store.put(
            "u1", "support/T 1_a.png", b"png", resource_type="auto", content_type="image/png"
        )

        assert url == "/api/v1/blobs/u1/support_T_1_a.png"
        blob = await store.open("u1", "support_T_1_a.png")
        assert blob is not None
        assert blob.content_type == "image/png"
        assert await store.read("u1", "support/T 1_a.png", url) == b"png"

    async def test_one_owner_cannot_open_anothers_blob(self, tmp_path: Path) -> None:
        store = LocalVolumeBlobStore(tmp_path)
        await store.put("alice", "k", b"secret", resource_type="auto", content_type="text/plain")

        assert await store.open("bob", "k") is None

    @pytest.mark.parametrize("key", ["../alice/k", "..", "a/b"])
    async def test_a_key_that_is_not_one_flat_segment_never_resolves(
        self, tmp_path: Path, key: str
    ) -> None:
        store = LocalVolumeBlobStore(tmp_path)
        await store.put("alice", "k", b"secret", resource_type="auto", content_type="text/plain")

        assert await store.open("bob", key) is None

    async def test_public_ids_cannot_escape_the_owner_directory(self, tmp_path: Path) -> None:
        assert local_blob_key("../../etc/passwd") == "_.._etc_passwd"
        (tmp_path / "files").mkdir()
        store = LocalVolumeBlobStore(tmp_path / "files")
        await store.put("u1", "../../x", b"b", resource_type="auto", content_type="text/plain")
        assert [p.name for p in (tmp_path / "files" / "u1").iterdir()] == ["_.._x"]

    async def test_an_unsafe_owner_id_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="owner"):
            await LocalVolumeBlobStore(tmp_path).put(
                "../u1", "k", b"b", resource_type="auto", content_type="text/plain"
            )

    async def test_delete_removes_the_blob_and_tolerates_a_missing_one(
        self, tmp_path: Path
    ) -> None:
        store = LocalVolumeBlobStore(tmp_path)
        await store.put("u1", "k", b"b", resource_type="auto", content_type="text/plain")

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
                "u1", "k", b"b", resource_type="auto", content_type="text/plain"
            )
        assert raised.value.status_code == 503
        assert raised.value.code == "file_storage_not_mounted"
        assert list(tmp_path.iterdir()) == []
