"""Target: a meeting task left off for want of an app switches on once that app is connected."""

from __future__ import annotations

import pytest

from tests.e2e._harness.tasks_driver import TasksDriver

pytestmark = [pytest.mark.e2e, pytest.mark.tasks_target]


class TestConnectingTheMissingAppLater:
    async def test_the_meeting_briefing_switches_on(self, tasks: TasksDriver) -> None:
        await tasks.connect_app("googlecalendar")
        (briefing,) = [t for t in await tasks.repeating_tasks() if t.title == "Meeting Briefing"]
        assert briefing.active is False

        await tasks.connect_app("gmail")

        assert (await tasks.get_repeating(briefing.id)).active is True
