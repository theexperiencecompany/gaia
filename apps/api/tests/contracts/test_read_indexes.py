"""Per-user read paths against real Mongo: each one is served by an index built for it.

The plans are read from the server's profiler while the real repository finder runs
against indexes built by the real startup creators, so a finder whose filter or sort
drifts from its index fails here instead of scanning a whole collection in production.
Every collection is seeded with other users' rows, so a plan that does not lead with the
user's own key has real work to lose to.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.constants.hil import TOOL_READ_ONLY_VERDICT_TTL
from app.constants.user_activity import ActivityStatus
from app.db.mongodb import indexes
from app.db.repositories.approval_ledger import ApprovalLedgerRepository
from app.db.repositories.conversations import ConversationRepository
from app.db.repositories.hil import HilApprovalRepository, ToolReadOnlyVerdictRepository
from app.db.repositories.todos import TodosRepository
from app.db.repositories.users import UserRepository
from app.models.todo_models import ExternalRefSource
from tests.contracts.conftest import QueryPlans

USER_ID = "user-reading"
_NOW = datetime(2026, 11, 18, 6, 0, tzinfo=UTC)
_NOISE = 60


@pytest.fixture(autouse=True)
def _indexes_on_the_fixture(raw_collection, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(indexes, "get_async_collection", lambda name: raw_collection)


def _served_by(plans: list[str], *keys: str) -> bool:
    return bool(plans) and all(keys and all(key in plan for key in keys) for plan in plans)


@pytest.mark.regression
async def test_pending_ledger_approvals_are_read_by_user_state_and_age(
    raw_collection, query_plans: QueryPlans
) -> None:
    await indexes.create_approval_ledger_indexes()
    await raw_collection.insert_many(
        [
            {
                "approval_id": f"a{i}",
                "conversation_id": f"c{i}",
                "fingerprint": f"f{i}",
                "user_id": f"other-{i}",
                "state": "pending",
                "created_at": _NOW,
            }
            for i in range(_NOISE)
        ]
    )

    plans = await query_plans(ApprovalLedgerRepository().list_pending_for_user(USER_ID))

    assert _served_by(plans, "IXSCAN { user_id: 1, state: 1, created_at: 1 }"), plans


@pytest.mark.regression
async def test_pending_hil_approvals_are_read_by_user_status_and_age(
    raw_collection, query_plans: QueryPlans
) -> None:
    await indexes.create_hil_approvals_indexes()
    await raw_collection.insert_many(
        [
            {
                "user_id": f"other-{i}",
                "status": "pending",
                "expires_at": _NOW + timedelta(hours=1),
                "created_at": _NOW,
            }
            for i in range(_NOISE)
        ]
    )

    plans = await query_plans(HilApprovalRepository().list_pending_for_user(USER_ID, _NOW))

    assert _served_by(plans, "IXSCAN { user_id: 1, status: 1, created_at: 1 }"), plans


@pytest.mark.regression
async def test_todos_completed_since_are_read_by_user_completion_and_time(
    raw_collection, query_plans: QueryPlans
) -> None:
    await indexes.create_todo_indexes()
    await raw_collection.insert_many(
        [
            {
                "user_id": USER_ID,
                "completed": i % 2 == 0,
                "completed_at": _NOW - timedelta(days=i),
                "created_at": _NOW - timedelta(days=i),
            }
            for i in range(_NOISE)
        ]
    )

    plans = await query_plans(
        TodosRepository().list_completed_since(USER_ID, since=_NOW + timedelta(days=1))
    )

    assert _served_by(plans, "IXSCAN { user_id: 1, completed: 1, completed_at: 1 }"), plans


@pytest.mark.regression
async def test_external_ref_activity_is_read_by_user_source_and_each_time(
    raw_collection, query_plans: QueryPlans
) -> None:
    await indexes.create_todo_indexes()
    await raw_collection.insert_many(
        [
            {
                "user_id": USER_ID,
                "external_ref": {"source": ExternalRefSource.GMAIL_THREAD.value, "id": f"t{i}"},
                "completed": False,
                "created_at": _NOW - timedelta(days=i),
            }
            for i in range(_NOISE)
        ]
    )

    plans = await query_plans(
        TodosRepository().list_external_ref_activity_since(
            USER_ID, ExternalRefSource.GMAIL_THREAD, since=_NOW + timedelta(days=1)
        )
    )

    assert _served_by(
        plans,
        "IXSCAN { user_id: 1, external_ref.source: 1, created_at: 1 }",
        "IXSCAN { user_id: 1, external_ref.source: 1, completed_at: 1 }",
    ), plans


@pytest.mark.regression
async def test_bot_replies_read_only_conversations_active_since(
    raw_collection, query_plans: QueryPlans
) -> None:
    await indexes.create_conversation_indexes()
    stale = _NOW - timedelta(days=30)
    await raw_collection.insert_many(
        [
            {
                "conversation_id": f"c{i}",
                "user_id": USER_ID,
                "source": "telegram",
                "createdAt": stale.isoformat(),
                "updatedAt": stale,
                "messages": [
                    {"type": "user", "response": "hi", "date": stale.isoformat()} for _ in range(20)
                ],
            }
            for i in range(_NOISE)
        ]
    )

    plans = await query_plans(
        ConversationRepository().list_bot_replies_since(USER_ID, _NOW, limit=10)
    )

    assert _served_by(plans, "IXSCAN { user_id: 1, updatedAt: -1 }"), plans


@pytest.mark.regression
async def test_users_by_activity_status_never_scan_the_collection(
    raw_collection, query_plans: QueryPlans
) -> None:
    await indexes.create_user_indexes()
    await raw_collection.insert_many(
        [
            {"email": f"u{i}@example.com", "created_at": _NOW, "last_active_at": _NOW}
            for i in range(_NOISE)
        ]
        + [{"email": "never@example.com", "created_at": _NOW - timedelta(days=400)}]
    )

    plans = await query_plans(UserRepository().find_activity_rows(ActivityStatus.DORMANT))

    assert plans
    assert not any("COLLSCAN" in plan for plan in plans), plans


@pytest.mark.regression
async def test_a_read_only_verdict_is_read_by_tool_shape_and_classifier(
    raw_collection, query_plans: QueryPlans
) -> None:
    await raw_collection.create_index([("tool_hash", 1)], unique=True)
    await indexes.create_tool_read_only_verdict_indexes()
    await raw_collection.insert_many(
        [
            {"tool_hash": "shape", "classifier": f"judge-{i}", "tool_name": "t", "read_only": True}
            for i in range(_NOISE)
        ]
    )

    plans = await query_plans(ToolReadOnlyVerdictRepository().find_verdict("shape", "judge-7"))

    assert _served_by(plans, "IXSCAN { tool_hash: 1, classifier: 1 }"), plans
    ttl = {i["name"]: i.get("expireAfterSeconds") async for i in raw_collection.list_indexes()}
    assert ttl["classified_at_ttl"] == TOOL_READ_ONLY_VERDICT_TTL.total_seconds()
