"""Unit tests for todo_canvas_storage (Mongo-backed canvas/log read/write/append).

The storage primitives funnel every read and write through the todos
repository — a write only succeeds when the repository confirms the update
matched. Branch-only primitives (atomic append, compare-and-set, the
activity/log pair and the empty-body embedding delete) live in
``test_canvas_storage_atomic.py``: the regression-proof lane overlays this
branch's tests onto the base revision, so this module must import only what the
base also exports.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.todo_models import TodoDocument
from app.services.todo_canvas_storage import (
    _schedule_reindex,
    append_log,
    build_vfs_label,
    embedding_text,
    read_canvas,
    write_canvas,
)

_MOD = "app.services.todo_canvas_storage"
USER_ID = "507f1f77bcf86cd799439011"
TODO_ID = "todo-1"


def _todo_doc(**overrides: object) -> TodoDocument:
    data: dict[str, object] = {
        "id": TODO_ID,
        "user_id": USER_ID,
        "title": "Ship the thing",
        "canvas_content": "canvas-v1",
        "activity_content": "activity-v1",
        "log_content": "log-v1",
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }
    data.update(overrides)
    return TodoDocument(**data)


@pytest.fixture
def mock_repo():
    with patch(f"{_MOD}.todo_repository") as m:
        m.get = AsyncMock(return_value=None)
        m.update = AsyncMock(return_value=None)
        m.replace_note_fields = AsyncMock(return_value=None)
        m.append_text_field = AsyncMock(return_value=None)
        yield m


@pytest.fixture
def mock_sync():
    with patch(f"{_MOD}.schedule_gaia_tasks_sync", new_callable=MagicMock) as m:
        yield m


class TestEmbeddingText:
    def test_joins_canvas_and_activity_with_blank_line(self):
        doc = _todo_doc(canvas_content="c", activity_content="a")

        assert embedding_text(doc) == "c\n\na"

    def test_skips_empty_parts(self):
        assert embedding_text(_todo_doc(canvas_content="c", activity_content=None)) == "c"
        assert embedding_text(_todo_doc(canvas_content=None, activity_content="a")) == "a"

    def test_empty_when_both_empty(self):
        assert embedding_text(_todo_doc(canvas_content=None, activity_content=None)) == ""


class TestScheduleReindex:
    def test_reindexes_with_the_exact_arguments(self):
        doc = _todo_doc(canvas_content="c", activity_content="a", labels=["x"])
        with patch(f"{_MOD}.update_canvas_embedding", new_callable=AsyncMock) as embed:
            with patch(f"{_MOD}.spawn_logged_task") as spawn:
                _schedule_reindex(doc)

        name, coro = spawn.call_args.args
        assert name == "canvas_reindex"
        coro.close()
        assert embed.call_args.kwargs == {
            "todo_id": TODO_ID,
            "canvas_content": "c\n\na",
            "user_id": USER_ID,
            "title": "Ship the thing",
            "labels": ["x"],
            "revision": doc.updated_at.isoformat(),
        }

    def test_empty_bodies_delete_the_embedding_instead(self):
        doc = _todo_doc(canvas_content=None, activity_content=None)
        with patch(f"{_MOD}.delete_canvas_embedding", new_callable=AsyncMock) as delete:
            with patch(f"{_MOD}.spawn_logged_task") as spawn:
                _schedule_reindex(doc)

        name, coro = spawn.call_args.args
        coro.close()
        assert name == "canvas_reindex_delete"
        delete.assert_called_once_with(TODO_ID)


class TestBuildVfsLabel:
    def test_label_format(self):
        assert build_vfs_label(TODO_ID) == f"/workspace/gaia-tasks/{TODO_ID}"

    def test_label_never_contains_user_id(self) -> None:
        assert USER_ID not in build_vfs_label(TODO_ID)

    def test_archive_label_format(self) -> None:
        assert build_vfs_label(TODO_ID, archived=True) == (
            f"/workspace/gaia-tasks/archive/{TODO_ID}"
        )


class TestReadCanvas:
    async def test_none_for_missing_todo(self, mock_repo):
        assert await read_canvas(TODO_ID, USER_ID) is None

    async def test_returns_content(self, mock_repo):
        mock_repo.get.return_value = _todo_doc(canvas_content="hello")

        assert await read_canvas(TODO_ID, USER_ID) == "hello"

    async def test_empty_string_when_unset(self, mock_repo):
        mock_repo.get.return_value = _todo_doc(canvas_content=None)

        assert await read_canvas(TODO_ID, USER_ID) == ""


class TestWriteCanvas:
    async def test_writes_and_triggers_sync(self, mock_repo, mock_sync):
        mock_repo.replace_note_fields.return_value = _todo_doc()

        ok = await write_canvas(TODO_ID, USER_ID, "new content")

        assert ok is True
        kwargs = mock_repo.replace_note_fields.await_args.kwargs
        assert kwargs["update"].canvas_content == "new content"
        assert kwargs["update"].title is None  # only the canvas body is replaced
        assert kwargs["expected_updated_at"] is None
        mock_sync.assert_called_once_with(USER_ID)

    async def test_false_when_update_matches_nothing(self, mock_repo, mock_sync):
        mock_repo.replace_note_fields.return_value = None

        assert await write_canvas(TODO_ID, USER_ID, "new content") is False
        mock_sync.assert_not_called()


class TestAppendLog:
    async def test_appends_with_newline_separator(self, mock_repo, mock_sync):
        mock_repo.append_text_field.return_value = _todo_doc()

        assert await append_log(TODO_ID, USER_ID, "audit v2") is True
        mock_repo.append_text_field.assert_awaited_once_with(
            TODO_ID, USER_ID, field="log_content", suffix="\naudit v2"
        )
        mock_sync.assert_called_once_with(USER_ID)
