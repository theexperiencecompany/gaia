"""The notification details expand and contract migrations over real Mongo: free-form metadata becomes typed details."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
import uuid

from motor.motor_asyncio import AsyncIOMotorCollection
import pytest

from app.constants.notifications import NotificationKind
from app.db.repositories.notifications import notification_repository
from app.models.notification.details_models import (
    TodoNotification,
    WorkflowPausedNotification,
)
from scripts import migrate_notification_details as migration

pytestmark = pytest.mark.service

USER = "user-1"
_CARD = {
    "briefing_id": "brief-1",
    "date": "2026-11-18",
    "kind": "daily",
    "headline": "Three things today",
    "edition": {"image_url": "https://cdn.test/e.png", "fold": None, "paper": None},
    "edition_name": "Swiss",
    "stamp_city_name": None,
    "needs_you_count": 1,
}
#: What each producer of the previous release stored, by the notification's id.
_STORED_METADATA: dict[str, tuple[str, dict[str, object]]] = {
    "agent": ("ai_agent", {}),
    "todo": ("background_job", {"todo_id": "todo-1"}),
    "todo_failed": ("background_job", {"todo_id": "todo-1", "retry_count": 3}),
    "trigger": ("todo_trigger", {"todo_id": "todo-1", "subscription_id": "sub-1"}),
    "dormant": ("background_job", {"todo_count": 2}),
    "reminder": ("ai_reminder", {"reminder_id": "rem-1", "created_at": "2026-11-18T08:00:00"}),
    "memory": ("background_job", {"source": "memory_backfill"}),
    "gmail": ("background_job", {"source": "gmail_personalization"}),
    "wf_done": ("workflow_completed", {"workflow_id": "wf-1", "conversation_id": "conv-1"}),
    "wf_failed": ("workflow_failed", {"workflow_id": "wf-1", "error_type": "RuntimeError"}),
    "wf_failed_bare": ("workflow_failed", {"workflow_id": "wf-1"}),
    "wf_paused": (
        "integration_expired",
        {"workflow_id": "wf-1", "missing_integrations": "gmail,notion"},
    ),
    "expired": ("integration_expired", {"integration_id": "gmail", "paused_workflows": 1}),
    "provisioned": ("system_workflows_provisioned", {"integration_display_name": "Gmail"}),
    "brief": (
        "background_job",
        {"kind": "briefing_daily", "brief_url": "https://heygaia.link/b", "card": _CARD},
    ),
    "note": ("background_job", {"kind": "briefing_note"}),
    # Retired producers' shapes: no current kind describes them.
    "old_brief": (
        "background_job",
        {"kind": "briefing_daily", "briefing_id": "brief-0", "brief_url": "https://x"},
    ),
    "old_draft": ("ai_email_draft", {"draft_id": "d-1", "email_subject": "Hi"}),
    "bare_workflow_completion": ("workflow_completed", {"workflow_id": "wf-1"}),
}
_EXPECTED_DETAILS: dict[str, dict[str, object] | None] = {
    "agent": None,
    "todo": {"kind": "todo", "todo_id": "todo-1"},
    "todo_failed": {"kind": "todo_failed", "todo_id": "todo-1", "retry_count": 3},
    "trigger": {"kind": "todo_trigger_fired", "todo_id": "todo-1", "subscription_id": "sub-1"},
    "dormant": {"kind": "dormant_todos", "todo_count": 2},
    "reminder": {"kind": "reminder", "reminder_id": "rem-1"},
    "memory": {"kind": "memory_ready"},
    "gmail": {"kind": "gmail_personalized"},
    "wf_done": {"kind": "workflow_completed", "workflow_id": "wf-1", "conversation_id": "conv-1"},
    "wf_failed": {"kind": "workflow_failed", "workflow_id": "wf-1", "error_type": "RuntimeError"},
    "wf_failed_bare": {"kind": "workflow_failed", "workflow_id": "wf-1", "error_type": None},
    "wf_paused": {
        "kind": "workflow_paused",
        "workflow_id": "wf-1",
        "missing_integrations": ["gmail", "notion"],
    },
    "expired": {"kind": "integration_expired", "integration_id": "gmail", "paused_workflows": 1},
    "provisioned": {
        "kind": "system_workflows_provisioned",
        "integration_display_name": "Gmail",
    },
    "brief": {"kind": "briefing_daily", "brief_url": "https://heygaia.link/b", "card": _CARD},
    "note": {"kind": "briefing_note"},
    "old_brief": None,
    "old_draft": None,
    "bare_workflow_completion": None,
}


@pytest.fixture
async def notifications(
    mongo_db, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[AsyncIOMotorCollection]:
    """Point the migration and the notification repository at a fresh notifications collection."""
    collection = mongo_db[f"notifications_details_migration_{uuid.uuid4().hex}"]
    monkeypatch.setattr(migration, "notifications_collection", collection)
    monkeypatch.setattr("app.db.repositories.base.get_async_collection", lambda _name: collection)
    yield collection
    await collection.drop()


def _stored(notification_id: str, source: str, metadata: dict[str, object]) -> dict[str, object]:
    """Return a notification document as the previous release stored it."""
    now = datetime.now(UTC)
    return {
        "id": notification_id,
        "user_id": USER,
        "status": "delivered",
        "created_at": now,
        "channels": [],
        "original_request": {
            "id": notification_id,
            "user_id": USER,
            "source": source,
            "type": "info",
            "priority": 3,
            "channels": [],
            "content": {"title": "t", "body": "b", "actions": None, "rich_content": None},
            "metadata": metadata,
            "created_at": now,
        },
    }


async def _seed(notifications: AsyncIOMotorCollection) -> None:
    await notifications.insert_many(
        [_stored(nid, source, meta) for nid, (source, meta) in _STORED_METADATA.items()]
    )


async def _details_by_id(notifications: AsyncIOMotorCollection) -> dict[str, object]:
    return {
        doc["id"]: doc["original_request"].get("details", "<missing>")
        async for doc in notifications.find({})
    }


async def test_a_dry_run_counts_and_writes_nothing(notifications: AsyncIOMotorCollection) -> None:
    await _seed(notifications)
    before = [doc async for doc in notifications.find({})]

    assert await migration.migrate(apply=False) == len(_STORED_METADATA)

    assert [doc async for doc in notifications.find({})] == before


async def test_apply_stores_each_producers_details_and_keeps_the_metadata(
    notifications: AsyncIOMotorCollection,
) -> None:
    await _seed(notifications)

    assert await migration.migrate(apply=True) == len(_STORED_METADATA)

    assert await _details_by_id(notifications) == _EXPECTED_DETAILS
    assert await notifications.count_documents(
        {"original_request.metadata": {"$exists": True}}
    ) == (len(_STORED_METADATA))
    records = {
        record.id: record.original_request.details
        for record in await notification_repository.list_for_user(USER)
    }
    assert records["todo"] == TodoNotification(kind=NotificationKind.TODO, todo_id="todo-1")
    assert records["wf_paused"] == WorkflowPausedNotification(
        kind=NotificationKind.WORKFLOW_PAUSED,
        workflow_id="wf-1",
        missing_integrations=["gmail", "notion"],
    )
    assert records["old_draft"] is None


async def test_a_second_apply_finds_nothing_to_move(notifications: AsyncIOMotorCollection) -> None:
    await _seed(notifications)
    await migration.migrate(apply=True)
    after_first = [doc async for doc in notifications.find({})]

    assert await migration.migrate(apply=True) == 0

    assert [doc async for doc in notifications.find({})] == after_first


async def test_contract_derives_what_the_previous_release_wrote_since_then_drops_metadata(
    notifications: AsyncIOMotorCollection,
) -> None:
    await _seed(notifications)
    await migration.migrate(apply=True)
    await notifications.insert_one(_stored("late", "background_job", {"todo_id": "todo-9"}))
    carrying = {"original_request.metadata": {"$exists": True}}

    assert await migration.contract(apply=False) == len(_STORED_METADATA) + 1
    assert await notifications.count_documents(carrying) == len(_STORED_METADATA) + 1

    assert await migration.contract(apply=True) == len(_STORED_METADATA) + 1

    assert await notifications.count_documents(carrying) == 0
    late = await notification_repository.get_for_user("late", USER)
    assert late is not None
    assert late.original_request.details == TodoNotification(
        kind=NotificationKind.TODO, todo_id="todo-9"
    )
    assert await migration.contract(apply=True) == 0
