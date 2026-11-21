"""Journey: a to-do the user keeps themselves, from creation to deletion."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta

import pytest

from tests.e2e._harness.tasks_driver import TasksDriver
from tests.e2e._harness.tasks_views import TaskNotFoundError

pytestmark = pytest.mark.e2e


def _later_today() -> datetime:
    """Return a time between now and the end of today (UTC), so it is due today and not overdue."""
    now = datetime.now(UTC)
    end_of_day = datetime.combine(now.date(), time.max, tzinfo=UTC)
    return now + (end_of_day - now) / 2


class TestAPlainTodo:
    async def test_it_is_edited_ticked_off_reopened_and_deleted(self, tasks: TasksDriver) -> None:
        todo = await tasks.create_todo("Book the dentist")
        assert (todo.title, todo.done, todo.subtasks) == ("Book the dentist", False, ())

        due = datetime.now(UTC) + timedelta(days=3)
        edited = await tasks.edit(todo.id, title="Book the dentist for Friday", due=due)
        assert edited.title == "Book the dentist for Friday"
        # Stored to the millisecond.
        assert edited.due is not None and abs(edited.due - due) < timedelta(milliseconds=1)

        await tasks.add_subtask(todo.id, "Find the number")
        with_steps = await tasks.add_subtask(todo.id, "Call before noon")
        find, call = with_steps.subtasks
        ticked = await tasks.tick_subtask(todo.id, find.id)
        renamed = await tasks.rename_subtask(todo.id, call.id, "Call before 11")
        assert [(s.title, s.done) for s in ticked.subtasks] == [
            ("Find the number", True),
            ("Call before noon", False),
        ]
        assert [(s.title, s.done) for s in renamed.subtasks] == [
            ("Find the number", True),
            ("Call before 11", False),
        ]

        done = await tasks.complete(todo.id)
        assert done.done is True
        assert todo.id not in [t.id for t in await tasks.open_list()]
        assert [t.id for t in await tasks.completed_list()] == [todo.id]
        assert (await tasks.counts()).completed == 1

        reopened = await tasks.reopen(todo.id)
        assert reopened.done is False
        assert [t.id for t in await tasks.open_list()] == [todo.id]
        assert (await tasks.counts()).completed == 0

        await tasks.delete(todo.id)
        assert await tasks.get(todo.id) is None
        assert await tasks.open_list() == []

    async def test_changing_a_todo_that_is_gone_is_refused(self, tasks: TasksDriver) -> None:
        todo = await tasks.create_todo("Return the library book")
        await tasks.delete(todo.id)

        with pytest.raises(TaskNotFoundError):
            await tasks.edit(todo.id, title="Return it tomorrow")
        with pytest.raises(TaskNotFoundError):
            await tasks.add_subtask(todo.id, "Find the receipt")

    async def test_ticking_a_subtask_that_is_not_there_is_refused(self, tasks: TasksDriver) -> None:
        todo = await tasks.create_todo("Pack for the trip")

        with pytest.raises(TaskNotFoundError):
            await tasks.tick_subtask(todo.id, "no-such-step")
        assert (await tasks.get(todo.id)) == todo


class TestTheListByDueDate:
    async def test_newest_first_with_overdue_and_today_counted_apart(
        self, tasks: TasksDriver
    ) -> None:
        overdue = await tasks.create_todo(
            "Pay the electricity bill", due=datetime.now(UTC) - timedelta(days=1)
        )
        today = await tasks.create_todo("Water the plants", due=_later_today())
        upcoming = await tasks.create_todo(
            "Renew the passport", due=datetime.now(UTC) + timedelta(days=10)
        )
        someday = await tasks.create_todo("Learn to juggle")

        listed = [t.id for t in await tasks.open_list()]
        assert listed == [someday.id, upcoming.id, today.id, overdue.id]
        assert [t.id for t in await tasks.overdue()] == [overdue.id]
        counts = await tasks.counts()
        assert (counts.today, counts.overdue) == (1, 1)

        await tasks.complete(overdue.id)
        assert await tasks.overdue() == []
        assert (await tasks.counts()).overdue == 0
