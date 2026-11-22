"""The migration journey's legacy builder writes exactly what the old todos engine wrote.

legacy_snapshot.json is the old engine's own output for these steps, normalized, recorded
by this file's recorder test at e2b62755dd while the tracked-todo tools, the old Inbox desk
and their engine still ran (RECORD_LEGACY_SNAPSHOT=1 rewrote it). The builder must keep
producing it, so the migration stays proven on real legacy shapes once that code is gone.
A desk the user stopped is held to the old todos API, which still writes it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase
import pytest

from tests.conftest import FAKE_USER, FAKE_USER_2
from tests.e2e._harness.legacy_todos import LegacyTodos, normalized_legacy
from tests.e2e._harness.tasks_driver import GATED_ACTION, GATED_ACTION_ARGS, TasksDriver
from tests.e2e._harness.tasks_views import NoReply

pytestmark = pytest.mark.e2e

USER = FAKE_USER.user_id
SNAPSHOT = Path(__file__).resolve().parents[1] / "_harness" / "legacy_snapshot.json"
QUESTION = "Window or aisle for the Lisbon flight?"
SPLIT = ("Get mover quotes", "Book the van")
THREAD = "19a6c1f0d2e3b4a5"
#: The summary the approval card gave the gated action.
GATED_SUMMARY = "Create flowchart"


class TestTheLegacyBuilder:
    @pytest.mark.usefixtures("_clean_user")
    async def test_the_builder_writes_what_the_old_engine_wrote(
        self, mongo_db: AsyncIOMotorDatabase[dict[str, Any]]
    ) -> None:
        legacy = LegacyTodos(mongo_db, USER)
        await legacy.tracked_todo("Find a dentist near the office")
        asked = await legacy.tracked_todo("Book the Lisbon flight")
        await legacy.asked(asked, QUESTION, NoReply.HOLD.value)
        parent = await legacy.tracked_todo("Move flats on the 14th")
        await legacy.split(parent, SPLIT, "Split the move.")
        finished = await legacy.tracked_todo("Renew the car insurance")
        await legacy.finished(finished, "Renewed the insurance.")
        watcher = await legacy.tracked_todo("Wait for the landlord's reply")
        await legacy.watches_emails_from(watcher, "landlord@example.com")
        desk = await legacy.inbox_desk()
        await legacy.desk_opened_reply_task(
            desk,
            THREAD,
            "Reply to Mads",
            account_id="acct_0123456789abcdef",
            report="One thread needs you.",
        )
        gated = await legacy.tracked_todo("Draw up the launch plan")
        await legacy.parked_on_approval(
            gated, tool_name=GATED_ACTION, summary=GATED_SUMMARY, args=GATED_ACTION_ARGS
        )

        recorded = json.loads(SNAPSHOT.read_text())["documents"]
        assert await normalized_legacy(mongo_db, USER) == recorded

    async def test_a_desk_the_user_stopped_is_what_the_old_todos_api_left(
        self, tasks: TasksDriver, mongo_db: AsyncIOMotorDatabase[dict[str, Any]]
    ) -> None:
        stopped_in_the_app = await LegacyTodos(mongo_db, USER).inbox_desk()
        await tasks.complete(stopped_in_the_app)
        built = LegacyTodos(mongo_db, FAKE_USER_2.user_id)
        await built.completed_by_the_user(await built.inbox_desk())

        mine = await normalized_legacy(mongo_db, USER)
        theirs = await normalized_legacy(mongo_db, FAKE_USER_2.user_id)
        assert mine["todos"] == theirs["todos"]
