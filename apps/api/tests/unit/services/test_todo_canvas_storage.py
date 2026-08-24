"""Unit tests for todo_canvas_storage (Mongo-backed canvas/log read/write/append).

The storage primitives funnel every read and write through the todos
repository — atomicity here means: each append reads the current value, then
writes back the full concatenated content in one update (no partial writes),
and a write only succeeds when the repository confirms the update matched.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.todo_models import TodoDocument
from app.services.todo_canvas_storage import (
    append_canvas,
    append_log,
    build_vfs_label,
    read_canvas,
    read_log,
    write_canvas,
    write_log,
)

_MOD = "app.services.todo_canvas_storage"
USER_ID = "507f1f77bcf86cd799439011"
TODO_ID = "todo-1"


def _todo_doc(**overrides: object) -> TodoDocument:
    data: dict[str, object] = {
        "user_id": USER_ID,
        "title": "Ship the thing",
        "canvas_content": "canvas-v1",
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
        yield m


@pytest.fixture
def mock_sync():
    with patch(f"{_MOD}.schedule_gaia_tasks_sync", new_callable=MagicMock) as m:
        yield m


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
        mock_repo.update.return_value = _todo_doc()

        ok = await write_canvas(TODO_ID, USER_ID, "new content")

        assert ok is True
        update = mock_repo.update.await_args.kwargs["update"]
        assert update.canvas_content == "new content"
        mock_sync.assert_called_once_with(USER_ID)

    async def test_false_when_update_matches_nothing(self, mock_repo, mock_sync):
        mock_repo.update.return_value = None

        assert await write_canvas(TODO_ID, USER_ID, "new content") is False
        mock_sync.assert_not_called()


class TestAppendCanvas:
    async def test_false_for_missing_todo(self, mock_repo):
        assert await append_canvas(TODO_ID, USER_ID, "entry") is False

    async def test_appends_with_newline_separator(self, mock_repo, mock_sync):
        mock_repo.get.return_value = _todo_doc(canvas_content="existing")
        mock_repo.update.return_value = _todo_doc()

        ok = await append_canvas(TODO_ID, USER_ID, "entry")

        assert ok is True
        assert mock_repo.update.await_args.kwargs["update"].canvas_content == "existing\nentry"

    async def test_preserves_leading_newline_in_content(self, mock_repo, mock_sync):
        mock_repo.get.return_value = _todo_doc(canvas_content="existing")
        mock_repo.update.return_value = _todo_doc()

        await append_canvas(TODO_ID, USER_ID, "\nentry")

        assert mock_repo.update.await_args.kwargs["update"].canvas_content == "existing\nentry"

    async def test_round_trip_appends_accumulate(self, mock_repo, mock_sync):
        """Two appends must produce one content string — the read-then-write
        pattern concatenates instead of overwriting."""
        canvas = "v1"
        mock_repo.update.return_value = _todo_doc()

        async def fake_get(todo_id: str, **kwargs: object) -> TodoDocument | None:
            return _todo_doc(canvas_content=canvas)

        async def fake_update(todo_id: str, **kwargs: object) -> TodoDocument:
            nonlocal canvas
            canvas = kwargs["update"].canvas_content
            return _todo_doc(canvas_content=canvas)

        mock_repo.get = fake_get
        mock_repo.update = fake_update

        await append_canvas(TODO_ID, USER_ID, "b")
        await append_canvas(TODO_ID, USER_ID, "c")

        assert canvas == "v1\nb\nc"


class TestReadLog:
    async def test_none_for_missing_todo(self, mock_repo):
        assert await read_log(TODO_ID, USER_ID) is None

    async def test_returns_content(self, mock_repo):
        mock_repo.get.return_value = _todo_doc(log_content="audit")

        assert await read_log(TODO_ID, USER_ID) == "audit"


class TestWriteLog:
    async def test_writes_and_triggers_sync(self, mock_repo, mock_sync):
        mock_repo.update.return_value = _todo_doc()

        assert await write_log(TODO_ID, USER_ID, "audit v2") is True
        assert mock_repo.update.await_args.kwargs["update"].log_content == "audit v2"
        mock_sync.assert_called_once_with(USER_ID)

    async def test_false_when_update_matches_nothing(self, mock_repo, mock_sync):
        mock_repo.update.return_value = None

        assert await write_log(TODO_ID, USER_ID, "audit v2") is False
        mock_sync.assert_not_called()


class TestAppendLog:
    async def test_false_for_missing_todo(self, mock_repo):
        assert await append_log(TODO_ID, USER_ID, "entry") is False

    async def test_appends_with_newline_separator(self, mock_repo, mock_sync):
        mock_repo.get.return_value = _todo_doc(log_content="audit v1")
        mock_repo.update.return_value = _todo_doc()

        assert await append_log(TODO_ID, USER_ID, "audit v2") is True
        assert mock_repo.update.await_args.kwargs["update"].log_content == "audit v1\naudit v2"
