"""Workspace projection: naming, mirroring, sidecars, and deletion."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from app.services.files import sandbox
from app.services.files.sandbox import UploadMirror, workspace_upload_name
from app.services.storage import FsOps, JuiceFSUnavailable

CONV = "conv-1"
USER = "user-1"


class _AsyncContext:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *_exc: object) -> bool:
        return False


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(sandbox, "session_root", lambda user_id, conv_id: tmp_path)
    uploads = tmp_path / "user-uploaded"
    uploads.mkdir()
    return tmp_path, uploads


def _mirror(**overrides) -> UploadMirror:
    values = {
        "file_id": "f-1",
        "filename": "table.png",
        "content": b"image-bytes",
        "content_type": "image/png",
        "description": "a table",
        "page_wise_summary": None,
    }
    values.update(overrides)
    return UploadMirror(**values)


def _fake_writer(root: Path):
    async def write(user_id, conversation_id, relative_path, content):
        target = root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        return target, f"/workspace/sessions/{conversation_id}/{relative_path}"

    return AsyncMock(side_effect=write)


def _timer() -> MagicMock:
    return MagicMock(return_value=_AsyncContext())


class TestWorkspaceUploadName:
    def test_prefixes_the_file_id_so_distinct_files_cannot_collide(self) -> None:
        assert workspace_upload_name("f-1", "image.png") == "f-1_image.png"

    def test_sanitizes_the_display_name(self) -> None:
        assert workspace_upload_name("f-1", "my screenshot (1).png") == "f-1_my_screenshot__1_.png"

    def test_caps_the_component_at_the_filesystem_limit(self) -> None:
        name = workspace_upload_name("f-1", "a" * 400 + ".png")

        assert name.startswith("f-1_")
        assert len(name.encode()) == 255

    def test_rejects_a_name_that_sanitizes_away(self) -> None:
        with pytest.raises(ValueError):
            workspace_upload_name("f-1", "...")


class TestMirrorUpload:
    async def test_writes_the_bytes_and_the_sidecar(self, workspace):
        root, uploads = workspace
        timer = _timer()

        with (
            patch.object(sandbox, "fs_timer", timer),
            patch.object(sandbox, "write_session_file", _fake_writer(root)),
            patch.object(sandbox, "chmod_path", AsyncMock()) as chmod,
            patch.object(sandbox, "publish_artifact_event", AsyncMock()) as publish,
        ):
            path = await sandbox.mirror_upload(USER, CONV, _mirror())

        assert path == f"/workspace/sessions/{CONV}/user-uploaded/f-1_table.png"
        timer.assert_called_once_with(FsOps.UPLOAD_PERSIST_SANDBOX)
        assert (uploads / "f-1_table.png").read_bytes() == b"image-bytes"
        sidecar = (uploads / "f-1_table.png.summary.md").read_text()
        assert "# Summary: table.png" in sidecar
        assert "`image/png`" in sidecar
        assert "a table" in sidecar
        assert chmod.await_args_list == [
            call(uploads / "f-1_table.png", 0o444),
            call(uploads / "f-1_table.png.summary.md", 0o444),
        ]
        assert publish.await_args.args[0] == USER
        event = publish.await_args.args[1]
        assert event["event"] == "upload"
        assert event["session_id"] == CONV
        assert event["path"] == "f-1_table.png"
        assert event["size_bytes"] == len(b"image-bytes")
        assert event["content_type"] == "image/png"

    async def test_no_summary_means_no_sidecar(self, workspace):
        root, uploads = workspace
        writer = _fake_writer(root)

        with (
            patch.object(sandbox, "fs_timer", _timer()),
            patch.object(sandbox, "write_session_file", writer),
            patch.object(sandbox, "chmod_path", AsyncMock()),
            patch.object(sandbox, "publish_artifact_event", AsyncMock()),
        ):
            await sandbox.mirror_upload(
                USER, CONV, _mirror(description=None, page_wise_summary=None)
            )

        assert writer.await_count == 1
        assert not (uploads / "f-1_table.png.summary.md").exists()

    async def test_an_unsafe_filename_is_logged_and_skipped(self, workspace):
        root, _uploads = workspace
        writer = _fake_writer(root)

        with (
            patch.object(sandbox, "fs_timer", _timer()),
            patch.object(sandbox, "write_session_file", writer),
            patch.object(sandbox, "log") as mock_log,
        ):
            assert await sandbox.mirror_upload(USER, CONV, _mirror(filename="...")) is None

        writer.assert_not_awaited()
        assert mock_log.warning.call_args.args[0] == (
            "[files] skipping sandbox mirror, unsafe filename"
        )
        kwargs = mock_log.warning.call_args.kwargs
        assert kwargs["filename"] == "..."
        assert kwargs["error"] == "filename is empty after sanitization"
        assert kwargs["error_type"] == "ValueError"
        assert kwargs["user_id"] == USER
        assert kwargs["conversation_id"] == CONV

    async def test_returns_none_when_the_mount_is_unavailable(self, workspace):
        root, _uploads = workspace

        with (
            patch.object(sandbox, "fs_timer", _timer()),
            patch.object(
                sandbox,
                "write_session_file",
                AsyncMock(side_effect=JuiceFSUnavailable("no mount")),
            ),
            patch.object(sandbox, "log") as mock_log,
        ):
            assert await sandbox.mirror_upload(USER, CONV, _mirror()) is None

        mock_log.warning.assert_called_once_with(
            "[files] juicefs unavailable; not mirroring upload",
            error="no mount",
            error_type="JuiceFSUnavailable",
            user_id=USER,
            conversation_id=CONV,
        )

    async def test_returns_none_on_an_unexpected_error(self, workspace):
        root, _uploads = workspace

        with (
            patch.object(sandbox, "fs_timer", _timer()),
            patch.object(
                sandbox,
                "write_session_file",
                AsyncMock(side_effect=RuntimeError("io")),
            ),
            patch.object(sandbox, "log") as mock_log,
        ):
            assert await sandbox.mirror_upload(USER, CONV, _mirror()) is None

        mock_log.error.assert_called_once_with(
            "[files] failed to mirror upload to sandbox",
            error="io",
            error_type="RuntimeError",
            user_id=USER,
            conversation_id=CONV,
            exc_info=True,
        )


class TestWriteSummarySidecar:
    async def test_writes_the_markdown_and_chmods_it(self, workspace):
        root, uploads = workspace
        writer = _fake_writer(root)

        with (
            patch.object(sandbox, "_overwrite_read_only", AsyncMock()) as overwrite,
            patch.object(sandbox, "write_session_file", writer),
            patch.object(sandbox, "chmod_path", AsyncMock()) as chmod,
        ):
            await sandbox.write_summary_sidecar(USER, CONV, "f-1_table.png", "summary")

        overwrite.assert_awaited_once_with(USER, CONV, "user-uploaded/f-1_table.png.summary.md")
        kwargs = writer.await_args.kwargs
        assert kwargs["user_id"] == USER
        assert kwargs["conversation_id"] == CONV
        assert kwargs["relative_path"] == "user-uploaded/f-1_table.png.summary.md"
        assert kwargs["content"] == b"summary"
        assert (uploads / "f-1_table.png.summary.md").read_text() == "summary"
        chmod.assert_awaited_once_with(uploads / "f-1_table.png.summary.md", 0o444)

    async def test_a_failure_is_logged_and_swallowed(self, workspace):
        with (
            patch.object(sandbox, "_overwrite_read_only", AsyncMock()),
            patch.object(
                sandbox,
                "write_session_file",
                AsyncMock(side_effect=RuntimeError("io")),
            ),
            patch.object(sandbox, "log") as mock_log,
        ):
            await sandbox.write_summary_sidecar(USER, CONV, "f-1_table.png", "summary")

        mock_log.warning.assert_called_once_with(
            "[files] failed to write summary sidecar for",
            safe_filename="f-1_table.png",
            error="io",
            error_type="RuntimeError",
            user_id=USER,
            conversation_id=CONV,
        )

    async def test_a_missing_mount_is_silent(self, workspace):
        with (
            patch.object(sandbox, "_overwrite_read_only", AsyncMock()),
            patch.object(
                sandbox,
                "write_session_file",
                AsyncMock(side_effect=JuiceFSUnavailable("no mount")),
            ),
            patch.object(sandbox, "log") as mock_log,
        ):
            await sandbox.write_summary_sidecar(USER, CONV, "f-1_table.png", "summary")

        mock_log.warning.assert_not_called()


class TestDeleteUpload:
    async def test_removes_the_file_and_sidecar(self, workspace):
        root, uploads = workspace
        (uploads / "f-1_a.png").write_bytes(b"x")
        (uploads / "f-1_a.png.summary.md").write_text("summary")
        timer = _timer()

        with (
            patch.object(sandbox, "session_root", return_value=root) as session_root,
            patch.object(sandbox, "fs_timer", timer),
            patch.object(sandbox, "chmod_path", AsyncMock()) as chmod,
            patch.object(sandbox, "publish_artifact_event", AsyncMock()) as publish,
        ):
            assert await sandbox.delete_upload(USER, CONV, "f-1_a.png") is True

        timer.assert_called_once_with(FsOps.UPLOAD_PERSIST_SANDBOX)
        session_root.assert_called_once_with(USER, CONV)
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
        _root, uploads = workspace
        (uploads / "f-1_a.png.summary.md").write_text("summary")

        with (
            patch.object(sandbox, "fs_timer", _timer()),
            patch.object(sandbox, "chmod_path", AsyncMock()),
            patch.object(sandbox, "publish_artifact_event", AsyncMock()),
        ):
            assert await sandbox.delete_upload(USER, CONV, "f-1_a.png") is True

        assert not (uploads / "f-1_a.png.summary.md").exists()

    async def test_returns_false_when_nothing_is_there(self, workspace):
        with (
            patch.object(sandbox, "fs_timer", _timer()),
            patch.object(sandbox, "chmod_path", AsyncMock()) as chmod,
            patch.object(sandbox, "publish_artifact_event", AsyncMock()) as publish,
        ):
            assert await sandbox.delete_upload(USER, CONV, "missing.png") is False

        chmod.assert_not_awaited()
        publish.assert_not_awaited()

    async def test_returns_false_when_the_mount_is_unavailable(self, workspace):
        _root, uploads = workspace
        (uploads / "f-1_a.png").write_bytes(b"x")

        with (
            patch.object(sandbox, "fs_timer", _timer()),
            patch.object(
                sandbox, "chmod_path", AsyncMock(side_effect=JuiceFSUnavailable("no mount"))
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
        _root, uploads = workspace
        (uploads / "f-1_a.png").write_bytes(b"x")

        with (
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
