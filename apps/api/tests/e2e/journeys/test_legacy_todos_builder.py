"""The migration journey's legacy builder writes exactly what the old todos engine wrote.

legacy_snapshot.json is the old engine's own output for these steps, normalized. While the
old engine exists, the first test drives it and must still produce the snapshot
(RECORD_LEGACY_SNAPSHOT=1 rewrites the file instead); the second builds the same steps by
hand and must produce it too, so the migration keeps being proven on real legacy shapes.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase
import pytest

from app.agents.tools.tracked_todo_tools import create_tracked_todo
from tests.conftest import FAKE_USER
from tests.e2e._harness.legacy_todos import LegacyTodos, normalized_legacy
from tests.e2e._harness.tasks_driver import GATED_ACTION, GATED_ACTION_ARGS, TasksDriver
from tests.e2e._harness.tasks_views import (
    Asks,
    Finishes,
    NeedsApproval,
    NoReply,
    OpensReplyTask,
    OpensSubtasks,
)

pytestmark = pytest.mark.e2e

USER = FAKE_USER.user_id
SNAPSHOT = Path(__file__).resolve().parents[1] / "_harness" / "legacy_snapshot.json"
QUESTION = "Window or aisle for the Lisbon flight?"
SPLIT = ("Get mover quotes", "Book the van")
THREAD = "19a6c1f0d2e3b4a5"
#: The summary the approval card gave the gated action.
GATED_SUMMARY = "Create flowchart"


def _recorded() -> dict[str, Any]:
    return json.loads(SNAPSHOT.read_text())["documents"]


async def _old_tracked_todo(db: AsyncIOMotorDatabase[dict[str, Any]], title: str) -> str:
    """Hand GAIA a one-off through the old tracked-todo tool, as chat did; returns its id."""
    said = await create_tracked_todo.ainvoke(
        {"title": title, "waiting_on": "time", "scheduled_at": "1h", "notify_on_run": True},
        config={"configurable": {"user_id": USER}},
    )
    row = await db["todos"].find_one({"user_id": USER, "title": title, "labels": "gaia-tracked"})
    assert row is not None, f"GAIA did not take the task on: {said}"
    return str(row["_id"])


class TestTheLegacyBuilder:
    async def test_the_old_engine_wrote_the_recorded_documents(
        self, tasks: TasksDriver, mongo_db: AsyncIOMotorDatabase[dict[str, Any]]
    ) -> None:
        await _old_tracked_todo(mongo_db, "Find a dentist near the office")
        asked = await _old_tracked_todo(mongo_db, "Book the Lisbon flight")
        await tasks.run_due(asked, Asks(QUESTION, NoReply.HOLD))
        parent = await _old_tracked_todo(mongo_db, "Move flats on the 14th")
        await tasks.run_due(parent, OpensSubtasks(SPLIT, "Split the move."))
        finished = await _old_tracked_todo(mongo_db, "Renew the car insurance")
        await tasks.run_due(finished, Finishes("Renewed the insurance."))
        await tasks.connect_app("gmail")
        watcher = await _old_tracked_todo(mongo_db, "Wait for the landlord's reply")
        await tasks.watch_emails_from(watcher, "landlord@example.com")
        desk = await tasks.inbox_desk()
        assert desk is not None
        await tasks.run_due(
            desk.id, OpensReplyTask(THREAD, "Reply to Mads", "One thread needs you.")
        )
        await tasks.ask_before_acting()
        gated = await _old_tracked_todo(mongo_db, "Draw up the launch plan")
        await tasks.run_due(gated, NeedsApproval("Waiting on your approval."))

        written = await normalized_legacy(mongo_db, USER)

        if os.environ.get("RECORD_LEGACY_SNAPSHOT") == "1":
            SNAPSHOT.write_text(
                json.dumps(
                    {
                        "recorded_from": "the old todos engine at 9380571eba, by this test",
                        "documents": written,
                    },
                    indent=1,
                    sort_keys=True,
                )
                + "\n"
            )
        assert written == _recorded()

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

        assert await normalized_legacy(mongo_db, USER) == _recorded()
