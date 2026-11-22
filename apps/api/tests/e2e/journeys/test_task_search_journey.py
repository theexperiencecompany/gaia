"""Journey: GAIA finds the user's tasks by what they are about, kept true as tasks change.

The index runs on a real in-process Chroma with an embedding that knows a few meanings
(tests/e2e/_harness/task_index.py): "dentist" lands near "toothache", never near "passport".
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase
import pytest
from scripts.tasks_migration.migrate import migrate
from scripts.tasks_migration.search_index import check_index, reindex

from app.services.tasks import search_index
from tests.conftest import FAKE_USER, FAKE_USER_2
from tests.e2e._harness.tasks_driver import TasksDriver

pytestmark = pytest.mark.e2e

USER = FAKE_USER.user_id
SCOPE = (USER, FAKE_USER_2.user_id)


async def _coverage(db: AsyncIOMotorDatabase[dict[str, Any]]) -> list[str]:
    report = await check_index(db, await search_index.task_index(), user_ids=SCOPE)
    return [diff.line() for diff in report.diffs]


class TestFindingATaskByMeaning:
    async def test_a_task_is_found_by_what_it_is_about_not_its_words(
        self, tasks: TasksDriver
    ) -> None:
        checkup = await tasks.create_todo("Book a check-up")
        await tasks.gaia_uses("update_task", task_id=checkup.id, body="The toothache on the left.")
        passport = await tasks.create_todo("Renew the passport")
        await tasks.create_todo("Pay the gas bill")

        assert (await tasks.search("dentist appointment"))[0] == checkup.id
        assert (await tasks.search("visa for the trip"))[0] == passport.id

    async def test_gaia_finds_what_its_own_notes_already_know(self, tasks: TasksDriver) -> None:
        move = await tasks.hand_to_gaia("Sort out the flat move")
        await tasks.hand_to_gaia("Find a dentist")
        await tasks.gaia_uses(
            "update_task",
            task_id=move.id,
            notes="# Sort out the flat move\n\n## Key Details\n- Landlord Mads owes the deposit "
            "refund; it comes back by bank transfer.\n",
        )

        said = await tasks.gaia_uses("search_tasks", query="money owed to me", assignee="gaia")

        assert said.index(f"(id {move.id})") < said.index("Find a dentist")
        assert "Landlord Mads" in said


class TestTheIndexFollowsTheTasks:
    async def test_an_edited_task_is_found_by_its_new_text_and_not_its_old(
        self, tasks: TasksDriver
    ) -> None:
        errand = await tasks.create_todo("An errand")
        await tasks.gaia_uses("update_task", task_id=errand.id, body="Water the plants")
        bins = await tasks.create_todo("Take the bins out")
        assert (await tasks.search("watering plants"))[0] == errand.id

        await tasks.gaia_uses("update_task", task_id=errand.id, body="Buy mum a birthday present")

        assert (await tasks.search("a gift for the party"))[0] == errand.id
        assert (await tasks.search("watering plants"))[0] == bins.id

    async def test_a_finished_task_is_found_only_among_finished_ones_until_reopened(
        self, tasks: TasksDriver
    ) -> None:
        passport = await tasks.create_todo("Renew the passport")
        await tasks.create_todo("Pay the gas bill")

        await tasks.complete(passport.id)
        assert passport.id not in await tasks.search("visa for the trip", include_done=False)
        assert (await tasks.search("visa for the trip"))[0] == passport.id
        await tasks.reopen(passport.id)

        assert (await tasks.search("visa for the trip", include_done=False))[0] == passport.id

    async def test_a_deleted_task_leaves_the_index(
        self, tasks: TasksDriver, mongo_db: AsyncIOMotorDatabase[dict[str, Any]]
    ) -> None:
        passport = await tasks.create_todo("Renew the passport")
        await tasks.create_todo("Pay the gas bill")

        await tasks.delete(passport.id)

        assert passport.id not in await tasks.search("visa for the trip")
        assert await _coverage(mongo_db) == []

    async def test_another_users_task_is_never_found(self, tasks: TasksDriver) -> None:
        mine = await tasks.create_todo("Renew the passport")
        theirs = await tasks.someone_elses_todo("Dentist for the kids", body="toothache")

        found = await search_index.search_tasks(USER, "dentist toothache")

        assert [m.task_id for m in found] == [mine.id]
        assert theirs not in await tasks.search("dentist toothache")


class TestMigratedTasksAreIndexed:
    async def test_the_checker_counts_them_missing_until_the_reindex_fills_them(
        self, tasks: TasksDriver, mongo_db: AsyncIOMotorDatabase[dict[str, Any]]
    ) -> None:
        old_id = ObjectId()
        now = datetime.now(UTC)
        await mongo_db["todos"].insert_one(
            {
                "_id": old_id,
                "user_id": USER,
                "title": "Ring the embassy",
                "description": "About the visa for the Lisbon trip",
                "labels": [],
                "priority": "none",
                "completed": False,
                "subtasks": [],
                "notify_on_run": True,
                "created_at": now,
                "updated_at": now,
            }
        )
        await tasks.create_todo("Pay the gas bill")
        assert (await migrate(mongo_db, apply=True, restart=True, user_ids=[USER])).clean

        assert await _coverage(mongo_db) == [
            f"tasks_index/{old_id} entry: expected 'indexed', found 'missing'"
        ]
        report = await reindex(mongo_db, await search_index.task_index(), user_ids=SCOPE)

        assert report.indexed == 2
        assert await _coverage(mongo_db) == []
        assert (await tasks.search("flights abroad"))[0] == str(old_id)
