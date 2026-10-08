"""Reconciliation's ground-truth side against a real Mongo: each aggregation counts exactly what its row claims."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

from pymongo import MongoClient
from pymongo.database import Database
import pytest
from scripts.analytics_ops.mongo import Document
from scripts.analytics_ops.reconcile import Window, mongo_signals

from tests.helpers import worker_mongo_db_name

WINDOW = Window(datetime(2026, 9, 8, tzinfo=UTC), datetime(2026, 10, 8, tzinfo=UTC))
INSIDE = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)
BEFORE = datetime(2026, 9, 7, 23, 59, tzinfo=UTC)
COLLECTIONS = (
    "users",
    "conversations",
    "subscriptions",
    "processed_webhooks",
    "support_requests",
    "llm_calls",
)


@pytest.fixture
def db(mongodb_url: str) -> Iterator[Database[Document]]:
    client: MongoClient[Document] = MongoClient(
        mongodb_url, tz_aware=True, serverSelectionTimeoutMS=5000
    )
    database = client[worker_mongo_db_name()]
    for name in COLLECTIONS:
        database[name].delete_many({})
    yield database
    for name in COLLECTIONS:
        database[name].delete_many({})
    client.close()


def _message(kind: str, when: datetime) -> Document:
    return {"type": kind, "date": when.isoformat(), "response": "x"}


def test_messages_count_user_turns_by_their_own_date_per_source(db: Database[Document]) -> None:
    db.conversations.insert_many(
        [
            # An old conversation: only the turn inside the window counts.
            {
                "source": "web",
                "messages": [
                    _message("user", BEFORE),
                    _message("user", INSIDE),
                    _message("bot", INSIDE),
                ],
            },
            {"source": "telegram", "messages": [_message("user", INSIDE)]},
            # Before conversations carried a source, every one was a web conversation.
            {"messages": [_message("user", INSIDE)]},
            # The agent's own runs are not human messages.
            {"source": "workflow_system", "messages": [_message("user", INSIDE)]},
            {"source": "background", "messages": [_message("user", INSIDE)]},
        ]
    )

    assert mongo_signals(db, WINDOW).messages_by_source == {"web": 2, "telegram": 1}


def test_billing_counts_only_processed_deliveries_in_the_window(db: Database[Document]) -> None:
    db.processed_webhooks.insert_many(
        [
            {
                "webhook_id": "1",
                "event_type": "payment.succeeded",
                "status": "processed",
                "processed_at": INSIDE,
            },
            {
                "webhook_id": "2",
                "event_type": "payment.succeeded",
                "status": "processed",
                "processed_at": INSIDE,
            },
            {
                "webhook_id": "3",
                "event_type": "payment.succeeded",
                "status": "ignored",
                "processed_at": INSIDE,
            },
            {
                "webhook_id": "4",
                "event_type": "subscription.active",
                "status": "processed",
                "processed_at": BEFORE,
            },
        ]
    )

    billing = mongo_signals(db, WINDOW).billing

    assert (billing["payment:succeeded"], billing["subscription:activated"]) == (2, 0)


def test_signups_support_subscriptions_and_cost_count_by_created_at(db: Database[Document]) -> None:
    db.users.insert_many([{"created_at": INSIDE}, {"created_at": BEFORE}])
    db.support_requests.insert_many([{"created_at": INSIDE}])
    db.subscriptions.insert_many(
        [
            {"user_id": "a", "status": "active", "created_at": INSIDE},
            {
                "user_id": "b",
                "status": "active",
                "recurring_pre_tax_amount": 0,
                "created_at": BEFORE,
            },
            {"user_id": "c", "status": "expired", "created_at": INSIDE},
        ]
    )
    db.llm_calls.insert_many(
        [
            {"cost_usd": 0.25, "created_at": INSIDE},
            {"cost_usd": 0.5, "created_at": INSIDE},
            {"cost_usd": 9.0, "created_at": BEFORE},
        ]
    )

    signals = mongo_signals(db, WINDOW)

    assert (signals.signups, signals.support_requests, signals.subscriptions_started) == (1, 1, 2)
    assert signals.llm_cost_usd == pytest.approx(0.75)
    # Active now, whenever it started, and a $0 discount-code subscription counts.
    assert signals.subscribers_now == 2
