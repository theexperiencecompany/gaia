"""Journey: a GAIA task the lapsed plan stops tells the user once, and comes back with the plan.

The task's run is not taken, GAIA says the task paused and why, and nothing runs it again
until the plan is back; a later firing tells the user nothing new.
"""

from __future__ import annotations

import pytest

from tests.e2e._harness.tasks_driver import TasksDriver
from tests.e2e._harness.tasks_views import RunOutcome

pytestmark = pytest.mark.e2e

TITLE = "Morning news digest"


class TestALapsedPlanPausesAGaiaTask:
    async def test_a_repeating_task_tells_the_user_once_that_it_paused(
        self, tasks: TasksDriver
    ) -> None:
        said = await tasks.gaia_uses(
            "create_task", title=TITLE, assignee="gaia", repeat="0 8 * * *", body="The news."
        )
        (task,) = [t for t in await tasks.open_list() if t.title == TITLE]
        await tasks.let_subscription_lapse()

        await tasks.run_due(task.id)

        (told,) = await tasks.delivered()
        assert TITLE in told.title and "plan" in told.body, said
        paused = await tasks.get(task.id)
        assert paused is not None and paused.paused_reason == "subscription_lapsed"
        assert [r.outcome for r in await tasks.runs(task.id)] == [RunOutcome.SKIPPED]
        assert not await tasks.has_run_armed(task.id)

    async def test_a_one_off_task_tells_the_user_too(self, tasks: TasksDriver) -> None:
        task = await tasks.hand_to_gaia("Check whether the visa appointment slots opened")
        await tasks.let_subscription_lapse()

        await tasks.run_due(task.id)

        (told,) = await tasks.delivered()
        assert "visa appointment" in told.title
