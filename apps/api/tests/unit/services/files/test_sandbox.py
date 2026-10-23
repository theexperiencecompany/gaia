"""Workspace projection: rename and delete of uploads and their sidecars."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from app.services.files import sandbox
from app.services.storage import FsOps, JuiceFSUnavailable

CONV = "conv-1"
USER = "user-1"
OLD = "f-1_old.png"
NEW = "f-1_new.png"


class _AsyncContext:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *_exc: object) -> bool:
        return False


@pytest.fixture
def workspace(tmp_path):
    uploads = tmp_path / "user-uploaded"
    uploads.mkdir()
    return tmp_path, uploads


def _write(uploads: Path, name: str, body: bytes = b"x") -> Path:
    target = uploads / name
    target.write_bytes(body)
    return target


def _timer() -> MagicMock:
    return MagicMock(return_value=_AsyncContext())


class TestRenameUpload:
    async def test_moves_the_file_and_sidecar(self, workspace):
        root, uploads = workspace
        _write(uploads, OLD)
        _write(uploads, f"{OLD}.summary.md")
        timer = _timer()

        with (
            patch.object(sandbox, "session_root", return_value=root) as session_root,
            patch.object(sandbox, "fs_timer", timer),
            patch.object(sandbox, "chmod_path", AsyncMock()) as chmod,
            patch.object(sandbox, "publish_artifact_event", AsyncMock()) as publish,
        ):
            new_path = await sandbox.rename_upload(
                USER,
                CONV,
                OLD,
                NEW,
                content_type="image/png",
                size_bytes=10,
            )

        assert new_path == f"/workspace/sessions/{CONV}/user-uploaded/{NEW}"
        session_root.assert_called_once_with(USER, CONV)
        timer.assert_called_once_with(FsOps.UPLOAD_PERSIST_SANDBOX)
        assert chmod.await_args_list == [
            call(uploads / OLD, 0o644),
            call(uploads / NEW, 0o444),
            call(uploads / f"{OLD}.summary.md", 0o644),
            call(uploads / f"{NEW}.summary.md", 0o444),
        ]
        assert not (uploads / OLD).exists()
        assert (uploads / NEW).read_bytes() == b"x"
        assert not (uploads / f"{OLD}.summary.md").exists()
        assert (uploads / f"{NEW}.summary.md").exists()

        removed, landed = publish.await_args_list
        assert removed.args[0] == USER
        assert removed.args[1] == {"event": "remove", "session_id": CONV, "path": OLD}
        assert landed.args[0] == USER
        assert landed.args[1]["event"] == "upload"
        assert landed.args[1]["session_id"] == CONV
        assert landed.args[1]["path"] == NEW
        assert landed.args[1]["size_bytes"] == 10
        assert landed.args[1]["content_type"] == "image/png"

    async def test_returns_none_when_the_source_is_missing(self, workspace):
        root, _uploads = workspace

        with (
            patch.object(sandbox, "session_root", return_value=root),
            patch.object(sandbox, "fs_timer", _timer()),
            patch.object(sandbox, "chmod_path", AsyncMock()) as chmod,
            patch.object(sandbox, "publish_artifact_event", AsyncMock()) as publish,
        ):
            assert (
                await sandbox.rename_upload(
                    USER,
                    CONV,
                    "missing.png",
                    NEW,
                    content_type="image/png",
                    size_bytes=10,
                )
                is None
            )

        chmod.assert_not_awaited()
        publish.assert_not_awaited()

    async def test_returns_none_when_the_mount_is_unavailable(self, workspace):
        root, uploads = workspace
        _write(uploads, OLD)

        with (
            patch.object(sandbox, "session_root", return_value=root),
            patch.object(sandbox, "fs_timer", _timer()),
            patch.object(
                sandbox,
                "chmod_path",
                AsyncMock(side_effect=JuiceFSUnavailable("no mount")),
            ),
            patch.object(sandbox, "publish_artifact_event", AsyncMock()) as publish,
            patch.object(sandbox, "log") as mock_log,
        ):
            assert (
                await sandbox.rename_upload(
                    USER,
                    CONV,
                    OLD,
                    NEW,
                    content_type="image/png",
                    size_bytes=10,
                )
                is None
            )

        publish.assert_not_awaited()
        mock_log.warning.assert_called_once_with(
            "[files] juicefs unavailable; not renaming upload",
            error="no mount",
            error_type="JuiceFSUnavailable",
            user_id=USER,
            conversation_id=CONV,
        )

    async def test_returns_none_on_an_unexpected_error(self, workspace):
        root, uploads = workspace
        _write(uploads, OLD)

        with (
            patch.object(sandbox, "session_root", return_value=root),
            patch.object(sandbox, "fs_timer", _timer()),
            patch.object(sandbox, "chmod_path", AsyncMock(side_effect=RuntimeError("io"))),
            patch.object(sandbox, "publish_artifact_event", AsyncMock()) as publish,
            patch.object(sandbox, "log") as mock_log,
        ):
            assert (
                await sandbox.rename_upload(
                    USER,
                    CONV,
                    OLD,
                    NEW,
                    content_type="image/png",
                    size_bytes=10,
                )
                is None
            )

        publish.assert_not_awaited()
        mock_log.error.assert_called_once_with(
            "[files] failed to rename upload in sandbox",
            error="io",
            error_type="RuntimeError",
            user_id=USER,
            conversation_id=CONV,
            exc_info=True,
        )


class TestDeleteUpload:
    async def test_removes_the_file_and_sidecar(self, workspace):
        root, uploads = workspace
        _write(uploads, "f-1_a.png")
        _write(uploads, "f-1_a.png.summary.md")
        timer = _timer()

        with (
            patch.object(sandbox, "session_root", return_value=root) as session_root,
            patch.object(sandbox, "fs_timer", timer),
            patch.object(sandbox, "chmod_path", AsyncMock()) as chmod,
            patch.object(sandbox, "publish_artifact_event", AsyncMock()) as publish,
        ):
            assert await sandbox.delete_upload(USER, CONV, "f-1_a.png") is True

        session_root.assert_called_once_with(USER, CONV)
        timer.assert_called_once_with(FsOps.UPLOAD_PERSIST_SANDBOX)
        assert chmod.await_args_list == [
            call(uploads / "f-1_a.png", 0o644),
            call(uploads / "f-1_a.png.summary.md", 0o644),
        ]
        assert not (uploads / "f-1_a.png").exists()
        assert not (uploads / "f-1_a.png.summary.md").exists()
        assert publish.await_args.args[0] == USER
        assert publish.await_args.args[1] == {
            "event": "remove",
            "session_id": CONV,
            "path": "f-1_a.png",
        }

    async def test_removes_a_sidecar_whose_file_is_already_gone(self, workspace):
        root, uploads = workspace
        _write(uploads, "f-1_a.png.summary.md")

        with (
            patch.object(sandbox, "session_root", return_value=root),
            patch.object(sandbox, "fs_timer", _timer()),
            patch.object(sandbox, "chmod_path", AsyncMock()),
            patch.object(sandbox, "publish_artifact_event", AsyncMock()),
        ):
            assert await sandbox.delete_upload(USER, CONV, "f-1_a.png") is True

        assert not (uploads / "f-1_a.png.summary.md").exists()

    async def test_returns_false_when_nothing_is_there(self, workspace):
        root, _uploads = workspace

        with (
            patch.object(sandbox, "session_root", return_value=root),
            patch.object(sandbox, "fs_timer", _timer()),
            patch.object(sandbox, "chmod_path", AsyncMock()) as chmod,
            patch.object(sandbox, "publish_artifact_event", AsyncMock()) as publish,
        ):
            assert await sandbox.delete_upload(USER, CONV, "missing.png") is False

        chmod.assert_not_awaited()
        publish.assert_not_awaited()

    async def test_returns_false_when_the_mount_is_unavailable(self, workspace):
        root, uploads = workspace
        _write(uploads, "f-1_a.png")

        with (
            patch.object(sandbox, "session_root", return_value=root),
            patch.object(sandbox, "fs_timer", _timer()),
            patch.object(
                sandbox,
                "chmod_path",
                AsyncMock(side_effect=JuiceFSUnavailable("no mount")),
            ),
            patch.object(sandbox, "publish_artifact_event", AsyncMock()) as publish,
            patch.object(sandbox, "log") as mock_log,
        ):
            assert await sandbox.delete_upload(USER, CONV, "f-1_a.png") is False

        publish.assert_not_awaited()
        mock_log.warning.assert_called_once_with(
            "[files] juicefs unavailable; not deleting upload",
            error="no mount",
            error_type="JuiceFSUnavailable",
            user_id=USER,
            conversation_id=CONV,
        )

    async def test_returns_false_on_an_unexpected_error(self, workspace):
        root, uploads = workspace
        _write(uploads, "f-1_a.png")

        with (
            patch.object(sandbox, "session_root", return_value=root),
            patch.object(sandbox, "fs_timer", _timer()),
            patch.object(sandbox, "chmod_path", AsyncMock(side_effect=RuntimeError("io"))),
            patch.object(sandbox, "publish_artifact_event", AsyncMock()) as publish,
            patch.object(sandbox, "log") as mock_log,
        ):
            assert await sandbox.delete_upload(USER, CONV, "f-1_a.png") is False

        publish.assert_not_awaited()
        mock_log.error.assert_called_once_with(
            "[files] failed to delete upload from sandbox",
            error="io",
            error_type="RuntimeError",
            user_id=USER,
            conversation_id=CONV,
            exc_info=True,
        )
