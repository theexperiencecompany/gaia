"""Journey: an account built on today's todos and workflows moves into tasks with nothing lost.

The account is made by driving the real system (routes, tools, worker jobs, OAuth connect),
not by writing documents by hand. The migration then runs on real Mongo, the parity checker
must come back clean, every kind of corruption must be caught, a second run must change
nothing, and a run killed midway must resume to the same end state.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch

from motor.motor_asyncio import AsyncIOMotorDatabase
import pytest
from scripts.seed_explore_workflows import create_workflow_document, get_all_workflows
from scripts.tasks_migration import migrate as migration
from scripts.tasks_migration.migrate import PROGRESS, migrate
from scripts.tasks_migration.parity import ParityReport, check_parity
from scripts.tasks_migration.transform import task_from_workflow

from app.constants.tasks import INBOX_DESK_SYSTEM_KEY
from app.constants.waits import WaitCondition
from app.db.repositories.todos import todo_repository
from app.models.agent_config import AgentConfigurableView
from app.models.task_models import TaskDocument
from app.models.workflow_models import (
    CreateWorkflowRequest,
    TriggerConfig,
    TriggerType,
    WorkflowStep,
)
from app.services.tasks.body_hash import task_body_hash
from app.services.wait_service import wait_for_user
from app.services.workflow.service import WorkflowService
from tests.conftest import FAKE_USER
from tests.e2e._harness.tasks_driver import TasksDriver
from tests.e2e._harness.tasks_views import (
    Asks,
    Finishes,
    NeedsApproval,
    NoReply,
    OpensReplyTask,
    OpensSubtasks,
    SavesPlaybook,
)

pytestmark = pytest.mark.e2e

USER = FAKE_USER.user_id
#: The owner of the curated templates the explore seed writes.
CURATOR = "650000000000000000000c01"
SCOPE = (USER, CURATOR)
TARGETS = ("tasks", "task_runs", "task_templates", "task_playbooks", PROGRESS)
SHARED = ("conversations", "approval_ledger", "waits")
DAILY_8AM = "0 8 * * *"
QUESTION = "Window or aisle for the Lisbon flight?"
ONLY_BILLING = "the email is about billing"


async def _generated_workflow(tasks: TasksDriver, title: str) -> str:
    """Give a to-do its generated workflow the way the generation worker does, steps supplied."""
    todo = await tasks.create_todo(title)
    workflow = await WorkflowService.create_workflow(
        CreateWorkflowRequest(
            title=f"Todo: {title}",
            description="Automated workflow to help complete the todo.",
            prompt=f"Complete the todo: {title}",
            trigger_config=TriggerConfig(type=TriggerType.MANUAL, enabled=True),
            steps=[WorkflowStep(title="Find options", category="search", description="Look it up")],
        ),
        USER,
        is_todo_workflow=True,
        source_todo_id=todo.id,
    )
    assert workflow.id is not None
    assert await todo_repository.link_workflow(todo.id, user_id=USER, workflow_id=workflow.id)
    return workflow.id


async def _seed_explore_row(db: AsyncIOMotorDatabase[dict[str, Any]]) -> str:
    """Write one curated card exactly as the explore seed script builds it."""
    row = create_workflow_document(get_all_workflows()[0], CURATOR)
    await db["workflows"].insert_one(row)
    return str(row["_id"])


async def _build_account(tasks: TasksDriver, db: AsyncIOMotorDatabase[dict[str, Any]]) -> None:
    """Drive today's system into an account with every kind of todo and workflow."""
    soon = datetime.now(UTC) + timedelta(days=2)
    groceries = await tasks.create_todo("Buy groceries", due=soon)
    groceries = await tasks.add_subtask(groceries.id, "Milk")
    groceries = await tasks.add_subtask(groceries.id, "Bread")
    await tasks.tick_subtask(groceries.id, groceries.subtasks[0].id)
    await tasks.create_todo("Pay rent", due=soon, repeat="0 9 1 * *")
    done = await tasks.create_todo("Return the library book")
    await tasks.complete(done.id)

    dentist = await tasks.hand_to_gaia("Find a dentist near the office")
    await wait_for_user(
        AgentConfigurableView(execution_mode="background", active_todo_id=dentist.id),
        USER,
        WaitCondition.INTEGRATION_CONNECTED,
        "notion",
        "Notion",
    )
    asked = await tasks.hand_to_gaia("Book the Lisbon flight")
    await tasks.run_due(asked.id, Asks(QUESTION, NoReply.HOLD))
    parent = await tasks.hand_to_gaia("Move flats on the 14th")
    await tasks.run_due(
        parent.id, OpensSubtasks(("Get mover quotes", "Book the van"), "Split the move.")
    )
    finished = await tasks.hand_to_gaia("Renew the car insurance")
    await tasks.run_due(finished.id, Finishes("Renewed the insurance."))
    await _generated_workflow(tasks, "Plan the offsite")

    await tasks.connect_app("gmail")
    watcher = await tasks.hand_to_gaia("Wait for the landlord's reply")
    await tasks.watch_emails_from(watcher.id, "landlord@example.com")
    desk = await tasks.inbox_desk()
    assert desk is not None
    await tasks.run_due(
        desk.id, OpensReplyTask("19a6c1f0d2e3b4a5", "Reply to Mads", "One thread needs you.")
    )

    briefing = await tasks.create_repeating_task(
        "Morning flowchart", "Every morning, draw the day's plan as a flowchart.", cron=DAILY_8AM
    )
    await tasks.run_due(briefing.id, SavesPlaybook("The plan is drawn."))
    await tasks.publish(briefing.id)
    billing = await tasks.create_event_task(
        "Billing replies",
        "Draft a reply to billing mail.",
        app_event="gmail_new_message",
        only_when=ONLY_BILLING,
    )
    await tasks.new_email(
        subject="50% off this weekend", sender="deals@shop.com", gate_passes=False, delivery_id="m1"
    )
    assert (await tasks.get_repeating(billing.id)).skipped_events
    paused = await tasks.create_repeating_task(
        "Weekly review", "Review my week.", cron="0 17 * * 5"
    )
    await tasks.pause(paused.id)
    await wait_for_user(
        AgentConfigurableView(conversation_id="chat-asking-for-a-trigger"),
        USER,
        WaitCondition.WORKFLOW_TRIGGER_CONFIGURED,
        paused.id,
        "Weekly review",
    )
    await tasks.connect_app("googlecalendar")
    await _seed_explore_row(db)

    await tasks.ask_before_acting()
    gated = await tasks.hand_to_gaia("Draw up the launch plan")
    await tasks.run_due(gated.id, NeedsApproval("Waiting on your approval."))


