"""Journey: the user hands GAIA a one-off task; it runs, and either finishes or fails for good."""

from __future__ import annotations

import pytest

from tests.e2e._harness.tasks_driver import TasksDriver
from tests.e2e._harness.tasks_views import Breaks, Finishes, RunOutcome

pytestmark = pytest.mark.e2e

TITLE = "Check whether the visa appointment slots opened"
REPORT = "Slots opened for 3 December; nothing was booked."


class TestAOneOffGaiaTask:
    async def test_it_runs_finishes_and_tells_the_user(self, tasks: TasksDriver) -> None:
        task = await tasks.hand_to_gaia(TITLE)
        assert (task.title, task.by_gaia, task.done) == (TITLE, True, False)
        assert task.id in [t.id for t in await tasks.open_list()]

        await tasks.run_due(task.id, Finishes(REPORT))

        after = await tasks.get(task.id)
        assert after is not None and after.done is True
        assert [r.outcome for r in await tasks.runs(task.id)] == [RunOutcome.SUCCEEDED]
        (told,) = await tasks.delivered()
        assert REPORT in told.body

    async def test_a_run_that_keeps_failing_is_retried_then_marked_failed(
        self, tasks: TasksDriver
    ) -> None:
        task = await tasks.hand_to_gaia(TITLE)

        await tasks.run_due(task.id, Breaks())
        assert [r.outcome for r in await tasks.runs(task.id)] == [RunOutcome.FAILED]
        assert await tasks.delivered() == []
        await tasks.run_due(task.id, Breaks())
        await tasks.run_due(task.id, Breaks())

        after = await tasks.get(task.id)
        assert after is not None
        assert (after.done, after.failed) == (False, True)
        assert [r.outcome for r in await tasks.runs(task.id)] == [RunOutcome.FAILED] * 3
        (told,) = await tasks.delivered()
        assert TITLE in told.title
        # Failed for good: nothing is armed to run it again.
        assert not await tasks.has_run_armed(task.id)
