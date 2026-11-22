"""Journey: an email a GAIA task listens for can tell the user, close the task or unblock it.

Not every subscription runs GAIA. A task can ask only to be told when the email lands,
to be closed by it, or to be unblocked by it; a todo moved over from the old system keeps
whichever of these it had.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase
import pytest
from scripts.tasks_migration.migrate import PROGRESS, migrate
from scripts.tasks_migration.parity import check_parity

from tests.conftest import FAKE_USER
from tests.e2e._harness.tasks_driver import TasksDriver
from tests.e2e._harness.tasks_views import Finishes, OnEvent, RunOutcome

pytestmark = pytest.mark.e2e

TITLE = "Get the deposit back from the landlord"
LANDLORD = "landlord@flatlets.com"
RETURNED = "The landlord confirmed the deposit is on its way."
MIGRATION_TARGETS = ("tasks", "task_runs", "task_templates", "task_playbooks", PROGRESS)


async def _told_about(tasks: TasksDriver, title: str) -> int:
    return sum(title in message.title for message in await tasks.delivered())


class TestAnEmailThatTellsTheUser:
    async def test_the_user_is_told_once_and_gaia_does_not_run_until_its_date(
        self, tasks: TasksDriver
    ) -> None:
        await tasks.connect_app("gmail")
        task = await tasks.hand_to_gaia(TITLE, first_look="3d")
        await tasks.watch_emails_from(task.id, LANDLORD, then=OnEvent.TELL_ME)

        await tasks.new_email(subject="Re: deposit", sender=LANDLORD, delivery_id="1")
        await tasks.new_email(subject="Re: deposit", sender=LANDLORD, delivery_id="1")
        await tasks.new_email(subject="Lunch?", sender="friend@mail.com", delivery_id="2")

        assert await _told_about(tasks, TITLE) == 1
        assert await tasks.runs(task.id) == []
        assert await tasks.woken_by_events(task.id) == 1
        await tasks.run_due(task.id, Finishes(RETURNED))
        assert [run.outcome for run in await tasks.runs(task.id)] == [RunOutcome.SUCCEEDED]
        assert await tasks.has_run_armed(task.id) is False

    async def test_a_second_email_inside_the_cooldown_tells_nothing_more(
        self, tasks: TasksDriver
    ) -> None:
        await tasks.connect_app("gmail")
        task = await tasks.hand_to_gaia(TITLE, first_look="3d")
        await tasks.watch_emails_from(
            task.id, LANDLORD, then=OnEvent.TELL_ME, batch_for=timedelta(hours=1)
        )

        await tasks.new_email(subject="Re: deposit", sender=LANDLORD, delivery_id="6")
        await tasks.new_email(subject="Re: deposit, again", sender=LANDLORD, delivery_id="7")

        assert await _told_about(tasks, TITLE) == 1
        assert await tasks.woken_by_events(task.id) == 1


class TestAnEmailThatClosesTheTask:
    async def test_the_task_is_done_without_a_run(self, tasks: TasksDriver) -> None:
        await tasks.connect_app("gmail")
        task = await tasks.hand_to_gaia(TITLE, first_look="3d")
        await tasks.watch_emails_from(task.id, LANDLORD, then=OnEvent.CLOSE)

        await tasks.new_email(subject="Deposit returned", sender=LANDLORD, delivery_id="3")

        closed = await tasks.get(task.id)
        assert closed is not None and closed.done is True
        # Its first look comes round and finds nothing left to do.
        await tasks.run_due(task.id)
        assert await tasks.runs(task.id) == []


class TestAnEmailThatUnblocksTheTask:
    async def test_a_task_with_nothing_blocking_it_tells_the_user_instead(
        self, tasks: TasksDriver
    ) -> None:
        await tasks.connect_app("gmail")
        task = await tasks.hand_to_gaia(TITLE, first_look="3d")
        await tasks.watch_emails_from(task.id, LANDLORD, then=OnEvent.UNBLOCK)

        await tasks.new_email(subject="Re: deposit", sender=LANDLORD, delivery_id="4")

        assert await _told_about(tasks, TITLE) == 1
        assert await tasks.runs(task.id) == []

    async def test_a_moved_todo_waiting_on_the_reply_is_unblocked_by_it(
        self, tasks: TasksDriver, mongo_db: AsyncIOMotorDatabase[dict[str, Any]]
    ) -> None:
        await tasks.connect_app("gmail")
        todo_id = await _legacy_todo_waiting_on_a_reply(mongo_db)
        await _move_to_tasks(mongo_db)
        try:
            assert await _flags(mongo_db, todo_id) == ["waiting_for_reply"]

            await tasks.new_email(subject="Re: deposit", sender=LANDLORD, delivery_id="5")

            assert await _flags(mongo_db, todo_id) == []
            assert await mongo_db["task_runs"].count_documents({"task_id": todo_id}) == 0
            assert await _told_about(tasks, TITLE) == 0
        finally:
            for name in MIGRATION_TARGETS:
                await mongo_db[name].delete_many({})


async def _legacy_todo_waiting_on_a_reply(db: AsyncIOMotorDatabase[dict[str, Any]]) -> str:
    """Write a tracked todo as today's tools left it: waiting on a reply that unblocks it."""
    now = datetime.now(UTC)
    todo_id = ObjectId()
    await db["todos"].insert_one(
        {
            "_id": todo_id,
            "user_id": FAKE_USER.user_id,
            "title": TITLE,
            "description": "Wait for the landlord to confirm the deposit.",
            "labels": ["gaia-tracked", "waiting-for-reply"],
            "priority": "none",
            "completed": False,
            "subtasks": [],
            "waiting_on": "event",
            "scheduled_at": now + timedelta(days=3),
            "notify_on_run": True,
            "trigger_subscriptions": [
                {
                    "id": "sub-landlord",
                    "trigger_name": "gmail_new_message",
                    "conditions": [
                        {"field_name": "sender", "operator": "contains", "value": LANDLORD}
                    ],
                    "match": "all",
                    "action": "unblock",
                    "cooldown_seconds": 0,
                    "resolution": "account",
                    "composio_trigger_ids": [],
                    "trigger_data": {},
                    "status": "active",
                    "created_at": now,
                }
            ],
            "created_at": now,
            "updated_at": now,
        }
    )
    return str(todo_id)


async def _move_to_tasks(db: AsyncIOMotorDatabase[dict[str, Any]]) -> None:
    for name in MIGRATION_TARGETS:
        await db[name].delete_many({})
    report = await migrate(db, apply=True, user_ids=(FAKE_USER.user_id,))
    assert report.clean, report.summary()
    parity = await check_parity(db, user_ids=(FAKE_USER.user_id,))
    assert parity.clean, parity.summary()


async def _flags(db: AsyncIOMotorDatabase[dict[str, Any]], task_id: str) -> list[str]:
    task = await db["tasks"].find_one({"_id": task_id})
    assert task is not None, f"{task_id} did not move to tasks"
    return list(task["status_flags"])
