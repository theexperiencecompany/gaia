"""Journey: a GAIA task waiting on an email wakes when that email arrives, and only then."""

from __future__ import annotations

import pytest

from tests.e2e._harness.tasks_driver import TasksDriver
from tests.e2e._harness.tasks_views import Finishes

pytestmark = pytest.mark.e2e

TITLE = "Get the deposit back from the landlord"
LANDLORD = "landlord@flatlets.com"
RETURNED = "The landlord confirmed the deposit is on its way."


async def _waiting_on_the_landlord(tasks: TasksDriver) -> str:
    await tasks.connect_app("gmail")
    task = await tasks.hand_to_gaia(TITLE)
    await tasks.watch_emails_from(task.id, LANDLORD)
    return task.id


class TestAGaiaTaskWatchingForAnEmail:
    async def test_the_email_wakes_it_and_it_finishes(self, tasks: TasksDriver) -> None:
        task_id = await _waiting_on_the_landlord(tasks)

        await tasks.new_email(subject="Re: deposit", sender=LANDLORD, delivery_id="1")
        await tasks.run_due(task_id, Finishes(RETURNED))

        assert await tasks.woken_by_events(task_id) == 1
        done = await tasks.get(task_id)
        assert done is not None and done.done is True
        assert RETURNED in (await tasks.delivered())[-1].body

    async def test_an_email_from_anyone_else_does_not_wake_it(self, tasks: TasksDriver) -> None:
        task_id = await _waiting_on_the_landlord(tasks)
        armed = await tasks.runs_armed(task_id)

        await tasks.new_email(subject="Your parcel", sender="noreply@courier.com", delivery_id="2")

        assert await tasks.runs_armed(task_id) == armed
        assert await tasks.woken_by_events(task_id) == 0
