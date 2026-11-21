"""Target: a to-do the user keeps comes back when it repeats, and nudges them when it falls due."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from tests.e2e._harness.tasks_driver import TasksDriver

pytestmark = pytest.mark.e2e


class TestARepeatingTodo:
    async def test_reopens_on_its_next_day_after_being_ticked_off(self, tasks: TasksDriver) -> None:
        bins = await tasks.create_todo("Take the bins out", repeat="0 19 * * 2")
        await tasks.complete(bins.id)

        await tasks.pass_time_until(datetime.now(UTC) + timedelta(days=8))

        again = await tasks.get(bins.id)
        assert again is not None and again.done is False


class TestATodoWithADueTime:
    async def test_nudges_the_user_when_it_falls_due(self, tasks: TasksDriver) -> None:
        due = datetime.now(UTC) + timedelta(hours=3)
        todo = await tasks.create_todo("Call the bank", due=due)

        await tasks.pass_time_until(due + timedelta(minutes=5))

        assert [d for d in await tasks.delivered() if todo.title in d.title + d.body]
