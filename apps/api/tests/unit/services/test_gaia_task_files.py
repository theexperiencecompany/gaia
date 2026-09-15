"""Unit tests for gaia_task_files, the /workspace/gaia-tasks/ path router.

The coding tools use it so canvas.md / activity.md live on the todo doc, not on disk.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

from bson import ObjectId
import pytest

from app.constants.todos import GAIA_TRACKED_LABEL
from app.models.todo_models import Priority, TodoDocument
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
from app.services.gaia_tasks_fs import project_gaia_task

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
    """Patch the repository singleton at both import seams (this module and the projection glue)."""
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
        # The full id is looked up for THIS user — a dropped/swapped folder or
        # user_id silently reads another user's todo.
        mock_repo.get.assert_awaited_once_with(TODO_ID, user_id=USER_ID)

    async def test_full_id_of_a_non_tracked_todo_is_an_error(self, mock_repo):
        mock_repo.get.return_value = _doc(labels=["work"])

        with pytest.raises(GaiaTaskPathError, match="not a tracked todo"):
            await resolve(f"gaia-tasks/{TODO_ID}/canvas.md", USER_ID)

    async def test_a_full_id_that_exists_for_no_one_names_the_id(self, mock_repo):
        # A well-formed ObjectId the repo cannot find (wrong user or deleted) is
        # its own error, distinct from "not a tracked todo" and from the
        # short-id no-match — the message must carry the id that was tried.
        with pytest.raises(GaiaTaskPathError, match=f"no tracked todo with id {TODO_ID}"):
            await resolve(f"gaia-tasks/{TODO_ID}/canvas.md", USER_ID)

    async def test_unknown_folder_is_an_error(self, mock_repo):
        with pytest.raises(GaiaTaskPathError) as exc:
            await resolve(f"gaia-tasks/{FOLDER}/canvas.md", USER_ID)

        message = str(exc.value)
        assert "no tracked todo" in message
        # The recovery hint must survive verbatim — an uppercased or mangled
        # copy of it still "contains" nothing useful to the model.
        assert "/ or read its index.md for the current folder names" in message

    async def test_ambiguous_short_id_is_an_error(self, mock_repo):
        second_id = "a" * 16 + SHORT
        mock_repo.find_tracked_by_short_id.return_value = [_doc(), _doc(id=second_id)]

        with pytest.raises(GaiaTaskPathError) as exc:
            await resolve(f"gaia-tasks/{FOLDER}/canvas.md", USER_ID)

        message = str(exc.value)
        assert "matches 2" in message
        # Every colliding id is listed so the caller can pick one; the recovery
        # hint is verbatim.
        assert f"({TODO_ID}, {second_id})" in message
        assert "; use the full todo id as the folder name instead" in message

    async def test_unknown_filename_in_task_folder_falls_through(self, mock_repo):
        mock_repo.find_tracked_by_short_id.return_value = [_doc()]

        assert await resolve(f"gaia-tasks/{FOLDER}/notes.md", USER_ID) is None

    async def test_gaia_tasks_under_a_session_dir_names_the_absolute_path(self, mock_repo):
        """A relative gaia-tasks/... path under a session dir still names the absolute path in the error."""
        with pytest.raises(GaiaTaskPathError, match="/workspace/gaia-tasks/"):
            await resolve(f"sessions/conv-1/scratch/gaia-tasks/{FOLDER}/canvas.md", USER_ID)

    async def test_gaia_tasks_as_the_second_segment_rebuilds_the_full_tail(self, mock_repo):
        # `gaia-tasks` can appear at any depth, including index 1 — the detector
        # must scan the whole remainder, not skip the first element, and the
        # suggestion must join the real tail back onto /workspace/.
        with pytest.raises(GaiaTaskPathError) as exc:
            await resolve(f"sessions/gaia-tasks/{FOLDER}/canvas.md", USER_ID)

        message = str(exc.value)
        assert "use /workspace/gaia-tasks/" in message
        assert f"gaia-tasks/{FOLDER}/canvas.md" in message

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
        doc = _doc(canvas_content=None, activity_content=None, log_content=None)

        assert await read_file(TaskFile(doc, GaiaTaskFile.CANVAS), USER_ID) == ""
        assert await read_file(TaskFile(doc, GaiaTaskFile.ACTIVITY), USER_ID) == ""
        assert await read_file(TaskFile(doc, GaiaTaskFile.LOG), USER_ID) == ""

    async def test_meta_json_matches_the_disk_projection(self, mock_repo):
        body = await read_file(TaskFile(_doc(), GaiaTaskFile.META), USER_ID)

        assert '"title": "Fix the thing"' in body
        assert '"completed": false' in body

    async def test_index_lists_the_active_set(self, mock_repo):
        projections = [project_gaia_task(_doc())]
        with patch(
            f"{_MOD}.fetch_active_projections",
            new_callable=AsyncMock,
            return_value=projections,
        ) as fetch:
            body = await read_file(RootFile("index.md"), USER_ID)

        # The index is the user's own catalog — the lookup must be scoped to
        # the caller, not an unfiltered/None query.
        fetch.assert_awaited_once_with(USER_ID)
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
        # The audit line names this todo and this user, and records the file and
        # character count verbatim.
        syslog.assert_awaited_once_with(
            todo_id=TODO_ID,
            user_id=USER_ID,
            event_type="CANVAS_UPDATED",
            details="Agent wrote canvas.md (5 chars)",
        )

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
        assert "Only canvas.md and activity.md are editable under gaia-tasks/." in refusal
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
        # The re-read must look up THIS todo for THIS user to tell deletion
        # apart from a lost revision race.
        mock_repo.get.assert_awaited_once_with(TODO_ID, user_id=USER_ID)
        syslog.assert_not_awaited()

    async def test_concurrent_write_raises_for_retry(self, writers, mock_repo):
        canvas, _, syslog = writers
        canvas.return_value = False
        mock_repo.get.return_value = _doc()

        with pytest.raises(NoteConflictError) as exc:
            await write_file(TaskFile(_doc(), GaiaTaskFile.CANVAS), USER_ID, "x")

        # The conflict carries the todo id so a re-appliable caller knows what
        # to re-resolve.
        assert exc.value.args == (TODO_ID,)
        syslog.assert_not_awaited()

    async def test_audit_failure_still_succeeds(self, writers):
        canvas, _, syslog = writers
        syslog.side_effect = RuntimeError("audit down")

        with patch(f"{_MOD}.log") as mock_log:
            result = await write_file(TaskFile(_doc(), GaiaTaskFile.CANVAS), USER_ID, "# new")

        assert result is None
        canvas.assert_awaited_once()
        # A failed audit is logged with the real event and all context — a
        # dropped keyword or a mangled message loses the only breadcrumb.
        mock_log.warning.assert_called_once_with(
            "gaia task audit log failed",
            error_type="RuntimeError",
            todo_id=TODO_ID,
            user_id=USER_ID,
            exc_info=True,
        )


class TestProjectGaiaTask:
    """project_gaia_task shapes the on-disk projection.

    Every field the agent reads must map across exactly.
    """

    def test_maps_notes_and_meta(self):
        doc = _doc(
            id="t1",
            title="Ship it",
            canvas_content="# c",
            activity_content="- a",
            log_content="## l",
            labels=[GAIA_TRACKED_LABEL],
            priority=Priority.HIGH,
            completed=True,
        )

        projection = project_gaia_task(doc)

        assert projection["id"] == "t1"
        assert projection["canvas"] == "# c"
        assert projection["activity"] == "- a"
        assert projection["log"] == "## l"
        assert projection["meta"]["title"] == "Ship it"
        assert projection["meta"]["completed"] is True
        assert projection["meta"]["priority"] == "high"
        assert projection["meta"]["labels"] == [GAIA_TRACKED_LABEL]

    def test_unset_bodies_read_as_empty_strings(self):
        projection = project_gaia_task(_doc(canvas_content=None, activity_content=None))

        assert projection["canvas"] == ""
        assert projection["activity"] == ""
