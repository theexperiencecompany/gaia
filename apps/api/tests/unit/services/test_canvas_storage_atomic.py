"""Atomic canvas/activity writes — the branch-only storage primitives.

These tests pin behavior the base revision does not have (``append_text_field``
backing ``append_activity``/``append_log``, the ``expected_updated_at``
compare-and-set, ``write_canvas_and_activity``, the reindex revision, and the
empty-body embedding delete). They live in their own module rather than in
``test_todo_canvas_storage.py`` on purpose: the regression-proof lane overlays
this branch's test tree onto the base revision, so a file that imports
branch-only names at module level would collection-error there (an error is not
proof — the run never reaches an assertion). The branch-only callables are
imported inside the tests that use them, so this module imports cleanly on base
and each marked test then fails on the behavior, which is what the lane checks.
"""

from collections.abc import Coroutine
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.todo_models import TodoDocument
from app.services.todo_canvas_storage import (
    append_log,
    build_vfs_label,
    read_canvas,
    write_canvas,
)

_MOD = "app.services.todo_canvas_storage"
USER_ID = "507f1f77bcf86cd799439011"
TODO_ID = "todo-1"


def _todo_doc(**overrides: object) -> TodoDocument:
    data: dict[str, object] = {
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


@pytest.fixture
def captured_reindex():
    """Capture the fire-and-forget reindex: patched spawn collects coroutines so
    tests can await them deterministically; the embedding call itself is mocked.

    ``create=True`` on the spawn patch keeps this fixture usable against the
    base revision, which has no ``spawn_logged_task`` import — the regression
    lane runs the marked tests against base, and a fixture that errors there is
    not proof.
    """
    scheduled: list[tuple[str, Coroutine[Any, Any, Any]]] = []

    def fake_spawn(name: str, coro: Coroutine[Any, Any, Any]) -> None:
        scheduled.append((name, coro))

    with (
        patch(f"{_MOD}.spawn_logged_task", side_effect=fake_spawn, create=True),
        patch(f"{_MOD}.update_canvas_embedding", new_callable=AsyncMock) as embed,
    ):
        yield scheduled, embed
        for _, coro in scheduled:
            coro.close()


class TestSharedPrimitives:
    """The canvas read/write + log-append basics, kept where the atomic tests
    live too so this module is self-contained when run alone."""

    async def test_read_canvas_returns_content(self, mock_repo):
        mock_repo.get.return_value = _todo_doc(canvas_content="hello")

        assert await read_canvas(TODO_ID, USER_ID) == "hello"

    async def test_build_vfs_label(self):
        assert build_vfs_label(TODO_ID) == f"/workspace/gaia-tasks/{TODO_ID}"


class TestWriteCanvasCompareAndSet:
    @pytest.mark.regression
    async def test_passes_expected_updated_at(self, mock_repo, mock_sync) -> None:
        expected = datetime.now(UTC)
        mock_repo.replace_note_fields.return_value = _todo_doc()

        ok = await write_canvas(TODO_ID, USER_ID, "new", expected_updated_at=expected)

        assert ok is True
        kwargs = mock_repo.replace_note_fields.await_args.kwargs
        assert kwargs["update"].canvas_content == "new"
        assert kwargs["expected_updated_at"] == expected

    async def test_false_on_revision_mismatch(self, mock_repo, mock_sync) -> None:
        mock_repo.replace_note_fields.return_value = None

        ok = await write_canvas(TODO_ID, USER_ID, "new", expected_updated_at=datetime.now(UTC))

        assert ok is False
        mock_sync.assert_not_called()


class TestActivity:
    async def test_read_none_for_missing_todo(self, mock_repo):
        from app.services.todo_canvas_storage import read_activity

        assert await read_activity(TODO_ID, USER_ID) is None

    async def test_read_empty_string_when_unset(self, mock_repo):
        from app.services.todo_canvas_storage import read_activity

        mock_repo.get.return_value = _todo_doc(activity_content=None)

        assert await read_activity(TODO_ID, USER_ID) == ""

    async def test_write_and_triggers_sync(self, mock_repo, mock_sync, captured_reindex):
        from app.services.todo_canvas_storage import write_activity

        mock_repo.replace_note_fields.return_value = _todo_doc()

        ok = await write_activity(TODO_ID, USER_ID, "- 2026-09-02 did a thing")

        assert ok is True
        update = mock_repo.replace_note_fields.await_args.kwargs["update"]
        assert update.activity_content == "- 2026-09-02 did a thing"
        mock_sync.assert_called_once_with(USER_ID)

    async def test_write_false_when_update_matches_nothing(self, mock_repo, mock_sync):
        from app.services.todo_canvas_storage import write_activity

        mock_repo.replace_note_fields.return_value = None

        assert await write_activity(TODO_ID, USER_ID, "entry") is False
        mock_sync.assert_not_called()

    @pytest.mark.regression
    async def test_append_false_for_missing_todo(self, mock_repo):
        from app.services.todo_canvas_storage import append_activity

        mock_repo.append_text_field.return_value = None

        assert await append_activity(TODO_ID, USER_ID, "entry") is False

    @pytest.mark.regression
    async def test_append_concatenates_atomically(self, mock_repo, mock_sync):
        """One server-side append: the suffix goes to the repo, sync follows."""
        from app.services.todo_canvas_storage import append_activity

        mock_repo.append_text_field.return_value = _todo_doc(activity_content="- old\n- new")

        ok = await append_activity(TODO_ID, USER_ID, "- new")

        assert ok is True
        kwargs = mock_repo.append_text_field.await_args.kwargs
        assert kwargs["field"] == "activity_content"
        assert kwargs["suffix"] == "\n- new"
        mock_sync.assert_called_once_with(USER_ID)

    async def test_append_keeps_leading_newline_entry_as_is(self, mock_repo, mock_sync):
        from app.services.todo_canvas_storage import append_activity

        mock_repo.append_text_field.return_value = _todo_doc()

        await append_activity(TODO_ID, USER_ID, "\n- new")

        assert mock_repo.append_text_field.await_args.kwargs["suffix"] == "\n- new"


class TestWriteCanvasAndActivity:
    async def test_sets_both_fields_in_one_update(self, mock_repo, mock_sync, captured_reindex):
        from app.services.todo_canvas_storage import write_canvas_and_activity

        scheduled, _ = captured_reindex
        mock_repo.replace_note_fields.return_value = _todo_doc(
            canvas_content="c", activity_content="a"
        )

        ok = await write_canvas_and_activity(TODO_ID, USER_ID, canvas="c", activity="a")

        assert ok is True
        mock_repo.replace_note_fields.assert_awaited_once()
        update = mock_repo.replace_note_fields.await_args.kwargs["update"]
        assert (update.canvas_content, update.activity_content) == ("c", "a")
        mock_sync.assert_called_once_with(USER_ID)
        assert [name for name, _ in scheduled] == ["canvas_reindex"]

    async def test_false_when_update_matches_nothing(self, mock_repo, mock_sync):
        from app.services.todo_canvas_storage import write_canvas_and_activity

        mock_repo.replace_note_fields.return_value = None

        assert await write_canvas_and_activity(TODO_ID, USER_ID, canvas="c", activity="a") is False
        mock_sync.assert_not_called()


class TestReindexRevision:
    async def test_write_canvas_reindexes_with_combined_text_and_revision(
        self, mock_repo, mock_sync, captured_reindex
    ):
        scheduled, embed = captured_reindex
        updated = _todo_doc(canvas_content="canvas body", activity_content="activity body")
        mock_repo.replace_note_fields.return_value = updated

        await write_canvas(TODO_ID, USER_ID, "canvas body")

        assert [name for name, _ in scheduled] == ["canvas_reindex"]
        await scheduled.pop()[1]
        embed.assert_awaited_once()
        assert embed.await_args.kwargs["canvas_content"] == "canvas body\n\nactivity body"
        assert embed.await_args.kwargs["revision"] == updated.updated_at.isoformat()

    async def test_write_activity_reindexes(self, mock_repo, mock_sync, captured_reindex):
        from app.services.todo_canvas_storage import write_activity

        scheduled, embed = captured_reindex
        mock_repo.replace_note_fields.return_value = _todo_doc(
            canvas_content="canvas body", activity_content="- entry"
        )

        await write_activity(TODO_ID, USER_ID, "- entry")

        assert [name for name, _ in scheduled] == ["canvas_reindex"]
        await scheduled.pop()[1]
        assert embed.await_args.kwargs["canvas_content"] == "canvas body\n\n- entry"

    async def test_no_reindex_when_update_matches_nothing(
        self, mock_repo, mock_sync, captured_reindex
    ):
        scheduled, embed = captured_reindex
        mock_repo.replace_note_fields.return_value = None

        await write_canvas(TODO_ID, USER_ID, "content")

        assert scheduled == []
        embed.assert_not_awaited()


class TestClearDeletesEmbedding:
    @pytest.mark.regression
    async def test_clearing_canvas_and_activity_deletes_embedding(
        self, mock_repo, mock_sync
    ) -> None:
        """Clearing both bodies must remove the stale index entry, not orphan it."""
        from app.services.todo_canvas_storage import write_canvas_and_activity

        scheduled: list[tuple[str, Coroutine[Any, Any, Any]]] = []

        def fake_spawn(name: str, coro: Coroutine[Any, Any, Any]) -> None:
            scheduled.append((name, coro))

        with (
            patch(f"{_MOD}.spawn_logged_task", side_effect=fake_spawn),
            patch(f"{_MOD}.update_canvas_embedding", new_callable=AsyncMock) as embed,
            patch(f"{_MOD}.delete_canvas_embedding", new_callable=AsyncMock, create=True) as delete,
        ):
            try:
                mock_repo.replace_note_fields.return_value = _todo_doc(
                    id=TODO_ID, canvas_content="", activity_content=""
                )
                ok = await write_canvas_and_activity(TODO_ID, USER_ID, canvas="", activity="")

                assert ok is True
                assert [name for name, _ in scheduled] == ["canvas_reindex_delete"]
                await scheduled[0][1]
                delete.assert_awaited_once_with(TODO_ID)
                embed.assert_not_awaited()
            finally:
                for _, coro in scheduled:
                    coro.close()


class TestAppendLog:
    @pytest.mark.regression
    async def test_routes_the_suffix_through_the_atomic_append(self, mock_repo, mock_sync) -> None:
        """The append is one server-side concat, not a read-then-overwrite.

        A missing-todo early return is identical on both revisions and would
        pass on base; asserting the ``append_text_field`` call is what
        distinguishes the atomic path."""
        mock_repo.append_text_field.return_value = _todo_doc()

        assert await append_log(TODO_ID, USER_ID, "audit v2") is True
        kwargs = mock_repo.append_text_field.await_args.kwargs
        assert kwargs["field"] == "log_content"
        assert kwargs["suffix"] == "\naudit v2"
        mock_repo.update.assert_not_awaited()
        mock_sync.assert_called_once_with(USER_ID)
