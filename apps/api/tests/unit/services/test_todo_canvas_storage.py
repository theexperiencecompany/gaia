"""Unit tests for todo_canvas_storage (Mongo-backed facet read/write/append).

A tracked todo's content lives as three facets on the todo document:
``deliverable``, ``notes``, and ``log``. The storage primitives funnel every
read and write through the todos repository — atomicity here means: each
append reads the current value, then writes back the full concatenated
content in one update (no partial writes), and a write only succeeds when the
repository confirms the update matched.
"""

from datetime import UTC, datetime
from unittest.mock import DEFAULT, AsyncMock, MagicMock, patch

import pytest

from app.constants.todos import FACET_DELIVERABLE, FACET_LOG, FACET_NOTES
from app.models.todo_models import Artifact, ExecutionStatus, TodoDocument
from app.services.todo_canvas_storage import (
    append_facet,
    build_vfs_label,
    read_artifacts,
    read_facet,
    write_facet,
)

_MOD = "app.services.todo_canvas_storage"
USER_ID = "507f1f77bcf86cd799439011"
TODO_ID = "todo-1"


def _todo_doc(**overrides: object) -> TodoDocument:
    data: dict[str, object] = {
        "user_id": USER_ID,
        "title": "Ship the thing",
        "deliverable_content": "deliverable-v1",
        "notes_content": "notes-v1",
        "log_content": "log-v1",
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }
    data.update(overrides)
    return TodoDocument(**data)


def _scoped_to_the_owner(todo_id: str, *, user_id: str, **_: object) -> object:
    """Match no document unless the call carries both real ids.

    Every repository call here is scoped by ``(todo_id, user_id)`` — that pair
    is the tenancy boundary, and a call that drops or swaps either half reads
    or writes somebody else's todo. A mock that answers regardless of its
    arguments cannot tell the difference, so the fake enforces the scope and
    every "it worked" assertion below doubles as proof the ids were passed
    through untouched.
    """
    if todo_id != TODO_ID or user_id != USER_ID:
        return None
    return DEFAULT


@pytest.fixture
def mock_repo():
    with patch(f"{_MOD}.todo_repository") as m:
        m.get = AsyncMock(return_value=None, side_effect=_scoped_to_the_owner)
        m.update = AsyncMock(return_value=None, side_effect=_scoped_to_the_owner)
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


class TestFacetValidation:
    """An unknown facet is a caller bug, never user input — it must fail loud
    rather than silently reading or writing a field nobody asked for."""

    async def test_read_rejects_unknown_facet(self, mock_repo):
        with pytest.raises(ValueError, match="Unknown facet"):
            await read_facet(TODO_ID, USER_ID, "canvas")
        mock_repo.get.assert_not_awaited()

    async def test_write_rejects_unknown_facet(self, mock_repo):
        with pytest.raises(ValueError, match="Unknown facet"):
            await write_facet(TODO_ID, USER_ID, "canvas", "content")
        mock_repo.update.assert_not_awaited()


class TestReadFacet:
    async def test_none_for_missing_todo(self, mock_repo):
        assert await read_facet(TODO_ID, USER_ID, FACET_NOTES) is None

    @pytest.mark.parametrize(
        ("facet", "expected"),
        [
            (FACET_DELIVERABLE, "deliverable-v1"),
            (FACET_NOTES, "notes-v1"),
            (FACET_LOG, "log-v1"),
        ],
    )
    async def test_each_facet_reads_its_own_field(self, mock_repo, facet, expected):
        mock_repo.get.return_value = _todo_doc()

        assert await read_facet(TODO_ID, USER_ID, facet) == expected

    async def test_empty_string_when_unset(self, mock_repo):
        mock_repo.get.return_value = _todo_doc(log_content=None)

        assert await read_facet(TODO_ID, USER_ID, FACET_LOG) == ""


class TestReadFacetMigrationFallback:
    """Pre-facet todos stored everything in ``canvas_content``. Notes always
    falls back to it; deliverable only for proposals, whose staged content
    lived in the old canvas."""

    async def test_notes_falls_back_to_legacy_canvas(self, mock_repo):
        mock_repo.get.return_value = _todo_doc(notes_content=None, canvas_content="legacy body")

        assert await read_facet(TODO_ID, USER_ID, FACET_NOTES) == "legacy body"

    async def test_deliverable_falls_back_only_for_a_proposal(self, mock_repo):
        mock_repo.get.return_value = _todo_doc(
            deliverable_content=None,
            canvas_content="legacy body",
            execution_status=ExecutionStatus.PROPOSED,
        )

        assert await read_facet(TODO_ID, USER_ID, FACET_DELIVERABLE) == "legacy body"

    async def test_deliverable_does_not_fall_back_for_a_queued_todo(self, mock_repo):
        mock_repo.get.return_value = _todo_doc(
            deliverable_content=None,
            canvas_content="legacy body",
            execution_status=ExecutionStatus.QUEUED,
        )

        assert await read_facet(TODO_ID, USER_ID, FACET_DELIVERABLE) == ""

    async def test_log_never_falls_back_to_legacy_canvas(self, mock_repo):
        mock_repo.get.return_value = _todo_doc(log_content=None, canvas_content="legacy body")

        assert await read_facet(TODO_ID, USER_ID, FACET_LOG) == ""


