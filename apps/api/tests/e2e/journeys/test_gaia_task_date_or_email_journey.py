"""Journey: a GAIA task with a next check and an email to wait for runs once, on whichever comes first."""

from __future__ import annotations

import pytest

from tests.e2e._harness.tasks_driver import TasksDriver
from tests.e2e._harness.tasks_views import Finishes, RunOutcome

pytestmark = pytest.mark.e2e

TITLE = "Get the deposit back from the landlord"
LANDLORD = "landlord@flatlets.com"
RETURNED = "The landlord confirmed the deposit is on its way."


async def _results_told(tasks: TasksDriver) -> int:
    return sum(RETURNED in message.body for message in await tasks.delivered())


class TestAGaiaTaskWithADateAndAnEmailToWaitFor:
    async def test_the_email_comes_first_and_the_date_does_not_run_it_again(
        self, tasks: TasksDriver
    ) -> None:
        await tasks.connect_app("gmail")
        task = await tasks.hand_to_gaia(TITLE, first_look="3d")
        await tasks.watch_emails_from(task.id, LANDLORD)

        await tasks.new_email(subject="Re: deposit", sender=LANDLORD, delivery_id="1")
        await tasks.run_due(task.id, Finishes(RETURNED))
        await tasks.run_due(task.id)

        runs = await tasks.runs(task.id)
        assert [(run.outcome, run.by_event) for run in runs] == [(RunOutcome.SUCCEEDED, True)]
        assert await _results_told(tasks) == 1
        assert await tasks.has_run_armed(task.id) is False

    async def test_the_date_comes_first_and_a_later_email_does_not_run_it_again(
        self, tasks: TasksDriver
    ) -> None:
        await tasks.connect_app("gmail")
        task = await tasks.hand_to_gaia(TITLE)
        await tasks.watch_emails_from(task.id, LANDLORD)

        await tasks.run_due(task.id, Finishes(RETURNED))
        await tasks.new_email(subject="Re: deposit", sender=LANDLORD, delivery_id="2")

        runs = await tasks.runs(task.id)
        assert [(run.outcome, run.by_event) for run in runs] == [(RunOutcome.SUCCEEDED, False)]
        assert await tasks.woken_by_events(task.id) == 0
        assert await tasks.has_run_armed(task.id) is False
        assert await _results_told(tasks) == 1
