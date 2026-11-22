"""Journey: everything the user asks GAIA to do with their list in chat, done with the task tools.

What the old todo tools offered a user in chat (their list and its day views, a checklist,
reopening, closing and deleting several at once, GAIA's notes, priorities) is asserted on
the tasks it leaves, not on what GAIA says.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from tests.e2e._harness.tasks_driver import TasksDriver

pytestmark = pytest.mark.e2e


def _later_today() -> datetime:
    now = datetime.now(UTC)
    end_of_day = now.replace(hour=23, minute=0, second=0, microsecond=0)
    return end_of_day if end_of_day > now else now + timedelta(minutes=5)


class TestTheListInChat:
    async def test_today_upcoming_overdue_and_a_search_each_show_their_tasks(
        self, tasks: TasksDriver
    ) -> None:
        today = await tasks.create_todo("Call the bank", due=_later_today())
        soon = await tasks.create_todo(
            "Renew the passport", due=datetime.now(UTC) + timedelta(days=3)
        )
        late = await tasks.create_todo(
            "Pay the gas bill", due=datetime.now(UTC) - timedelta(days=2)
        )

        shown_today = await tasks.gaia_uses("list_tasks", view="today")
        shown_upcoming = await tasks.gaia_uses("list_tasks", view="upcoming")
        shown_overdue = await tasks.gaia_uses("list_tasks", view="overdue")
        found = await tasks.gaia_uses("list_tasks", query="passport")

        assert today.id in shown_today and soon.id not in shown_today
        assert soon.id in shown_upcoming and today.id not in shown_upcoming
        assert late.id in shown_overdue and today.id not in shown_overdue
        assert soon.id in found and today.id not in found and late.id not in found


class TestAChecklistInChat:
    async def test_items_are_added_renamed_ticked_and_removed(self, tasks: TasksDriver) -> None:
        todo = await tasks.create_todo("Groceries")

        await tasks.gaia_uses("edit_checklist", task_id=todo.id, change="add", title="Milk")
        await tasks.gaia_uses("edit_checklist", task_id=todo.id, change="add", title="Bread")
        listed = await tasks.get(todo.id)
        assert listed is not None
        milk, bread = listed.subtasks
        await tasks.gaia_uses(
            "edit_checklist", task_id=todo.id, change="rename", item_id=milk.id, title="Oat milk"
        )
        await tasks.gaia_uses("edit_checklist", task_id=todo.id, change="tick", item_id=milk.id)
        await tasks.gaia_uses("edit_checklist", task_id=todo.id, change="remove", item_id=bread.id)

        after = await tasks.get(todo.id)
        assert after is not None
        assert [(s.title, s.done) for s in after.subtasks] == [("Oat milk", True)]
        shown = await tasks.gaia_uses("get_task", task_id=todo.id)
        assert milk.id in shown


class TestClosingReopeningAndDeletingInChat:
    async def test_several_are_ticked_off_one_reopened_and_two_deleted(
        self, tasks: TasksDriver
    ) -> None:
        first = await tasks.create_todo("Water the plants")
        second = await tasks.create_todo("Take the bins out")
        third = await tasks.create_todo("Book the dentist")

        await tasks.gaia_uses("complete_tasks", task_ids=[first.id, second.id])
        await tasks.gaia_uses("reopen_task", task_id=second.id)
        await tasks.gaia_uses("delete_tasks", task_ids=[second.id, third.id])

        assert [t.id for t in await tasks.completed_list()] == [first.id]
        assert await tasks.get(second.id) is None and await tasks.get(third.id) is None
        assert await tasks.open_list() == []


class TestGaiasNotesAndPriorities:
    async def test_notes_and_priority_are_kept_on_the_task(self, tasks: TasksDriver) -> None:
        task = await tasks.hand_to_gaia("Find a plumber for the leak")
        todo = await tasks.create_todo("Fix the gate")

        await tasks.gaia_uses(
            "update_task", task_id=task.id, notes="## Current State\nAsked two plumbers."
        )
        await tasks.gaia_uses("update_task", task_id=todo.id, priority="high")
        refused = await tasks.gaia_uses("update_task", task_id=todo.id, notes="no")

        assert "Asked two plumbers." in await tasks.gaia_uses("get_task", task_id=task.id)
        fixed = await tasks.get(todo.id)
        assert fixed is not None and fixed.priority == "high"
        assert refused.startswith("Error")
