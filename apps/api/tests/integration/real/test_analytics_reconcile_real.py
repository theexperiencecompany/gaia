"""Reconciliation's ground-truth side against a real Mongo: each aggregation counts exactly what its row claims."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

from pymongo import MongoClient
from pymongo.database import Database
import pytest
from scripts.analytics_ops.mongo import Document
from scripts.analytics_ops.reconcile import Window, mongo_signals

from app.constants.payments import SUBSCRIPTION_UNCHANGED_MESSAGE
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

    assert mongo_signals(db, WINDOW).messages_by_source == {"web+desktop": 2, "telegram": 1}


def test_web_and_desktop_are_one_bucket_since_neither_stores_a_source(
    db: Database[Document],
) -> None:
    db.conversations.insert_many(
        [
            {"messages": [_message("user", INSIDE)]},
            {"source": "web", "messages": [_message("user", INSIDE)]},
            {"source": "desktop", "messages": [_message("user", INSIDE)]},
        ]
    )

    assert mongo_signals(db, WINDOW).messages_by_source == {"web+desktop": 3}


def test_a_system_generated_conversations_user_turns_are_not_human(
    db: Database[Document],
) -> None:
    db.conversations.insert_many(
        [
            # A workflow run's conversation, stored without a source.
            {"is_system_generated": True, "messages": [_message("user", INSIDE)]},
            {"is_system_generated": False, "messages": [_message("user", INSIDE)]},
        ]
    )

    assert mongo_signals(db, WINDOW).messages_by_source == {"web+desktop": 1}


def test_the_linking_message_written_as_first_contact_is_not_a_submitted_turn(
    db: Database[Document],
) -> None:
    db.conversations.insert_one(
        {
            "source": "whatsapp",
            "messages": [
                {**_message("user", INSIDE), "first_contact": True},
                _message("bot", INSIDE),
                _message("user", INSIDE),
            ],
        }
    )

    assert mongo_signals(db, WINDOW).messages_by_source == {"whatsapp": 1}


def test_billing_counts_only_processed_deliveries_in_the_window(db: Database[Document]) -> None:
    db.processed_webhooks.insert_many(
        [
            {
                "webhook_id": "1",
                "payment_id": "pay_a",
                "event_type": "payment.succeeded",
                "status": "processed",
                "processed_at": INSIDE,
            },
            {
                "webhook_id": "2",
                "payment_id": "pay_b",
                "event_type": "payment.succeeded",
                "status": "processed",
                "processed_at": INSIDE,
            },
            {
                "webhook_id": "3",
                "payment_id": "pay_c",
                "event_type": "payment.succeeded",
                "status": "ignored",
                "processed_at": INSIDE,
            },
            {
                "webhook_id": "4",
                "subscription_id": "sub_a",
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


def _delivery(webhook_id: str, event_type: str, **ids: str) -> Document:
    return {
        "webhook_id": webhook_id,
        "event_type": event_type,
        "status": "processed",
        "processed_at": INSIDE,
        **ids,
    }


def test_billing_counts_each_state_change_once_not_each_delivery(db: Database[Document]) -> None:
    db.processed_webhooks.insert_many(
        [
            # A second activation report for the same subscription changes nothing.
            _delivery("a1", "subscription.active", subscription_id="sub_1"),
            _delivery("a2", "subscription.active", subscription_id="sub_1"),
            # The user's own cancel already fired the event; Dodo's report is the same change.
            _delivery("c1", "subscription.cancelled", subscription_id="sub_1"),
            # Two deliveries naming one payment are one payment.
            _delivery("p1", "payment.succeeded", payment_id="pay_1"),
            _delivery("p2", "payment.succeeded", payment_id="pay_1"),
            _delivery("p3", "payment.failed", payment_id="pay_2"),
            # Every renewal is its own change, even of the same subscription.
            _delivery("r1", "subscription.renewed", subscription_id="sub_1"),
            _delivery("r2", "subscription.renewed", subscription_id="sub_1"),
        ]
    )

    assert mongo_signals(db, WINDOW).billing == {
        "payment:succeeded": 1,
        "payment:failed": 1,
        "subscription:activated": 1,
        "subscription:renewed": 2,
        "subscription:cancelled": 1,
    }


def test_a_renewal_the_reducer_found_already_applied_is_not_a_renewal(
    db: Database[Document],
) -> None:
    db.processed_webhooks.insert_many(
        [
            _delivery("r1", "subscription.renewed", subscription_id="sub_1"),
            # Dodo's first-period renewal seconds after activation changes nothing and fires nothing.
            {
                **_delivery("r2", "subscription.renewed", subscription_id="sub_2"),
                "message": SUBSCRIPTION_UNCHANGED_MESSAGE,
            },
        ]
    )

    assert mongo_signals(db, WINDOW).billing["subscription:renewed"] == 1


def _subscription(dodo_id: str, *, cancel_scheduled: bool, last_event_at: datetime) -> Document:
    return {
        "dodo_subscription_id": dodo_id,
        "status": "active",
        "cancel_at_next_billing_date": cancel_scheduled,
        "last_event_at": last_event_at,
    }


def test_cancellations_count_in_app_and_webhook_cancels_once_per_subscription(
    db: Database[Document],
) -> None:
    db.processed_webhooks.insert_many(
        [
            _delivery("c1", "subscription.cancelled", subscription_id="sub_hook"),
            _delivery("c2", "subscription.cancelled", subscription_id="sub_both"),
        ]
    )
    db.subscriptions.insert_many(
        [
            # An in-app cancel gets no Dodo webhook: only the row's flag and event time record it.
            _subscription("sub_both", cancel_scheduled=True, last_event_at=INSIDE),
            _subscription("sub_app", cancel_scheduled=True, last_event_at=INSIDE),
            _subscription("sub_old", cancel_scheduled=True, last_event_at=BEFORE),
            _subscription("sub_renewing", cancel_scheduled=False, last_event_at=INSIDE),
        ]
    )

    assert mongo_signals(db, WINDOW).billing["subscription:cancelled"] == 3
