"""read/write/edit on ``/workspace/gaia-tasks/**`` route to the todo document.

The router's own logic (folder resolution, writable set) runs for real here;
the seams are the todos repository and the canvas storage writers. None of
these paths may touch the sandbox — that is what makes them work in native
dev, where the disk projection does not exist.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

from bson import ObjectId
import pytest

from app.agents.tools.coding import edit_tool, read_tool, write_tool
from app.constants.todos import GAIA_TRACKED_LABEL
from app.models.todo_models import TodoDocument

CONFIG = {"metadata": {"user_id": "user-1", "conversation_id": "conv-1"}}
TODO_ID = "66f838cc8829054e5f10e407"
FOLDER = f"fix-the-thing-{TODO_ID[-8:]}"
CANVAS = "# Fix the thing\n\n## Current State\nWaiting on Rahul.\n"
_FILES = "app.services.gaia_task_files"


def _doc(**overrides: object) -> TodoDocument:
    data: dict[str, object] = {
        "id": TODO_ID,
        "user_id": "user-1",
        "title": "Fix the thing",
        "labels": [GAIA_TRACKED_LABEL],
        "canvas_content": CANVAS,
        "activity_content": "- 2026-09-01T09:00:00+00:00 started",
        "created_at": datetime(2026, 9, 1, tzinfo=UTC),
        "updated_at": datetime(2026, 9, 2, tzinfo=UTC),
    }
    data.update(overrides)
    return TodoDocument(**data)


@pytest.fixture
def repo():
    with patch(f"{_FILES}.todo_repository") as m:
        m.get = AsyncMock(return_value=None)
        m.find_tracked_by_short_id = AsyncMock(return_value=[_doc()])
        m.is_valid_id = ObjectId.is_valid
        yield m


@pytest.fixture
def writers():
    with (
        patch(f"{_FILES}.write_canvas", new_callable=AsyncMock, return_value=True) as canvas,
        patch(f"{_FILES}.write_activity", new_callable=AsyncMock, return_value=True) as activity,
        patch(f"{_FILES}.tracked_todo_service.system_log", new_callable=AsyncMock),
    ):
        yield canvas, activity


@pytest.fixture
def no_sandbox():
    with (
        patch("app.agents.tools.coding.read_tool.acquire_sandbox") as r,
        patch("app.agents.tools.coding.write_tool.acquire_sandbox") as w,
        patch("app.agents.tools.coding.edit_tool.acquire_sandbox") as e,
        patch("app.agents.tools.coding.read_tool.read_user_file") as host_read,
    ):
        yield r, w, e, host_read


@pytest.mark.unit
class TestRead:
    async def test_canvas_is_served_from_the_todo_document(self, repo, no_sandbox):
        r, _, _, host_read = no_sandbox

        out = await read_tool.read.ainvoke(
            {"path": f"/workspace/gaia-tasks/{FOLDER}/canvas.md"}, config=CONFIG
        )

        assert "Waiting on Rahul." in out
        assert out.lstrip().startswith("1\t")  # numbered like every other read
        r.assert_not_called()
        host_read.assert_not_called()

    async def test_activity_is_served_from_the_todo_document(self, repo, no_sandbox):
        out = await read_tool.read.ainvoke(
            {"path": f"/workspace/gaia-tasks/{FOLDER}/activity.md"}, config=CONFIG
        )

        assert "started" in out

    async def test_unknown_folder_is_a_clear_error(self, repo, no_sandbox):
        repo.find_tracked_by_short_id.return_value = []

        out = await read_tool.read.ainvoke(
            {"path": "/workspace/gaia-tasks/nope-deadbeef/canvas.md"}, config=CONFIG
        )

        assert out.startswith("Error:") and "no tracked todo" in out

    async def test_other_paths_are_untouched(self, repo, no_sandbox):
        """A non gaia-tasks path still goes to the host mount / sandbox."""
        _, _, _, host_read = no_sandbox
        host_read.return_value = (["hello"], 1)

        out = await read_tool.read.ainvoke(
            {"path": "/workspace/sessions/conv-1/scratch/x.txt"}, config=CONFIG
        )

        assert "hello" in out
        repo.find_tracked_by_short_id.assert_not_awaited()


@pytest.mark.unit
class TestWrite:
    async def test_canvas_write_lands_in_mongo_not_the_sandbox(self, repo, writers, no_sandbox):
        canvas, activity = writers
        _, w, _, _ = no_sandbox

        out = await write_tool.write.ainvoke(
            {"path": f"/workspace/gaia-tasks/{FOLDER}/canvas.md", "content": "# new"},
            config=CONFIG,
        )

        assert out.startswith("Wrote")
        canvas.assert_awaited_once_with(
            TODO_ID, "user-1", "# new", expected_updated_at=_doc().updated_at
        )
        activity.assert_not_awaited()
        w.assert_not_called()

    async def test_activity_write_lands_in_mongo(self, repo, writers, no_sandbox):
        canvas, activity = writers

        await write_tool.write.ainvoke(
            {"path": f"/workspace/gaia-tasks/{FOLDER}/activity.md", "content": "- x"},
            config=CONFIG,
        )

        activity.assert_awaited_once_with(
            TODO_ID, "user-1", "- x", expected_updated_at=_doc().updated_at
        )

    async def test_log_write_is_refused(self, repo, writers, no_sandbox):
        canvas, activity = writers

        out = await write_tool.write.ainvoke(
            {"path": f"/workspace/gaia-tasks/{FOLDER}/log.md", "content": "x"}, config=CONFIG
        )

        assert out.startswith("Error:") and "system-written" in out
        canvas.assert_not_awaited()
        activity.assert_not_awaited()

    async def test_index_write_is_refused(self, repo, writers, no_sandbox):
        out = await write_tool.write.ainvoke(
            {"path": "/workspace/gaia-tasks/index.md", "content": "x"}, config=CONFIG
        )

        assert out.startswith("Error:") and "generated" in out

    async def test_unresolvable_folder_is_a_clear_error(self, repo, writers, no_sandbox):
        repo.find_tracked_by_short_id.return_value = []

        out = await write_tool.write.ainvoke(
            {"path": "/workspace/gaia-tasks/nope-deadbeef/canvas.md", "content": "x"},
            config=CONFIG,
        )

        assert out.startswith("Error:") and "no tracked todo" in out

    async def test_concurrent_write_reports_cleanly_without_retry(self, repo, writers, no_sandbox):
        canvas, _ = writers
        canvas.return_value = False
        repo.get.return_value = _doc()
        _, w, _, _ = no_sandbox

        out = await write_tool.write.ainvoke(
            {"path": f"/workspace/gaia-tasks/{FOLDER}/canvas.md", "content": "# new"},
            config=CONFIG,
        )

        assert "concurrently" in out
        canvas.assert_awaited_once()
        w.assert_not_called()


@pytest.mark.unit
class TestEdit:
    async def test_edit_replaces_inside_the_mongo_canvas(self, repo, writers, no_sandbox):
        canvas, _ = writers
        _, _, e, _ = no_sandbox

        out = await edit_tool.edit.ainvoke(
            {
                "path": f"/workspace/gaia-tasks/{FOLDER}/canvas.md",
                "old_string": "Waiting on Rahul.",
                "new_string": "Rahul replied; drafting the contract.",
            },
            config=CONFIG,
        )

        assert out.startswith("Edited")
        written = canvas.await_args.args[2]
        assert "Rahul replied; drafting the contract." in written
        assert "Waiting on Rahul." not in written
        assert written.startswith("# Fix the thing")  # the rest is intact
        e.assert_not_called()

    async def test_edit_missing_old_string_is_an_error_and_writes_nothing(
        self, repo, writers, no_sandbox
    ):
        canvas, _ = writers

        out = await edit_tool.edit.ainvoke(
            {
                "path": f"/workspace/gaia-tasks/{FOLDER}/canvas.md",
                "old_string": "not there",
                "new_string": "x",
            },
            config=CONFIG,
        )

        assert out == "Error: old_string not found in file"
        canvas.assert_not_awaited()

    async def test_edit_ambiguous_old_string_needs_replace_all(self, repo, writers, no_sandbox):
        canvas, _ = writers
        repo.find_tracked_by_short_id.return_value = [_doc(canvas_content="a b a")]

        out = await edit_tool.edit.ainvoke(
            {
                "path": f"/workspace/gaia-tasks/{FOLDER}/canvas.md",
                "old_string": "a",
                "new_string": "c",
            },
            config=CONFIG,
        )

        assert "appears 2 times" in out
        canvas.assert_not_awaited()

    async def test_edit_replace_all(self, repo, writers, no_sandbox):
        canvas, _ = writers
        repo.find_tracked_by_short_id.return_value = [_doc(canvas_content="a b a")]

        out = await edit_tool.edit.ainvoke(
            {
                "path": f"/workspace/gaia-tasks/{FOLDER}/canvas.md",
                "old_string": "a",
                "new_string": "c",
                "replace_all": True,
            },
            config=CONFIG,
        )

        assert "2 occurrences" in out
        assert canvas.await_args.args[2] == "c b c"

    async def test_edit_of_a_system_file_is_refused(self, repo, writers, no_sandbox):
        out = await edit_tool.edit.ainvoke(
            {
                "path": f"/workspace/gaia-tasks/{FOLDER}/meta.json",
                "old_string": "x",
                "new_string": "y",
            },
            config=CONFIG,
        )

        assert out.startswith("Error:") and "system-written" in out

    async def test_edit_retries_a_lost_revision_race(self, repo, writers, no_sandbox):
        canvas, _ = writers
        canvas.side_effect = [False, True]
        repo.get.return_value = _doc()
        _, _, e, _ = no_sandbox

        out = await edit_tool.edit.ainvoke(
            {
                "path": f"/workspace/gaia-tasks/{FOLDER}/canvas.md",
                "old_string": "Waiting on Rahul.",
                "new_string": "Rahul replied.",
            },
            config=CONFIG,
        )

        assert out.startswith("Edited")
        assert canvas.await_count == 2
        e.assert_not_called()

    async def test_edit_gives_up_after_repeated_conflicts(self, repo, writers, no_sandbox):
        canvas, _ = writers
        canvas.return_value = False
        repo.get.return_value = _doc()
        _, _, e, _ = no_sandbox

        out = await edit_tool.edit.ainvoke(
            {
                "path": f"/workspace/gaia-tasks/{FOLDER}/canvas.md",
                "old_string": "Waiting on Rahul.",
                "new_string": "Rahul replied.",
            },
            config=CONFIG,
        )

        assert "concurrently" in out
        assert canvas.await_count == 3
        e.assert_not_called()


@pytest.mark.unit
class TestUnexpectedFailuresStayInsideTheTool:
    async def test_read_resolve_failure_returns_stable_error(self, repo, no_sandbox):
        repo.find_tracked_by_short_id.side_effect = RuntimeError("mongo down")
        _, _, _, host_read = no_sandbox

        out = await read_tool.read.ainvoke(
            {"path": f"/workspace/gaia-tasks/{FOLDER}/canvas.md"}, config=CONFIG
        )

        assert out == "Error reading todo notes: mongo down"
        host_read.assert_not_called()

    async def test_write_resolve_failure_returns_stable_error(self, repo, writers, no_sandbox):
        repo.find_tracked_by_short_id.side_effect = RuntimeError("mongo down")
        _, w, _, _ = no_sandbox

        out = await write_tool.write.ainvoke(
            {"path": f"/workspace/gaia-tasks/{FOLDER}/canvas.md", "content": "x"},
            config=CONFIG,
        )

        assert out == "Error writing todo notes: mongo down"
        w.assert_not_called()

    async def test_edit_resolve_failure_returns_stable_error(self, repo, writers, no_sandbox):
        repo.find_tracked_by_short_id.side_effect = RuntimeError("mongo down")
        _, _, e, _ = no_sandbox

        out = await edit_tool.edit.ainvoke(
            {
                "path": f"/workspace/gaia-tasks/{FOLDER}/canvas.md",
                "old_string": "a",
                "new_string": "b",
            },
            config=CONFIG,
        )

        assert out == "Error editing todo notes: mongo down"
        e.assert_not_called()

    async def test_write_mongo_failure_returns_stable_error(self, repo, writers, no_sandbox):
        canvas, _ = writers
        canvas.side_effect = RuntimeError("mongo down")
        _, w, _, _ = no_sandbox

        out = await write_tool.write.ainvoke(
            {"path": f"/workspace/gaia-tasks/{FOLDER}/canvas.md", "content": "x"},
            config=CONFIG,
        )

        assert out == "Error writing todo notes: mongo down"
        w.assert_not_called()

    async def test_edit_mongo_failure_returns_stable_error(self, repo, writers, no_sandbox):
        canvas, _ = writers
        canvas.side_effect = RuntimeError("mongo down")
        _, _, e, _ = no_sandbox

        out = await edit_tool.edit.ainvoke(
            {
                "path": f"/workspace/gaia-tasks/{FOLDER}/canvas.md",
                "old_string": "Waiting on Rahul.",
                "new_string": "done",
            },
            config=CONFIG,
        )

        assert out == "Error editing todo notes: mongo down"
        e.assert_not_called()


@pytest.mark.unit
class TestProjectionGuard:
    async def test_write_to_unknown_task_file_is_a_routing_error(self, repo, writers, no_sandbox):
        _, w, _, _ = no_sandbox

        out = await write_tool.write.ainvoke(
            {"path": "/workspace/gaia-tasks/random.txt", "content": "x"}, config=CONFIG
        )

        assert "not an editable notes file" in out and "canvas.md" in out
        w.assert_not_called()

    async def test_write_to_nested_task_path_is_a_routing_error(self, repo, writers, no_sandbox):
        _, w, _, _ = no_sandbox

        out = await write_tool.write.ainvoke(
            {"path": f"/workspace/gaia-tasks/{FOLDER}/sub/canvas.md", "content": "x"},
            config=CONFIG,
        )

        assert "not an editable notes file" in out
        w.assert_not_called()

    async def test_edit_to_unknown_task_file_is_a_routing_error(self, repo, writers, no_sandbox):
        _, _, e, _ = no_sandbox

        out = await edit_tool.edit.ainvoke(
            {
                "path": "/workspace/gaia-tasks/random.txt",
                "old_string": "a",
                "new_string": "b",
            },
            config=CONFIG,
        )

        assert "not an editable notes file" in out and "canvas.md" in out
        e.assert_not_called()

    async def test_edit_to_nested_task_path_is_a_routing_error(self, repo, writers, no_sandbox):
        _, _, e, _ = no_sandbox

        out = await edit_tool.edit.ainvoke(
            {
                "path": f"/workspace/gaia-tasks/{FOLDER}/sub/canvas.md",
                "old_string": "a",
                "new_string": "b",
            },
            config=CONFIG,
        )

        assert "not an editable notes file" in out
        e.assert_not_called()