async def _forget_targets(db: AsyncIOMotorDatabase[dict[str, Any]]) -> None:
    for name in TARGETS:
        await db[name].delete_many({})
    for name in SHARED:
        await db[name].update_many(
            {"user_id": {"$in": list(SCOPE)}}, {"$unset": {"task_id": "", "owner_task_id": ""}}
        )
    await db["waits"].delete_many(
        {
            "user_id": {"$in": list(SCOPE)},
            "$or": [{"waiter": "task"}, {"condition": "task_trigger_configured"}],
        }
    )


@pytest.fixture
async def account(
    tasks: TasksDriver, mongo_db: AsyncIOMotorDatabase[dict[str, Any]]
) -> AsyncIterator[AsyncIOMotorDatabase[dict[str, Any]]]:
    """Yield the database holding the driven account, with nothing migrated yet."""
    await mongo_db["workflows"].delete_many({"user_id": CURATOR})
    await _forget_targets(mongo_db)
    await _build_account(tasks, mongo_db)
    yield mongo_db
    await _forget_targets(mongo_db)
    await mongo_db["workflows"].delete_many({"user_id": CURATOR})


async def _migrated(db: AsyncIOMotorDatabase[dict[str, Any]]) -> ParityReport:
    report = await migrate(db, apply=True, user_ids=SCOPE)
    assert report.clean, report.summary()
    parity = await check_parity(db, user_ids=SCOPE)
    assert parity.clean, parity.summary()
    return parity


