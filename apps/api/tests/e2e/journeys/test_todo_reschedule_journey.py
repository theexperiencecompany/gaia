"""Journey: moving a to-do's due time moves its nudge with it."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from tests.e2e._harness.tasks_driver import TasksDriver

pytestmark = pytest.mark.e2e

TITLE = "Renew the car insurance"


class TestMovingADueTime:
    async def test_the_nudge_comes_at_the_new_time_and_not_the_old(
        self, tasks: TasksDriver
    ) -> None:
        first = datetime.now(UTC) + timedelta(hours=2)
        moved = first + timedelta(hours=3)
        todo = await tasks.create_todo(TITLE, due=first)

        await tasks.edit(todo.id, due=moved)
        await tasks.pass_time_until(first + timedelta(minutes=5))
        early = [d for d in await tasks.delivered() if TITLE in d.title + d.body]
        await tasks.pass_time_until(moved + timedelta(minutes=5))
        nudged = [d for d in await tasks.delivered() if TITLE in d.title + d.body]

        assert (len(early), len(nudged)) == (0, 1)
