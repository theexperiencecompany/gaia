"""Journey: an app's connection lapses under a task that needs it, and coming back resumes it."""

from __future__ import annotations

import pytest

from tests.e2e._harness.tasks_driver import TasksDriver
from tests.e2e._harness.tasks_views import Reports, RunOutcome

pytestmark = pytest.mark.e2e

TITLE = "Draft replies to customer billing mail"
BRIEF = "When a customer emails about billing, draft a reply in my voice."
DRAFTED = "Drafted a reply to the invoice question."


class TestTheAppDisconnects:
    async def test_the_task_pauses_and_reconnecting_resumes_it(self, tasks: TasksDriver) -> None:
        await tasks.connect_app("gmail")
        task = await tasks.create_event_task(TITLE, BRIEF, app_event="gmail_new_message")

        await tasks.app_disconnects("gmail")

        paused = await tasks.get_repeating(task.id)
        assert (paused.active, paused.paused_reason) == (False, "integration_expired")
        await tasks.new_email(subject="Invoice 4021", sender="ap@acme.com", delivery_id="1")
        assert not await tasks.has_run_armed(task.id)

        await tasks.connect_app("gmail")

        resumed = await tasks.get_repeating(task.id)
        assert (resumed.active, resumed.paused_reason) == (True, None)
        await tasks.new_email(subject="Invoice 4022", sender="ap@acme.com", delivery_id="2")
        await tasks.run_due(task.id, Reports(DRAFTED))
        assert [r.outcome for r in await tasks.runs(task.id)] == [RunOutcome.SUCCEEDED]

    async def test_a_task_the_user_paused_stays_paused_on_reconnect(
        self, tasks: TasksDriver
    ) -> None:
        await tasks.connect_app("gmail")
        task = await tasks.create_event_task(TITLE, BRIEF, app_event="gmail_new_message")
        await tasks.pause(task.id)

        await tasks.app_disconnects("gmail")
        await tasks.connect_app("gmail")

        still = await tasks.get_repeating(task.id)
        assert (still.active, still.paused_reason) == (False, None)
