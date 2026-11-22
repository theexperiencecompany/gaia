"""Journey: where GAIA may file a subtask, and a subtask staying closed under a closed parent."""

from __future__ import annotations

import pytest

from tests.e2e._harness.tasks_driver import TasksDriver
from tests.e2e._harness.tasks_views import Finishes, OpensSubtasks, TaskRefusedError

pytestmark = pytest.mark.e2e

PARENT = "Plan the offsite"
VENUE = "Find a venue"
LATER = "Book the train"
FOUND = "Found a venue by the lake for the 3rd."


async def _split(tasks: TasksDriver) -> tuple[str, str]:
    parent = await tasks.hand_to_gaia(PARENT)
    await tasks.run_due(parent.id, OpensSubtasks((VENUE,), "Looking for a venue first."))
    (venue,) = await tasks.subtasks_of(parent.id)
    return parent.id, venue.id


class TestFilingASubtask:
    async def test_an_open_task_moves_under_an_open_parent(self, tasks: TasksDriver) -> None:
        parent_id, _venue = await _split(tasks)
        train = await tasks.hand_to_gaia(LATER)

        await tasks.gaia_files_under(train.id, parent_id)

        moved = await tasks.get(train.id)
        parent = await tasks.get(parent_id)
        assert moved is not None and moved.parent_id == parent_id
        assert parent is not None and parent.open_children == 2

    async def test_a_subtask_cannot_take_subtasks(self, tasks: TasksDriver) -> None:
        _parent_id, venue_id = await _split(tasks)
        train = await tasks.hand_to_gaia(LATER)

        said = await tasks.gaia_files_under(train.id, venue_id)

        assert said.startswith("Error:")
        unmoved = await tasks.get(train.id)
        assert unmoved is not None and unmoved.parent_id is None


class TestASubtaskUnderAClosedParent:
    async def test_it_cannot_reopen(self, tasks: TasksDriver) -> None:
        parent_id, venue_id = await _split(tasks)
        await tasks.complete(parent_id)

        with pytest.raises(TaskRefusedError):
            await tasks.reopen(venue_id)

        venue = await tasks.get(venue_id)
        assert venue is not None and venue.done


class TestASubtaskReportsToItsParent:
    async def test_its_result_is_not_sent_to_the_user(self, tasks: TasksDriver) -> None:
        _parent_id, venue_id = await _split(tasks)

        await tasks.run_due(venue_id, Finishes(FOUND))

        assert all(FOUND not in sent.body for sent in await tasks.delivered())
