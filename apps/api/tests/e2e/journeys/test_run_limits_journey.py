"""Journey: GAIA's runs are paid for; a spent allowance or a lapsed plan stops them and says so."""

from __future__ import annotations

import pytest

from tests.e2e._harness.tasks_driver import TasksDriver
from tests.e2e._harness.tasks_views import Reports, RunOutcome

pytestmark = pytest.mark.e2e

TITLE = "Morning news digest"
BRIEF = "Every morning, send me the three biggest tech stories with one line each."
DIGEST = "Three stories: a chip launch, a privacy ruling, a funding round."


class TestARunPastTheDaysAllowance:
    async def test_it_is_refused_the_user_is_told_and_tomorrow_still_runs(
        self, tasks: TasksDriver
    ) -> None:
        task = await tasks.create_repeating_task(TITLE, BRIEF, cron="0 8 * * *")
        await tasks.use_up_runs_for_the_day(task.id)

        await tasks.run_due(task.id)

        (refused,) = await tasks.runs(task.id)
        assert refused.outcome is RunOutcome.FAILED
        (told,) = await tasks.delivered()
        assert TITLE in told.title
        still = await tasks.get_repeating(task.id)
        assert still.active is True
        await tasks.run_due(task.id, Reports(DIGEST))
        assert [r.outcome for r in await tasks.runs(task.id)] == [
            RunOutcome.FAILED,
            RunOutcome.SUCCEEDED,
        ]


class TestALapsedSubscription:
    async def test_a_repeating_task_is_paused_without_running(self, tasks: TasksDriver) -> None:
        task = await tasks.create_repeating_task(TITLE, BRIEF, cron="0 8 * * *")
        await tasks.let_subscription_lapse()

        await tasks.run_due(task.id)

        assert await tasks.runs(task.id) == []
        paused = await tasks.get_repeating(task.id)
        assert (paused.active, paused.paused_reason) == (False, "subscription_lapsed")

    async def test_a_gaia_task_skips_its_run_and_says_why(self, tasks: TasksDriver) -> None:
        task = await tasks.hand_to_gaia("Check whether the visa appointment slots opened")
        await tasks.let_subscription_lapse()

        await tasks.run_due(task.id)

        (skipped,) = await tasks.runs(task.id)
        assert skipped.outcome is RunOutcome.SKIPPED
        assert skipped.reason is not None and "subscription" in skipped.reason
        still = await tasks.get(task.id)
        assert still is not None and still.done is False