class TestWriteFacet:
    @pytest.mark.parametrize(
        ("facet", "field"),
        [
            (FACET_DELIVERABLE, "deliverable_content"),
            (FACET_NOTES, "notes_content"),
            (FACET_LOG, "log_content"),
        ],
    )
    async def test_writes_the_facets_own_field_and_triggers_sync(
        self, mock_repo, mock_sync, facet, field
    ):
        mock_repo.update.return_value = _todo_doc()

        ok = await write_facet(TODO_ID, USER_ID, facet, "new content")

        assert ok is True
        update = mock_repo.update.await_args.kwargs["update"]
        assert getattr(update, field) == "new content"
        mock_sync.assert_called_once_with(USER_ID)

    async def test_write_leaves_the_other_facets_untouched(self, mock_repo, mock_sync):
        mock_repo.update.return_value = _todo_doc()

        await write_facet(TODO_ID, USER_ID, FACET_NOTES, "new notes")

        update = mock_repo.update.await_args.kwargs["update"]
        assert update.deliverable_content is None
        assert update.log_content is None

    async def test_false_when_update_matches_nothing(self, mock_repo, mock_sync):
        mock_repo.update.return_value = None

        assert await write_facet(TODO_ID, USER_ID, FACET_NOTES, "new content") is False
        mock_sync.assert_not_called()


class TestAppendFacet:
    async def test_false_for_missing_todo(self, mock_repo):
        assert await append_facet(TODO_ID, USER_ID, FACET_NOTES, "entry") is False

    async def test_the_missing_todo_warning_names_the_todo_and_the_facet(self, mock_repo):
        # The append returns False and writes nothing. The warning is the only
        # record that a facet write was dropped, so without both ids on it the
        # loss cannot be traced back to a todo.
        with patch(f"{_MOD}.log") as mock_log:
            assert await append_facet(TODO_ID, USER_ID, FACET_NOTES, "entry") is False

        mock_log.warning.assert_called_once_with(
            "todo_facet.append_missing_todo", todo_id=TODO_ID, facet=FACET_NOTES
        )

    async def test_appends_with_newline_separator(self, mock_repo, mock_sync):
        mock_repo.get.return_value = _todo_doc(notes_content="existing")
        mock_repo.update.return_value = _todo_doc()

        ok = await append_facet(TODO_ID, USER_ID, FACET_NOTES, "entry")

        assert ok is True
        assert mock_repo.update.await_args.kwargs["update"].notes_content == "existing\nentry"

    async def test_preserves_leading_newline_in_content(self, mock_repo, mock_sync):
        mock_repo.get.return_value = _todo_doc(log_content="existing")
        mock_repo.update.return_value = _todo_doc()

        await append_facet(TODO_ID, USER_ID, FACET_LOG, "\nentry")

        assert mock_repo.update.await_args.kwargs["update"].log_content == "existing\nentry"

    async def test_round_trip_appends_accumulate(self, mock_repo, mock_sync):
        """Two appends must produce one content string — the read-then-write
        pattern concatenates instead of overwriting."""
        notes = "v1"
        mock_repo.update.return_value = _todo_doc()

        async def fake_get(todo_id: str, **kwargs: object) -> TodoDocument | None:
            return _todo_doc(notes_content=notes)

        async def fake_update(todo_id: str, **kwargs: object) -> TodoDocument:
            nonlocal notes
            notes = kwargs["update"].notes_content
            return _todo_doc(notes_content=notes)

        mock_repo.get = fake_get
        mock_repo.update = fake_update

        await append_facet(TODO_ID, USER_ID, FACET_NOTES, "b")
        await append_facet(TODO_ID, USER_ID, FACET_NOTES, "c")

        assert notes == "v1\nb\nc"


class TestReadArtifacts:
    async def test_none_for_missing_todo(self, mock_repo):
        assert await read_artifacts(TODO_ID, USER_ID) is None

    async def test_empty_list_when_the_todo_has_no_artifacts(self, mock_repo):
        mock_repo.get.return_value = _todo_doc()

        assert await read_artifacts(TODO_ID, USER_ID) == []

    async def test_returns_serialized_artifacts(self, mock_repo):
        mock_repo.get.return_value = _todo_doc(
            artifacts=[Artifact(name="Draft", content="body", kind="markdown")]
        )

        assert await read_artifacts(TODO_ID, USER_ID) == [
            {"name": "Draft", "content": "body", "kind": "markdown"}
        ]
