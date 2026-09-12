"""Unit tests for gaia_task_files — the /workspace/gaia-tasks/ path router the
coding tools use so canvas.md / activity.md live on the todo doc, not on disk."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

from bson import ObjectId
import pytest

from app.constants.todos import GAIA_TRACKED_LABEL
from app.models.todo_models import TodoDocument
from app.services.gaia_task_files import (
    GaiaTaskFile,
    GaiaTaskPathError,
    NoteConflictError,
    RootFile,
    TaskFile,
    read_file,
    resolve,
    write_file,
)

_MOD = "app.services.gaia_task_files"
USER_ID = "507f1f77bcf86cd799439011"
TODO_ID = "66f838cc8829054e5f10e407"
SHORT = TODO_ID[-8:]
FOLDER = f"fix-the-thing-{SHORT}"


def _doc(**overrides: object) -> TodoDocument:
    data: dict[str, object] = {
        "id": TODO_ID,
        "user_id": USER_ID,
        "title": "Fix the thing",
        "labels": [GAIA_TRACKED_LABEL],
        "canvas_content": "# Fix the thing\n\n## Key Details\nk\n",
        "activity_content": "- 2026-09-01T09:00:00+00:00 started",
        "log_content": "## created",
        "created_at": datetime(2026, 9, 1, tzinfo=UTC),
        "updated_at": datetime(2026, 9, 2, tzinfo=UTC),
    }
    data.update(overrides)
    return TodoDocument(**data)


@pytest.fixture
def mock_repo():
    """The repository singleton is imported by both this module and the
    projection glue (index.md), so patch it at both seams."""
    with (
        patch(f"{_MOD}.todo_repository") as m,
        patch("app.services.gaia_tasks_fs.todo_repository", m),
    ):
        m.get = AsyncMock(return_value=None)
        m.find_tracked_by_short_id = AsyncMock(return_value=[])
        m.list_active_gaia_tracked_since = AsyncMock(return_value=[])
        m.is_valid_id = ObjectId.is_valid
        yield m


class TestResolve:
    async def test_non_gaia_tasks_path_is_none(self, mock_repo):
        assert await resolve("sessions/abc/scratch/x.md", USER_ID) is None
        assert await resolve("gaia-tasksish/x.md", USER_ID) is None

    async def test_root_index(self, mock_repo):
        assert await resolve("gaia-tasks/index.md", USER_ID) == RootFile(name="index.md")

    async def test_root_unknown_file_falls_through(self, mock_repo):
        assert await resolve("gaia-tasks/random.txt", USER_ID) is None

    async def test_folder_by_short_id(self, mock_repo):
        doc = _doc()
        mock_repo.find_tracked_by_short_id.return_value = [doc]

        ref = await resolve(f"gaia-tasks/{FOLDER}/canvas.md", USER_ID)

        assert ref == TaskFile(todo=doc, filename=GaiaTaskFile.CANVAS)
        mock_repo.find_tracked_by_short_id.assert_awaited_once_with(USER_ID, short_id=SHORT)

    async def test_folder_by_full_object_id(self, mock_repo):
        doc = _doc()
        mock_repo.get.return_value = doc

        ref = await resolve(f"gaia-tasks/{TODO_ID}/activity.md", USER_ID)

        assert ref == TaskFile(todo=doc, filename=GaiaTaskFile.ACTIVITY)
        mock_repo.find_tracked_by_short_id.assert_not_awaited()

    async def test_full_id_of_a_non_tracked_todo_is_an_error(self, mock_repo):
        mock_repo.get.return_value = _doc(labels=["work"])

        with pytest.raises(GaiaTaskPathError, match="not a tracked todo"):
            await resolve(f"gaia-tasks/{TODO_ID}/canvas.md", USER_ID)

    async def test_unknown_folder_is_an_error(self, mock_repo):
        with pytest.raises(GaiaTaskPathError, match="no tracked todo"):
            await resolve(f"gaia-tasks/{FOLDER}/canvas.md", USER_ID)

    async def test_ambiguous_short_id_is_an_error(self, mock_repo):
        mock_repo.find_tracked_by_short_id.return_value = [_doc(), _doc(id="a" * 16 + SHORT)]

        with pytest.raises(GaiaTaskPathError, match="matches 2"):
            await resolve(f"gaia-tasks/{FOLDER}/canvas.md", USER_ID)

    async def test_unknown_filename_in_task_folder_falls_through(self, mock_repo):
        mock_repo.find_tracked_by_short_id.return_value = [_doc()]

        assert await resolve(f"gaia-tasks/{FOLDER}/notes.md", USER_ID) is None

    async def test_gaia_tasks_under_a_session_dir_names_the_absolute_path(self, mock_repo):
        """A relative `gaia-tasks/...` resolves into the session scratch dir;
        the error must hand the model the path it meant."""
        with pytest.raises(GaiaTaskPathError, match="/workspace/gaia-tasks/"):
            await resolve(f"sessions/conv-1/scratch/gaia-tasks/{FOLDER}/canvas.md", USER_ID)

    async def test_nested_path_falls_through(self, mock_repo):
        assert await resolve(f"gaia-tasks/{FOLDER}/sub/canvas.md", USER_ID) is None


class TestReadFile:
    async def test_canvas_activity_log(self, mock_repo):
        doc = _doc()

        assert await read_file(TaskFile(doc, GaiaTaskFile.CANVAS), USER_ID) == doc.canvas_content
        assert (
            await read_file(TaskFile(doc, GaiaTaskFile.ACTIVITY), USER_ID) == doc.activity_content
        )
        assert await read_file(TaskFile(doc, GaiaTaskFile.LOG), USER_ID) == doc.log_content

    async def test_unset_bodies_read_as_empty(self, mock_repo):
        doc = _doc(canvas_content=None, activity_content=None)

        assert await read_file(TaskFile(doc, GaiaTaskFile.CANVAS), USER_ID) == ""
        assert await read_file(TaskFile(doc, GaiaTaskFile.ACTIVITY), USER_ID) == ""

    async def test_meta_json_matches_the_disk_projection(self, mock_repo):
        body = await read_file(TaskFile(_doc(), GaiaTaskFile.META), USER_ID)

        assert '"title": "Fix the thing"' in body
        assert '"completed": false' in body

    async def test_index_lists_the_active_set(self, mock_repo):
        mock_repo.list_active_gaia_tracked_since.return_value = [_doc()]

        body = await read_file(RootFile("index.md"), USER_ID)

        assert f"`{FOLDER}`" in body
        assert "Fix the thing" in body


class TestWriteFile:
    @pytest.fixture
    def writers(self):
        with (
            patch(f"{_MOD}.write_canvas", new_callable=AsyncMock, return_value=True) as canvas,
            patch(f"{_MOD}.write_activity", new_callable=AsyncMock, return_value=True) as activity,
            patch(f"{_MOD}.tracked_todo_service.system_log", new_callable=AsyncMock) as syslog,
        ):
            yield canvas, activity, syslog

    async def test_canvas_write_goes_to_mongo_and_audits(self, writers):
        canvas, activity, syslog = writers
        doc = _doc()

        result = await write_file(TaskFile(doc, GaiaTaskFile.CANVAS), USER_ID, "# new")

        assert result is None
        canvas.assert_awaited_once_with(
            TODO_ID, USER_ID, "# new", expected_updated_at=doc.updated_at
        )
        activity.assert_not_awaited()
        assert syslog.await_args.kwargs["event_type"] == "CANVAS_UPDATED"
        assert "canvas.md" in syslog.await_args.kwargs["details"]

    async def test_activity_write_goes_to_mongo(self, writers):
        canvas, activity, syslog = writers
        doc = _doc()

        assert await write_file(TaskFile(doc, GaiaTaskFile.ACTIVITY), USER_ID, "- x") is None
        activity.assert_awaited_once_with(
            TODO_ID, USER_ID, "- x", expected_updated_at=doc.updated_at
        )
        canvas.assert_not_awaited()
        assert "activity.md" in syslog.await_args.kwargs["details"]

    @pytest.mark.parametrize("filename", [GaiaTaskFile.LOG, GaiaTaskFile.META])
    async def test_system_files_are_refused(self, writers, filename):
        canvas, activity, syslog = writers

        refusal = await write_file(TaskFile(_doc(), filename), USER_ID, "x")

        assert refusal is not None
        assert filename.value in refusal
        assert "canvas.md" in refusal and "activity.md" in refusal
        canvas.assert_not_awaited()
        activity.assert_not_awaited()
        syslog.assert_not_awaited()

    async def test_root_index_is_refused(self, writers):
        refusal = await write_file(RootFile("index.md"), USER_ID, "x")

        assert refusal is not None and "generated" in refusal

    async def test_vanished_todo_is_an_error(self, writers, mock_repo):
        canvas, _, syslog = writers
        canvas.return_value = False
        mock_repo.get.return_value = None

        refusal = await write_file(TaskFile(_doc(), GaiaTaskFile.CANVAS), USER_ID, "x")

        assert refusal is not None and "no longer exists" in refusal
        syslog.assert_not_awaited()

    async def test_concurrent_write_raises_for_retry(self, writers, mock_repo):
        canvas, _, syslog = writers
        canvas.return_value = False
        mock_repo.get.return_value = _doc()

        with pytest.raises(NoteConflictError):
            await write_file(TaskFile(_doc(), GaiaTaskFile.CANVAS), USER_ID, "x")

        syslog.assert_not_awaited()

    async def test_audit_failure_still_succeeds(self, writers):
        canvas, _, syslog = writers
        syslog.side_effect = RuntimeError("audit down")

        with patch(f"{_MOD}.log") as mock_log:
            result = await write_file(TaskFile(_doc(), GaiaTaskFile.CANVAS), USER_ID, "# new")

        assert result is None
        canvas.assert_awaited_once()
        mock_log.warning.assert_called_once()
