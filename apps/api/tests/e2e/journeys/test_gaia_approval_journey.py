"""Journey: GAIA reaches an action the user wants to approve first; approving runs it, denying skips it."""

from __future__ import annotations

import pytest

from tests.e2e._harness.tasks_driver import TasksDriver
from tests.e2e._harness.tasks_views import NeedsApproval

pytestmark = pytest.mark.e2e

TITLE = "Draw up the launch plan"
ASKING = "Waiting on your approval to draw the launch plan."
DRAWN = "Drew the launch plan."
SKIPPED = "Skipped the launch plan, as you declined it."


async def _waiting_on_approval(tasks: TasksDriver) -> str:
    await tasks.ask_before_acting()
    task = await tasks.hand_to_gaia(TITLE)
    await tasks.run_due(task.id, NeedsApproval(ASKING))
    return task.id


class TestAnActionThatNeedsApproval:
    async def test_the_task_waits_and_tells_the_user(self, tasks: TasksDriver) -> None:
        task_id = await _waiting_on_approval(tasks)

        waiting = await tasks.get(task_id)
        assert waiting is not None and (waiting.pending_approval, waiting.done) == (True, False)
        assert ASKING in (await tasks.delivered())[-1].body
        assert await tasks.approved_actions_taken(task_id) == 0

    async def test_approving_takes_the_action(self, tasks: TasksDriver) -> None:
        task_id = await _waiting_on_approval(tasks)

        await tasks.approve(task_id, DRAWN)

        after = await tasks.get(task_id)
        assert after is not None and after.pending_approval is False
        assert await tasks.approved_actions_taken(task_id) == 1
        assert (await tasks.chat(task_id))[-1].text.startswith(DRAWN)

    async def test_denying_skips_the_action(self, tasks: TasksDriver) -> None:
        task_id = await _waiting_on_approval(tasks)

        await tasks.deny(task_id, SKIPPED)

        after = await tasks.get(task_id)
        assert after is not None and after.pending_approval is False
        assert await tasks.approved_actions_taken(task_id) == 0
        assert (await tasks.chat(task_id))[-1].text.startswith(SKIPPED)
