"""Journey: a task GAIA repeats on a schedule fires, records its run, and arms the next one."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from tests.e2e._harness.tasks_driver import TasksDriver
from tests.e2e._harness.tasks_views import Reports, RunOutcome

pytestmark = pytest.mark.e2e

TITLE = "Morning news digest"
BRIEF = "Every morning, send me the three biggest tech stories with one line each."
DIGEST = "Three stories: a chip launch, a privacy ruling, a funding round."
DAILY_AT_8 = "0 8 * * *"
DAILY_AT_9 = "0 9 * * *"


class TestAScheduledTask:
    async def test_it_fires_records_the_run_and_arms_the_next(self, tasks: TasksDriver) -> None:
        task = await tasks.create_repeating_task(TITLE, BRIEF, cron=DAILY_AT_8)
        assert task.active is True
        assert task.next_run is not None and task.next_run > datetime.now(UTC)
        assert (task.next_run.hour, task.next_run.minute) == (8, 0)

        await tasks.run_due(task.id, Reports(DIGEST))

        assert [r.outcome for r in await tasks.runs(task.id)] == [RunOutcome.SUCCEEDED]
        after = await tasks.get_repeating(task.id)
        assert after.next_run is not None and after.next_run - task.next_run == timedelta(days=1)
        (told,) = await tasks.delivered()
        assert TITLE in told.title

        # The next morning's run was armed, and fires in its turn.
        await tasks.run_due(task.id, Reports(DIGEST))
        assert [r.outcome for r in await tasks.runs(task.id)] == [RunOutcome.SUCCEEDED] * 2

    async def test_a_reschedule_retires_the_old_firing(self, tasks: TasksDriver) -> None:
        task = await tasks.create_repeating_task(TITLE, BRIEF, cron=DAILY_AT_8)

        moved = await tasks.reschedule(task.id, cron=DAILY_AT_9)
        assert moved.next_run is not None and (moved.next_run.hour, moved.next_run.minute) == (9, 0)
        await tasks.fire_every_armed(task.id, Reports(DIGEST))

        # The 8am firing still arrived, and did nothing: one run, the 9am one.
        assert [r.outcome for r in await tasks.runs(task.id)] == [RunOutcome.SUCCEEDED]

    async def test_a_duplicate_firing_does_not_run_twice(self, tasks: TasksDriver) -> None:
        task = await tasks.create_repeating_task(TITLE, BRIEF, cron=DAILY_AT_8)

        await tasks.run_due(task.id, Reports(DIGEST))
        await tasks.fire_again(task.id)

        assert [r.outcome for r in await tasks.runs(task.id)] == [RunOutcome.SUCCEEDED]
        assert len(await tasks.delivered()) == 1
