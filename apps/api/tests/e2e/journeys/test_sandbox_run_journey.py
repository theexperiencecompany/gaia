"""Journey: GAIA hands long coding work to an agent in the sandbox, and the run reports back to its task.

GAIA starts the run for one of its tasks; every event the coding agent pushes wakes that
task with the event, and the task's run tells the user. Two runs never cross, a run whose
task is done is refused, and a replaced sandbox wakes the task watching it.
"""

from __future__ import annotations

import pytest

from tests.e2e._harness.tasks_driver import TasksDriver
from tests.e2e._harness.tasks_views import Finishes, Reports, RunOutcome

pytestmark = pytest.mark.e2e

TITLE = "Fix the flaky checkout test"
AGENT_SAID = "All 214 tests pass; the race in the checkout fixture is gone."
REPORT = "The flaky checkout test is fixed and the suite is green."
#: What Claude Code's Stop hook posts when it finishes its turn.
FINISHED = {"hook_event_name": "Stop", "last_assistant_message": AGENT_SAID}


class TestASandboxRunGaiaStarted:
    async def test_its_finish_wakes_the_task_with_the_result_and_the_user_is_told(
        self, tasks: TasksDriver
    ) -> None:
        task = await tasks.hand_to_gaia(TITLE)
        run = await tasks.gaia_starts_sandbox_run(task.id)

        assert await tasks.sandbox_run_reports(run, FINISHED) == 202
        await tasks.run_due(task.id, Finishes(REPORT))

        assert tasks.last_run_was_shown(AGENT_SAID)
        assert [(r.outcome, r.by_event) for r in await tasks.runs(task.id)] == [
            (RunOutcome.SUCCEEDED, True)
        ]
        done = await tasks.get(task.id)
        assert done is not None and done.done
        (told,) = await tasks.delivered()
        assert REPORT in told.body

    async def test_two_runs_each_wake_only_their_own_task(self, tasks: TasksDriver) -> None:
        first = await tasks.hand_to_gaia(TITLE)
        second = await tasks.hand_to_gaia("Upgrade the payments SDK")
        first_run = await tasks.gaia_starts_sandbox_run(first.id)
        second_run = await tasks.gaia_starts_sandbox_run(second.id)

        assert await tasks.sandbox_run_reports(second_run, FINISHED) == 202
        await tasks.run_due(second.id, Reports("The SDK upgrade finished."))

        assert [r.by_event for r in await tasks.runs(second.id)] == [True]
        assert await tasks.runs(first.id) == []
        assert first_run != second_run

    async def test_an_event_after_the_task_is_done_is_refused_and_wakes_nothing(
        self, tasks: TasksDriver
    ) -> None:
        task = await tasks.hand_to_gaia(TITLE)
        run = await tasks.gaia_starts_sandbox_run(task.id)
        await tasks.complete(task.id)

        assert await tasks.sandbox_run_reports(run, FINISHED) == 404
        assert await tasks.runs(task.id) == []

    async def test_a_replaced_sandbox_wakes_the_task_watching_its_run(
        self, tasks: TasksDriver
    ) -> None:
        task = await tasks.hand_to_gaia(TITLE)
        await tasks.gaia_starts_sandbox_run(task.id)

        await tasks.sandbox_is_replaced()
        await tasks.run_due(task.id, Reports("Relaunched the agent from its last save."))

        assert tasks.last_run_was_shown("sandbox_replaced")
        assert [r.by_event for r in await tasks.runs(task.id)] == [True]
