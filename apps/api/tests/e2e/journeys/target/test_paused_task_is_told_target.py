"""Target: when a repeating task stops because the plan lapsed, the user is told, once."""

from __future__ import annotations

import pytest

from tests.e2e._harness.tasks_driver import TasksDriver

pytestmark = [pytest.mark.e2e, pytest.mark.tasks_target]

TITLE = "Morning news digest"


class TestALapsedPlanPausesARepeatingTask:
    async def test_the_user_is_told_it_paused(self, tasks: TasksDriver) -> None:
        task = await tasks.create_repeating_task(TITLE, "Send me the news.", cron="0 8 * * *")
        await tasks.let_subscription_lapse()

        await tasks.run_due(task.id)

        (told,) = await tasks.delivered()
        assert TITLE in told.title + told.body
