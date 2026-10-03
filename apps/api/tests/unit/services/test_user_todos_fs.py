"""Which of the user's todos the /workspace/todos/ projection carries, and what each one says.

The finder itself is contract-tested against real Mongo; this pins the glue that
decides the window it asks for and the shape it hands the VFS, which is where a
wrong label or a dropped subtask would land on disk unnoticed.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from app.constants.todos import GAIA_TRACKED_LABEL
from app.models.todo_models import TodoDocument
from app.services.user_todos_fs import ACTIVE_WINDOW_DAYS, _fetch_active_projections

pytestmark = pytest.mark.unit

MODULE = "app.services.user_todos_fs"
USER_ID = "507f1f77bcf86cd799439011"
TODO_ID = "66f838cc8829054e5f10e407"


def _doc(**overrides: object) -> TodoDocument:
    data: dict[str, object] = {
        "id": TODO_ID,
        "user_id": USER_ID,
        "title": "Book the flights",
        "subtasks": [{"id": "s1", "title": "Compare fares", "completed": True}],
        "created_at": datetime(2026, 9, 1, tzinfo=UTC),
        "updated_at": datetime(2026, 9, 2, tzinfo=UTC),
    }
    data.update(overrides)
    return TodoDocument(**data)


def _finder_returning(*docs: TodoDocument) -> tuple[AsyncMock, dict[str, object]]:
    """Patch the todos collection and record the window it was asked for."""
    asked: dict[str, object] = {}

    async def _list(user_id: str, *, completed_since: datetime) -> list[TodoDocument]:
        asked.update(user_id=user_id, completed_since=completed_since)
        return list(docs)

    finder = AsyncMock(side_effect=_list)
    return finder, asked


async def test_it_asks_for_the_user_todos_completed_inside_the_window() -> None:
    finder, asked = _finder_returning(_doc())
    before = datetime.now(UTC)

    with patch(f"{MODULE}.todo_repository.list_active_user_todos_since", finder):
        projections = await _fetch_active_projections(USER_ID)

    assert asked["user_id"] == USER_ID
    cutoff = asked["completed_since"]
    assert isinstance(cutoff, datetime)
    assert (
        before - timedelta(days=ACTIVE_WINDOW_DAYS)
        <= cutoff
        <= before - timedelta(days=ACTIVE_WINDOW_DAYS - 1)
    )
    assert [projection["id"] for projection in projections] == [TODO_ID]


async def test_each_projection_carries_the_todo_and_its_subtasks() -> None:
    finder, _asked = _finder_returning(_doc())

    with patch(f"{MODULE}.todo_repository.list_active_user_todos_since", finder):
        (projection,) = await _fetch_active_projections(USER_ID)

    assert projection["meta"]["title"] == "Book the flights"
    assert projection["meta"]["completed"] is False
    assert projection["meta"]["labels"] == []
    assert projection["meta"]["subtasks"] == [
        {"id": "s1", "title": "Compare fares", "completed": True}
    ]


async def test_the_gaia_tracked_exclusion_is_the_finders_not_this_glue() -> None:
    """GAIA's tracked todos never reach here because the finder leaves them out.

    That exclusion is the contract tier's to hold; what arrives here is projected as
    given, so this glue cannot quietly widen the list on its own.
    """
    finder, _asked = _finder_returning(_doc(labels=[GAIA_TRACKED_LABEL]))

    with patch(f"{MODULE}.todo_repository.list_active_user_todos_since", finder):
        (projection,) = await _fetch_active_projections(USER_ID)

    assert projection["meta"]["labels"] == [GAIA_TRACKED_LABEL]


async def test_a_user_with_nothing_active_projects_nothing() -> None:
    finder, _asked = _finder_returning()

    with patch(f"{MODULE}.todo_repository.list_active_user_todos_since", finder):
        assert await _fetch_active_projections(USER_ID) == []
