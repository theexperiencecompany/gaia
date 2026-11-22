"""Journey: the app a GAIA task waits on disconnects; the task pauses, keeps the email, and resumes on reconnect."""

from __future__ import annotations

import pytest

from tests.e2e._harness.tasks_driver import TasksDriver
from tests.e2e._harness.tasks_views import Finishes, RunOutcome

pytestmark = pytest.mark.e2e

TITLE = "Get the deposit back from the landlord"
LANDLORD = "landlord@flatlets.com"
RETURNED = "The landlord confirmed the deposit is on its way."


class TestTheAppAGaiaTaskWaitsOnDisconnects:
    async def test_it_pauses_keeps_the_email_and_runs_on_it_once_reconnected(
        self, tasks: TasksDriver
    ) -> None:
        await tasks.connect_app("gmail")
        task = await tasks.hand_to_gaia(TITLE)
        await tasks.watch_emails_from(task.id, LANDLORD)

        await tasks.app_disconnects("gmail")
        paused = await tasks.get(task.id)
        assert paused is not None
        assert (paused.paused_reason, paused.paused_for_apps) == ("integration_expired", ("gmail",))

        await tasks.new_email(subject="Re: deposit", sender=LANDLORD, delivery_id="1")
        assert await tasks.runs(task.id) == []

        await tasks.connect_app("gmail")
        resumed = await tasks.get(task.id)
        assert resumed is not None and resumed.paused_reason is None
        await tasks.run_due(task.id, Finishes(RETURNED))

        runs = await tasks.runs(task.id)
        assert [(run.outcome, run.by_event) for run in runs] == [(RunOutcome.SUCCEEDED, True)]
        done = await tasks.get(task.id)
        assert done is not None and done.done is True
        assert RETURNED in (await tasks.delivered())[-1].body
