"""Journey: a task GAIA runs when a new email arrives, only when it matches the user's condition."""

from __future__ import annotations

import pytest

from tests.e2e._harness.tasks_driver import TasksDriver
from tests.e2e._harness.tasks_views import Reports, RunOutcome

pytestmark = pytest.mark.e2e

TITLE = "Draft replies to customer billing mail"
BRIEF = "When a customer emails about billing, draft a reply in my voice."
ONLY_WHEN = "the email is from a customer about billing"
DRAFTED = "Drafted a reply to the invoice question."


async def _watching(tasks: TasksDriver, only_when: str | None = ONLY_WHEN) -> str:
    await tasks.connect_app("gmail")
    task = await tasks.create_event_task(
        TITLE, BRIEF, app_event="gmail_new_message", only_when=only_when
    )
    assert task.active is True
    return task.id


class TestAnEmailThatMatches:
    async def test_it_runs_the_task(self, tasks: TasksDriver) -> None:
        task_id = await _watching(tasks)

        await tasks.new_email(
            subject="Invoice 4021 is wrong", sender="ap@acme.com", gate_passes=True, delivery_id="1"
        )
        await tasks.run_due(task_id, Reports(DRAFTED))

        assert [r.outcome for r in await tasks.runs(task_id)] == [RunOutcome.SUCCEEDED]
        assert (await tasks.get_repeating(task_id)).skipped_events == ()


class TestAnEmailTheConditionTurnsAway:
    async def test_it_is_skipped_and_the_skip_is_shown(self, tasks: TasksDriver) -> None:
        task_id = await _watching(tasks)

        await tasks.new_email(
            subject="50% off this weekend",
            sender="deals@shop.com",
            gate_passes=False,
            delivery_id="2",
        )

        (skipped,) = (await tasks.get_repeating(task_id)).skipped_events
        assert "50% off this weekend" in skipped
        assert not await tasks.has_run_armed(task_id)
        assert await tasks.runs(task_id) == []


class TestTheSameEmailDeliveredTwice:
    async def test_it_runs_once(self, tasks: TasksDriver) -> None:
        task_id = await _watching(tasks, only_when=None)

        for _ in range(2):
            await tasks.new_email(subject="Invoice 4021", sender="ap@acme.com", delivery_id="3")
        await tasks.run_due(task_id, Reports(DRAFTED))

        assert [r.outcome for r in await tasks.runs(task_id)] == [RunOutcome.SUCCEEDED]
        assert not await tasks.has_run_armed(task_id)


class TestAPausedTask:
    async def test_an_email_does_not_run_it(self, tasks: TasksDriver) -> None:
        task_id = await _watching(tasks, only_when=None)
        paused = await tasks.pause(task_id)
        assert paused.active is False

        await tasks.new_email(subject="Invoice 4021", sender="ap@acme.com", delivery_id="4")

        assert not await tasks.has_run_armed(task_id)
        assert await tasks.runs(task_id) == []
