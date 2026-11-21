"""Journey: connecting Calendar sets up GAIA's meeting tasks, once, and they reset to how they shipped."""

from __future__ import annotations

import pytest

from tests.e2e._harness.tasks_driver import TasksDriver

pytestmark = pytest.mark.e2e

MEETING_TASKS = {"Meeting Briefing", "Meeting Reminder"}


class TestConnectingCalendar:
    async def test_sets_up_the_meeting_tasks_switched_on(self, tasks: TasksDriver) -> None:
        await tasks.connect_app("gmail")
        assert await tasks.repeating_tasks() == []

        await tasks.connect_app("googlecalendar")

        set_up = await tasks.repeating_tasks()
        assert {(t.title, t.active) for t in set_up} == {(title, True) for title in MEETING_TASKS}

    async def test_a_meeting_task_needing_an_unconnected_app_is_set_up_switched_off(
        self, tasks: TasksDriver
    ) -> None:
        await tasks.connect_app("googlecalendar")

        assert {(t.title, t.active) for t in await tasks.repeating_tasks()} == {
            ("Meeting Briefing", False),
            ("Meeting Reminder", True),
        }

    async def test_connecting_again_sets_up_nothing_new(self, tasks: TasksDriver) -> None:
        await tasks.connect_app("googlecalendar")
        await tasks.app_disconnects("googlecalendar")
        await tasks.connect_app("googlecalendar")

        assert sorted(t.title for t in await tasks.repeating_tasks()) == sorted(MEETING_TASKS)

    async def test_an_edited_meeting_task_resets_to_how_it_shipped(
        self, tasks: TasksDriver
    ) -> None:
        await tasks.connect_app("googlecalendar")
        (briefing,) = [t for t in await tasks.repeating_tasks() if t.title == "Meeting Briefing"]
        shipped = await tasks.brief_of(briefing.id)

        await tasks.edit_brief(briefing.id, "Only brief me on meetings with customers.")
        assert await tasks.brief_of(briefing.id) != shipped
        await tasks.reset_to_default(briefing.id)

        assert await tasks.brief_of(briefing.id) == shipped