#: Each target's business key; its Mongo _id is incidental where it is not the key.
_SNAPSHOT_KEYS = {
    "tasks": "_id",
    "task_templates": "_id",
    "task_runs": "run_id",
    "task_playbooks": "playbook_id",
}
_SHARED_FIELDS = {"task_id": 1, "owner_task_id": 1, "waiter": 1, "waiter_id": 1, "condition": 1}


async def _snapshot(db: AsyncIOMotorDatabase[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Every migrated document, and every field the migration adds to shared ones, in key order."""
    scope = {"user_id": {"$in": list(SCOPE)}}
    shot: dict[str, list[dict[str, Any]]] = {}
    for name, key in _SNAPSHOT_KEYS.items():
        projection = None if key == "_id" else {"_id": 0}
        filt = {} if name == "task_templates" else scope
        shot[name] = await db[name].find(filt, projection).sort(key, 1).to_list(None)
    for name in ("conversations", "approval_ledger"):
        shot[name] = await db[name].find(scope, _SHARED_FIELDS).sort("_id", 1).to_list(None)
    # A twin wait is a new document each time it is made, so it is compared by its key.
    shot["waits"] = (
        await db["waits"]
        .find(scope, {**_SHARED_FIELDS, "_id": 0, "subject_id": 1, "created_at": 1})
        .sort([("waiter", 1), ("waiter_id", 1), ("condition", 1)])
        .to_list(None)
    )
    return shot


class TestTheMigration:
    async def test_every_todo_and_workflow_becomes_a_task_and_the_checker_is_clean(
        self, account: AsyncIOMotorDatabase[dict[str, Any]]
    ) -> None:
        parity = await _migrated(account)

        tasks = {t["_id"]: t async for t in account["tasks"].find({"user_id": USER})}
        by_title = {t["title"]: t for t in tasks.values()}
        assert by_title["Buy groceries"]["assignee"] == "user"
        assert by_title["Pay rent"]["when"]["kind"] == "repeat"
        asked = by_title["Book the Lisbon flight"]
        assert asked["waiting"]["question"]["text"] == QUESTION
        assert asked["next_check_at"] is not None and asked["when"]["kind"] == "none"
        desk = by_title["Inbox desk"]
        assert (desk["system_key"], desk["source_integration"]) == (INBOX_DESK_SYSTEM_KEY, "gmail")
        reply = by_title["Reply to Mads"]
        assert reply["parent_id"] == desk["_id"]
        generated = by_title["Todo: Plan the offsite"]
        assert tasks[generated["parent_id"]]["title"] == "Plan the offsite"
        billing = by_title["Billing replies"]
        (subscription,) = billing["subscriptions"]
        assert subscription["gate"]["recent_skips"] and billing["when"]["kind"] == "event"
        assert by_title["Weekly review"]["active"] is False
        assert {t.get("system_key") for t in tasks.values()} >= {
            "calendar:meeting_prep",
            "calendar:meeting_reminder",
            INBOX_DESK_SYSTEM_KEY,
        }
        flowchart = by_title["Morning flowchart"]
        playbook = await account["task_playbooks"].find_one({"task_id": flowchart["_id"]})
        assert playbook is not None and playbook["body_hash"] == task_body_hash(flowchart["body"])
        assert (
            await account["task_templates"].count_documents({"source_task_id": flowchart["_id"]})
            == 1
        )
        assert await account["task_templates"].count_documents({"origin": "curated"}) == 1
        gated = by_title["Draw up the launch plan"]
        approval = await account["approval_ledger"].find_one({"owner_id": gated["_id"]})
        assert approval is not None and approval["owner_task_id"] == gated["_id"]
        imported = await account["task_runs"].count_documents(
            {
                "task_id": by_title["Renew the car insurance"]["_id"],
                "kind": "run",
                "status": "success",
            }
        )
        assert imported == 1
        assert parity.counts["chats_bound"] >= 4
        dentist = by_title["Find a dentist near the office"]["_id"]
        assert await account["waits"].count_documents({"waiter": "task", "waiter_id": dentist}) == 1
        assert await account["waits"].count_documents({"waiter": "todo", "waiter_id": dentist}) == 1
        assert (
            await account["waits"].count_documents(
                {
                    "condition": "task_trigger_configured",
                    "subject_id": by_title["Weekly review"]["_id"],
                }
            )
            == 1
        )

    async def test_a_second_run_changes_nothing(
        self, account: AsyncIOMotorDatabase[dict[str, Any]]
    ) -> None:
        await _migrated(account)
        first = await _snapshot(account)

        await _migrated(account)

        assert await _snapshot(account) == first

    async def test_a_run_killed_midway_resumes_to_the_same_end_state(
        self, account: AsyncIOMotorDatabase[dict[str, Any]]
    ) -> None:
        await _migrated(account)
        reference = await _snapshot(account)
        await _forget_targets(account)
        real = task_from_workflow
        calls = 0

        def dies_on_the_third(*args: Any, **kwargs: Any) -> TaskDocument:
            nonlocal calls
            calls += 1
            if calls == 3:
                raise ConnectionError("worker killed")
            return real(*args, **kwargs)

        with (
            patch.object(migration, "BATCH_SIZE", 1),
            patch.object(migration, "task_from_workflow", side_effect=dies_on_the_third),
            pytest.raises(ConnectionError),
        ):
            await migrate(account, apply=True, user_ids=SCOPE)
        todos_mark = await account[PROGRESS].find_one({"_id": "tasks_from_todos"})
        assert todos_mark is not None and todos_mark["done"] is True

        resumed = await migrate(account, apply=True, user_ids=SCOPE)

        assert resumed.clean, resumed.summary()
        assert "tasks_from_todos" not in {phase.value for phase in resumed.written}
        assert (await check_parity(account, user_ids=SCOPE)).clean
        assert await _snapshot(account) == reference


Corruption = Callable[
    [AsyncIOMotorDatabase[dict[str, Any]], dict[str, dict[str, Any]]], Awaitable[object]
]


def _set(title: str, fields: dict[str, Any]) -> Corruption:
    async def corrupt(
        db: AsyncIOMotorDatabase[dict[str, Any]], by_title: dict[str, dict[str, Any]]
    ) -> object:
        return await db["tasks"].update_one({"_id": by_title[title]["_id"]}, {"$set": fields})

    return corrupt


def _unset(title: str, field_name: str) -> Corruption:
    async def corrupt(
        db: AsyncIOMotorDatabase[dict[str, Any]], by_title: dict[str, dict[str, Any]]
    ) -> object:
        return await db["tasks"].update_one(
            {"_id": by_title[title]["_id"]}, {"$unset": {field_name: ""}}
        )

    return corrupt


async def _delete_task(
    db: AsyncIOMotorDatabase[dict[str, Any]], by_title: dict[str, dict[str, Any]]
) -> object:
    return await db["tasks"].delete_one({"_id": by_title["Buy groceries"]["_id"]})


async def _unbind_chat(
    db: AsyncIOMotorDatabase[dict[str, Any]], by_title: dict[str, dict[str, Any]]
) -> object:
    return await db["conversations"].update_one(
        {"task_id": by_title["Book the Lisbon flight"]["_id"]}, {"$unset": {"task_id": ""}}
    )


async def _stale_playbook(
    db: AsyncIOMotorDatabase[dict[str, Any]], by_title: dict[str, dict[str, Any]]
) -> object:
    return await db["task_playbooks"].update_one(
        {"task_id": by_title["Morning flowchart"]["_id"]}, {"$set": {"body_hash": "0" * 64}}
    )


async def _move_slug(
    db: AsyncIOMotorDatabase[dict[str, Any]], by_title: dict[str, dict[str, Any]]
) -> object:
    return await db["task_templates"].update_one(
        {"source_task_id": by_title["Morning flowchart"]["_id"]}, {"$set": {"slug": "elsewhere"}}
    )


async def _edit_history(
    db: AsyncIOMotorDatabase[dict[str, Any]], by_title: dict[str, dict[str, Any]]
) -> object:
    return await db["task_runs"].update_one(
        {"task_id": by_title["Renew the car insurance"]["_id"], "imported.seq": 0},
        {"$set": {"imported.text": "- nothing happened\n"}},
    )


async def _lose_execution(
    db: AsyncIOMotorDatabase[dict[str, Any]], by_title: dict[str, dict[str, Any]]
) -> object:
    return await db["task_runs"].delete_one(
        {"task_id": by_title["Morning flowchart"]["_id"], "imported": None}
    )


async def _lose_approval_owner(
    db: AsyncIOMotorDatabase[dict[str, Any]], by_title: dict[str, dict[str, Any]]
) -> object:
    return await db["approval_ledger"].update_one(
        {"owner_id": by_title["Draw up the launch plan"]["_id"]}, {"$unset": {"owner_task_id": ""}}
    )


async def _lose_wait_twin(
    db: AsyncIOMotorDatabase[dict[str, Any]], by_title: dict[str, dict[str, Any]]
) -> object:
    return await db["waits"].delete_one({"waiter": "task", "user_id": USER})


CORRUPTIONS: list[tuple[str, Corruption, str]] = [
    ("a renamed task", _set("Buy groceries", {"title": "Buy bread"}), "title"),
    (
        "an active schedule left unarmed",
        _unset("Morning flowchart", "when.next_run"),
        "when.next_run",
    ),
    (
        "a subscription that lost its trigger",
        _set("Billing replies", {"subscriptions.0.composio_trigger_ids": ["ti-other"]}),
        "subscription.composio_trigger_ids",
    ),
    ("a task that vanished", _delete_task, "_id"),
    (
        "a subtask under a missing parent",
        _set("Reply to Mads", {"parent_id": "wf_000000000000"}),
        "parent_id",
    ),
    ("a chat no longer bound", _unbind_chat, "task_id"),
    ("a playbook that stopped matching", _stale_playbook, "valid"),
    ("a public link that moved", _move_slug, "slug"),
    ("an edited history", _edit_history, "activity"),
    ("a lost run", _lose_execution, "run_id"),
    ("an approval that forgot its task", _lose_approval_owner, "owner_task_id"),
    (
        "a question rewritten",
        _set("Book the Lisbon flight", {"waiting.question.text": "Which seat?"}),
        "waiting.question.text",
    ),
    ("a stopped task switched on", _set("Weekly review", {"active": True}), "active"),
    ("a wait that lost its task twin", _lose_wait_twin, "twin"),
    (
        "a user label leaking back",
        _set("Buy groceries", {"status_flags": ["failed"]}),
        "status_flags",
    ),
]


class TestTheCheckerCatchesCorruption:
    async def test_every_kind_of_corruption_is_named_and_a_rerun_repairs_it(
        self, account: AsyncIOMotorDatabase[dict[str, Any]]
    ) -> None:
        await _migrated(account)
        by_title = {t["title"]: t async for t in account["tasks"].find({"user_id": USER})}

        for name, corrupt, field_name in CORRUPTIONS:
            await corrupt(account, by_title)
            found = await check_parity(account, user_ids=SCOPE)
            assert field_name in {diff.field for diff in found.diffs}, (name, found.summary())
            repaired = await migrate(account, apply=True, restart=True, user_ids=SCOPE)
            assert repaired.clean, repaired.summary()
            assert (await check_parity(account, user_ids=SCOPE)).clean, name
