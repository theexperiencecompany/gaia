"""Journey: a GAIA task asks the user to connect an app, waits, and picks up once they do."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase
import pytest
from scripts.tasks_migration.migrate import PROGRESS, migrate

from tests.conftest import FAKE_USER
from tests.e2e._harness.legacy_todos import LegacyTodos
from tests.e2e._harness.tasks_driver import TasksDriver
from tests.e2e._harness.tasks_views import AsksToConnect, Finishes

pytestmark = pytest.mark.e2e

USER = FAKE_USER.user_id
TITLE = "File the trip receipts in Notion"
ASKED = "I need Notion connected to file these; connect it and I will carry on."
FILED = "Filed all four receipts in the Trips page."
#: What the run that picks the task back up is told the user did.
CONNECTED = "The user just connected Notion."


@pytest.fixture
async def unmigrated(
    mongo_db: AsyncIOMotorDatabase[dict[str, Any]],
) -> AsyncIterator[AsyncIOMotorDatabase[dict[str, Any]]]:
    """Yield the database with no migration progress left from an earlier run."""
    await mongo_db[PROGRESS].delete_many({})
    yield mongo_db
    await mongo_db[PROGRESS].delete_many({})


class TestATaskWaitingOnTheUser:
    async def test_it_picks_up_when_the_user_connects_the_app(self, tasks: TasksDriver) -> None:
        await tasks.let_gaia_act_without_asking()
        task = await tasks.hand_to_gaia(TITLE)
        await tasks.run_due(task.id, AsksToConnect("notion", ASKED))

        await tasks.connect_app("notion")
        await tasks.pick_up_waiters()
        await tasks.run_due(task.id, Finishes(FILED))

        assert tasks.last_run_was_shown(CONNECTED)
        after = await tasks.get(task.id)
        assert after is not None and after.done is True

    async def test_a_wait_moved_over_from_a_todo_picks_up_its_task(
        self, tasks: TasksDriver, unmigrated: AsyncIOMotorDatabase[dict[str, Any]]
    ) -> None:
        legacy = LegacyTodos(unmigrated, USER)
        todo_id = await legacy.tracked_todo(TITLE)
        await legacy.waits_for_user_to_connect(todo_id, "notion", "Notion")
        report = await migrate(unmigrated, apply=True, user_ids=(USER,))
        assert report.clean, report.summary()

        await tasks.connect_app("notion")
        await tasks.pick_up_waiters()
        await tasks.run_due(todo_id, Finishes(FILED))

        assert tasks.last_run_was_shown(CONNECTED)
        after = await tasks.get(todo_id)
        assert after is not None and after.done is True
