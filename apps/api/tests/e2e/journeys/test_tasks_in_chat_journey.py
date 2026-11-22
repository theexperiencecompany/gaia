"""Journey: the user runs their tasks by talking to GAIA, through both real graphs.

Comms hands each message to the executor, which works with the task tools. Asserted on
the tasks left behind and on which tools ran and what they answered, never on prose.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from tests.e2e._harness.graph_run import call
from tests.e2e._harness.tasks_driver import TasksDriver

pytestmark = pytest.mark.e2e

#: The todo and tracked-todo tools the task tools replaced; none may reach the model.
REMOVED_TOOLS = frozenset(
    {
        "create_tracked_todo",
        "update_tracked_todo",
        "complete_tracked_todo",
        "list_tracked_todos",
        "search_todo_context",
        "subscribe_todo_to_trigger",
        "unsubscribe_todo_from_trigger",
        "list_trigger_fields",
        "create_todo",
        "list_todos",
        "update_todo",
        "delete_todo",
        "search_todos",
        "semantic_search_todos",
        "bulk_complete_todos",
        "bulk_delete_todos",
        "get_today_todos",
        "get_upcoming_todos",
        "get_todos_summary",
        "get_todo_statistics",
        "add_checklist_item",
        "update_checklist_item",
        "delete_checklist_item",
    }
)


def _later_today() -> str:
    now = datetime.now(UTC)
    end_of_day = now.replace(hour=23, minute=0, second=0, microsecond=0)
    return (end_of_day if end_of_day > now else now + timedelta(minutes=5)).isoformat()


class TestTasksInChat:
    async def test_add_hand_over_list_find_and_complete(self, tasks: TasksDriver) -> None:
        added = await tasks.ask_in_chat(
            "Add buying milk to my list for today",
            gaia_calls=[
                call(
                    "create_task",
                    {"title": "Buy milk", "assignee": "user", "due": _later_today()},
                    call_id="tc_add",
                )
            ],
            says="Added.",
        )
        handed = await tasks.ask_in_chat(
            "Keep an eye on the visa appointment slots for me",
            gaia_calls=[
                call(
                    "create_task",
                    {
                        "title": "Watch the visa appointment slots",
                        "assignee": "gaia",
                        "waiting_on": "time",
                        "next_check": "1d",
                    },
                    call_id="tc_hand",
                )
            ],
            says="I'll keep watching.",
        )
        checkup = await tasks.create_todo("Book a check-up")
        await tasks.gaia_uses("update_task", task_id=checkup.id, body="The toothache on the left.")
        (milk,) = [t for t in await tasks.open_list() if t.title == "Buy milk"]
        (watch,) = [t for t in await tasks.open_list() if t.by_gaia]

        today = await tasks.ask_in_chat(
            "What's on today?",
            gaia_calls=[call("list_tasks", {"view": "today"}, call_id="tc_today")],
            says="One thing today.",
        )
        found = await tasks.ask_in_chat(
            "Where's that dentist thing?",
            gaia_calls=[call("search_tasks", {"query": "dentist appointment"}, call_id="tc_find")],
            says="Found it.",
        )
        closed = await tasks.ask_in_chat(
            "I bought the milk",
            gaia_calls=[
                call(
                    "complete_task",
                    {"task_id": milk.id, "summary": "The user bought it."},
                    call_id="tc_done",
                )
            ],
            says="Ticked off.",
        )

        assert [m.name for m in (*added, *handed, *today, *found, *closed)] == [
            "create_task",
            "create_task",
            "list_tasks",
            "search_tasks",
            "complete_task",
        ]
        assert (milk.by_gaia, watch.title) == (False, "Watch the visa appointment slots")
        assert milk.id in str(today[0].content) and watch.id not in str(today[0].content)
        assert str(found[0].content).index(checkup.id) < str(found[0].content).index(milk.id)
        done = await tasks.get(milk.id)
        assert done is not None and done.done is True

    async def test_gaia_is_offered_only_the_task_tools(self, tasks: TasksDriver) -> None:
        await tasks.ask_in_chat(
            "What's on my list today?",
            gaia_calls=[call("list_tasks", {"view": "today"}, call_id="tc_today")],
            says="Nothing is due today.",
        )

        offered = tasks.tools_offered_to_gaia()
        assert {"create_task", "update_task", "complete_task", "list_tasks", "search_tasks"} <= (
            offered
        )
        assert offered.isdisjoint(REMOVED_TOOLS), sorted(offered & REMOVED_TOOLS)
        reachable = await tasks.tools_gaia_can_retrieve()
        assert reachable.isdisjoint(REMOVED_TOOLS), sorted(reachable & REMOVED_TOOLS)
