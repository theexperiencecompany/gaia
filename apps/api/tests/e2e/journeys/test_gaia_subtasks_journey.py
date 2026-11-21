"""Journey: GAIA splits a task into sub-tasks, waits on them, and wakes as they finish."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from tests.e2e._harness.tasks_driver import TasksDriver
from tests.e2e._harness.tasks_views import Finishes, KeepsWaiting, OpensSubtasks, TaskView

pytestmark = pytest.mark.e2e

PARENT = "Move flats on the 14th"
QUOTES = "Get quotes from two movers"
VAN = "Book the van"
SPLIT = "Split the move into quotes and the van; waiting on both."


async def _split(tasks: TasksDriver) -> tuple[TaskView, TaskView, TaskView]:
    parent = await tasks.hand_to_gaia(PARENT)
    await tasks.run_due(parent.id, OpensSubtasks((QUOTES, VAN), SPLIT))
    by_title = {t.title: t for t in await tasks.subtasks_of(parent.id)}
    return parent, by_title[QUOTES], by_title[VAN]


class TestAParentWaitingOnItsSubtasks:
    async def test_it_wakes_as_each_finishes_and_closes_after_the_last(
        self, tasks: TasksDriver
    ) -> None:
        parent, quotes, van = await _split(tasks)
        assert (quotes.parent_id, van.parent_id) == (parent.id, parent.id)
        assert (quotes.by_gaia, quotes.done) == (True, False)
        waiting = await tasks.get(parent.id)
        assert waiting is not None and (waiting.done, waiting.open_children) == (False, 2)

        await tasks.complete(quotes.id)
        # One sub-task done is enough to wake the parent within the minute.
        woken = await tasks.get(parent.id)
        assert woken is not None and woken.next_run is not None
        assert woken.next_run - datetime.now(UTC) < timedelta(minutes=1)
        await tasks.run_due(parent.id, KeepsWaiting("Quotes are in; the van is not booked."))
        still = await tasks.get(parent.id)
        assert still is not None and (still.done, still.open_children) == (False, 1)

        await tasks.run_due(van.id, Finishes("Van booked for the 14th, 8am."))
        await tasks.run_due(parent.id, Finishes("Movers and van are both sorted."))

        done = await tasks.get(parent.id)
        assert done is not None and (done.done, done.open_children) == (True, 0)

    async def test_nothing_wakes_the_parent_while_no_subtask_finished(
        self, tasks: TasksDriver
    ) -> None:
        parent, _quotes, _van = await _split(tasks)

        waiting = await tasks.get(parent.id)
        assert waiting is not None and waiting.next_run is not None
        assert waiting.next_run - datetime.now(UTC) > timedelta(days=2)


class TestClosingOrDeletingTheParent:
    async def test_completing_the_parent_completes_its_open_subtasks(
        self, tasks: TasksDriver
    ) -> None:
        parent, quotes, van = await _split(tasks)

        await tasks.complete(parent.id)

        assert [(t.title, t.done) for t in await tasks.subtasks_of(parent.id)] == [
            (VAN, True),
            (QUOTES, True),
        ]

    async def test_deleting_the_parent_deletes_its_subtasks(self, tasks: TasksDriver) -> None:
        parent, quotes, van = await _split(tasks)

        await tasks.delete(parent.id)

        assert [await tasks.get(t.id) for t in (parent, quotes, van)] == [None, None, None]
