"""Sidebar counts, the Today and Upcoming lists and the agent's summary all bucket todos the same way, on the user's local day, against real Mongo."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.agents.tools.todo_tool import get_todos_summary
from app.db.repositories.todos import todo_repository
from app.models.todo_models import TodoDayWindow, TodoDocument, TodoListParams
from app.services.todos.todo_service import TodoService
from app.utils.timezone import Timezone

pytestmark = pytest.mark.service

IST = Timezone.parse("Asia/Kolkata")
INBOX = "inbox-project"


@pytest.fixture(autouse=True)
def _no_stream() -> Iterator[None]:
    with patch("app.agents.tools.todo_tool.current_stream_writer", return_value=MagicMock()):
        yield


async def _todo(user_id: str, title: str, due: datetime | None, **fields: Any) -> None:
    await todo_repository.create(
        TodoDocument.model_validate(
            {"user_id": user_id, "title": title, "due_date": due, "project_id": INBOX, **fields}
        )
    )


async def _seed_one_per_bucket(user_id: str, window: TodoDayWindow) -> None:
    # 00:30 IST is always the previous UTC calendar day: the UTC-day rule missed it.
    await _todo(user_id, "early today", window.today_start + timedelta(minutes=30))
    await _todo(user_id, "tomorrow", window.tomorrow_start + timedelta(hours=1))
    await _todo(user_id, "yesterday", window.today_start - timedelta(hours=1))
    await _todo(user_id, "next month", window.upcoming_end + timedelta(days=20))


def _ist_window() -> TodoDayWindow:
    return TodoDayWindow.for_timezone(IST, datetime.now(UTC))


async def test_sidebar_counts_follow_the_users_local_day(user_id: str) -> None:
    window = _ist_window()
    await _seed_one_per_bucket(user_id, window)

    counts = await todo_repository.compute_counts(
        user_id=user_id, inbox_project_id=INBOX, window=window
    )

    assert (counts.today, counts.upcoming, counts.overdue) == (1, 1, 1)


async def test_today_and_upcoming_pages_list_the_users_local_days(user_id: str) -> None:
    window = _ist_window()
    await _seed_one_per_bucket(user_id, window)

    today = await TodoService.list_todos(
        user_id, TodoListParams(due_today=True, completed=False).to_search_params(window)
    )
    upcoming = await TodoService.list_todos(
        user_id, TodoListParams(due_this_week=True, completed=False).to_search_params(window)
    )
    overdue = await TodoService.list_todos(
        user_id, TodoListParams(overdue=True).to_search_params(window)
    )

    assert [t.title for t in today.data] == ["early today"]
    assert [t.title for t in upcoming.data] == ["tomorrow"]
    assert [t.title for t in overdue.data] == ["yesterday"]


async def test_summary_counts_every_todo_and_upcoming_excludes_today(user_id: str) -> None:
    window = _ist_window()
    await _seed_one_per_bucket(user_id, window)
    for n in range(120):
        await _todo(user_id, f"done {n}", None, completed=True)

    result = await get_todos_summary.ainvoke(
        {}, config={"configurable": {"user_id": user_id, "user_timezone": IST.value}}
    )

    summary = result["summary"]
    assert result["error"] is None
    assert summary["stats"]["total"] == 124
    assert summary["stats"]["completed"] == 120
    assert summary["stats"]["overdue"] == 1
    assert summary["today"]["count"] == 1
    assert [t["title"] for t in summary["upcoming_week"]["todos"]] == ["tomorrow"]
    assert summary["next_deadline"]["title"] in {"early today", "tomorrow"}
