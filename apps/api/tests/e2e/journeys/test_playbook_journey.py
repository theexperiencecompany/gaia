"""Journey: a repeating task's second run replays the calls its first run saved; an edit drops them."""

from __future__ import annotations

import pytest

from tests.e2e._harness.tasks_driver import TasksDriver
from tests.e2e._harness.tasks_views import ReplaysPlaybook, Reports, RunOutcome, SavesPlaybook

pytestmark = pytest.mark.e2e

TITLE = "Monday plan flowchart"
BRIEF = "Every Monday, draw this week's plan as a flowchart."
DRAWN = "This week's plan is drawn."
REDRAWN = "This week's plan is drawn again."
EVERY_MONDAY = "0 8 * * 1"


async def _with_a_saved_playbook(tasks: TasksDriver) -> str:
    task = await tasks.create_repeating_task(TITLE, BRIEF, cron=EVERY_MONDAY)
    await tasks.run_due(task.id, SavesPlaybook(DRAWN))
    return task.id


class TestASavedPlaybook:
    async def test_the_next_run_replays_it_without_reasoning_and_delivers(
        self, tasks: TasksDriver
    ) -> None:
        task_id = await _with_a_saved_playbook(tasks)

        await tasks.run_due(task_id, ReplaysPlaybook(REDRAWN))

        first, second = await tasks.runs(task_id)
        assert (first.outcome, first.replayed) == (RunOutcome.SUCCEEDED, False)
        assert (second.outcome, second.replayed) == (RunOutcome.SUCCEEDED, True)
        chat = await tasks.chat(task_id)
        authored = next(line for line in chat if line.text == DRAWN)
        replay = chat[-1]
        assert replay.text == REDRAWN
        # The replay's card shows the first run's work call made again.
        assert set(replay.cards) & set(authored.cards)

    async def test_editing_the_brief_drops_it_and_the_next_run_reasons_again(
        self, tasks: TasksDriver
    ) -> None:
        task_id = await _with_a_saved_playbook(tasks)

        await tasks.edit_brief(task_id, "Every Monday, draw this week's plan and its risks.")
        await tasks.run_due(task_id, Reports(REDRAWN))

        _first, second = await tasks.runs(task_id)
        assert (second.outcome, second.replayed) == (RunOutcome.SUCCEEDED, False)
