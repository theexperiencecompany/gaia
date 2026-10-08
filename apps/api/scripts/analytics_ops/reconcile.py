"""Print PostHog next to its ground truth for every signal the dashboards report, and fail on drift.

Ground truth is Mongo: users, conversations, processed_webhooks (Dodo's own
deliveries, kept 30 days), subscriptions, support_requests and the llm_calls
ledger. PostHog is read unfiltered, so both sides include test accounts.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from pymongo.database import Database

from app.constants.chat import ConversationSource
from app.models.payment_models import SubscriptionStatus
from app.models.webhook_models import DodoWebhookEventType, WebhookProcessingStatus
from shared.py.analytics.catalog.agents import AiLlmCallCompleted
from shared.py.analytics.catalog.auth import UserSignedUp
from shared.py.analytics.catalog.billing import (
    PaymentFailed,
    PaymentSucceeded,
    SubscriptionActivated,
    SubscriptionCancelled,
    SubscriptionRenewed,
)
from shared.py.analytics.catalog.chat import ChatMessageSubmitted
from shared.py.analytics.catalog.support import SupportFormSubmitted

from .mongo import Document
from .posthog_api import PostHogReader

# processed_webhooks rows expire after 30 days, so a longer window has no truth to compare.
MAX_WINDOW_DAYS = 30
# Provider-reported cost: the ledger and PostHog may round differently per call.
COST_TOLERANCE = 0.005
LLM_GENERATION_EVENT = "$ai_generation"
# Conversations no human typed into: the agent's own scheduled and background turns.
NON_HUMAN_SOURCES = frozenset({ConversationSource.WORKFLOW_SYSTEM, ConversationSource.BACKGROUND})
# Before conversations carried a source every one of them was a web conversation.
DEFAULT_SOURCE = ConversationSource.WEB

# Each PostHog transition event against the Dodo delivery type that causes it.
WEBHOOK_EVENTS: dict[str, DodoWebhookEventType] = {
    PaymentSucceeded.event: DodoWebhookEventType.PAYMENT_SUCCEEDED,
    PaymentFailed.event: DodoWebhookEventType.PAYMENT_FAILED,
    SubscriptionActivated.event: DodoWebhookEventType.SUBSCRIPTION_ACTIVE,
    SubscriptionRenewed.event: DodoWebhookEventType.SUBSCRIPTION_RENEWED,
    SubscriptionCancelled.event: DodoWebhookEventType.SUBSCRIPTION_CANCELLED,
}
COUNTED_EVENTS = (UserSignedUp.event, SupportFormSubmitted.event, *WEBHOOK_EVENTS)

# Every events query is bounded by the same half-open UTC window, passed as {start} and {end}.
EVENT_COUNTS_HOGQL = (
    "SELECT event, count() FROM events "
    "WHERE timestamp >= toDateTime({start}, 'UTC') AND timestamp < toDateTime({end}, 'UTC') "
    "AND event IN {events} GROUP BY event"
)
MESSAGES_HOGQL = (
    "SELECT toString(properties.source), count() FROM events "
    "WHERE timestamp >= toDateTime({start}, 'UTC') AND timestamp < toDateTime({end}, 'UTC') "
    "AND event = {event} GROUP BY 1"
)
LLM_COST_HOGQL = (
    "SELECT sumIf(toFloat(properties.cost_usd), event = {llm_event}), "
    "sumIf(toFloat(properties.$ai_total_cost_usd), event = {generation_event}) FROM events "
    "WHERE timestamp >= toDateTime({start}, 'UTC') AND timestamp < toDateTime({end}, 'UTC') "
    "AND event IN ({llm_event}, {generation_event})"
)
SUBSCRIBED_PERSONS_HOGQL = "SELECT count() FROM persons WHERE properties.is_subscribed = true"


@dataclass(frozen=True)
class Row:
    """One signal: what PostHog says, what the truth says, and how far apart they may be."""

    signal: str
    posthog: float
    truth: float
    truth_source: str
    relative_tolerance: float = 0.0

    @property
    def matches(self) -> bool:
        """Whether the two sides agree within the tolerance."""
        return abs(self.posthog - self.truth) <= self.relative_tolerance * abs(self.truth)


@dataclass(frozen=True)
class Window:
    """The half-open UTC window [start, end) both sides are counted over."""

    start: datetime
    end: datetime

    @classmethod
    def last_days(cls, days: int, now: datetime) -> Window:
        """Return the window of whole UTC days ending at the start of today."""
        end = now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        return cls(start=end - timedelta(days=days), end=end)

    def hogql_values(self) -> dict[str, object]:
        """Return the window as HogQL placeholder values."""
        return {
            "start": self.start.strftime("%Y-%m-%d %H:%M:%S"),
            "end": self.end.strftime("%Y-%m-%d %H:%M:%S"),
        }

    def mongo_range(self) -> dict[str, datetime]:
        """Return the window as a Mongo range filter."""
        return {"$gte": self.start, "$lt": self.end}


def _posthog_event_counts(posthog: PostHogReader, window: Window) -> dict[str, int]:
    rows = posthog.hogql(
        EVENT_COUNTS_HOGQL, {**window.hogql_values(), "events": list(COUNTED_EVENTS)}
    )
    return {str(event): int(str(count)) for event, count in rows}


def _human_messages_by_source(db: Database[Document], window: Window) -> dict[str, int]:
    """Count user-typed messages per conversation source, by each message's own date."""
    pipeline: list[Document] = [
        {"$match": {"messages.type": "user"}},
        {"$unwind": "$messages"},
        {"$match": {"messages.type": "user"}},
        {
            "$project": {
                "source": {"$ifNull": ["$source", DEFAULT_SOURCE.value]},
                "date": {"$toDate": "$messages.date"},
            }
        },
        {"$match": {"date": window.mongo_range()}},
        {"$group": {"_id": "$source", "count": {"$sum": 1}}},
    ]
    return {
        str(row["_id"]): int(str(row["count"]))
        for row in db.conversations.aggregate(pipeline)
        if row["_id"] not in NON_HUMAN_SOURCES
    }


def _processed_webhooks(db: Database[Document], window: Window) -> dict[str, int]:
    pipeline: list[Document] = [
        {
            "$match": {
                "processed_at": window.mongo_range(),
                "status": WebhookProcessingStatus.PROCESSED.value,
            }
        },
        {"$group": {"_id": "$event_type", "count": {"$sum": 1}}},
    ]
    return {
        str(row["_id"]): int(str(row["count"])) for row in db.processed_webhooks.aggregate(pipeline)
    }


def _ledger_cost(db: Database[Document], window: Window) -> float:
    pipeline: list[Document] = [
        {"$match": {"created_at": window.mongo_range()}},
        {"$group": {"_id": None, "cost": {"$sum": "$cost_usd"}}},
    ]
    totals = list(db.llm_calls.aggregate(pipeline))
    return float(str(totals[0]["cost"])) if totals else 0.0


def message_rows(posthog: PostHogReader, db: Database[Document], window: Window) -> list[Row]:
    """Return one row per message source: chat:message_submitted against the human messages in Mongo."""
    posthog_counts = {
        str(source): int(str(count))
        for source, count in posthog.hogql(
            MESSAGES_HOGQL, {**window.hogql_values(), "event": ChatMessageSubmitted.event}
        )
    }
    truth = _human_messages_by_source(db, window)
    return [
        Row(
            f"messages, {source}",
            posthog_counts.get(source, 0),
            truth.get(source, 0),
            "conversations.messages type=user",
        )
        for source in sorted(posthog_counts.keys() | truth.keys())
    ]


def count_rows(posthog: PostHogReader, db: Database[Document], window: Window) -> list[Row]:
    """Return signups, support requests and every billing transition against their Mongo truth."""
    counts = _posthog_event_counts(posthog, window)
    webhooks = _processed_webhooks(db, window)
    rows = [
        Row(
            "signups",
            counts.get(UserSignedUp.event, 0),
            db.users.count_documents({"created_at": window.mongo_range()}),
            "users.created_at",
        ),
        Row(
            "support requests",
            counts.get(SupportFormSubmitted.event, 0),
            db.support_requests.count_documents({"created_at": window.mongo_range()}),
            "support_requests.created_at",
        ),
        Row(
            f"{SubscriptionActivated.event} (rows)",
            counts.get(SubscriptionActivated.event, 0),
            db.subscriptions.count_documents({"created_at": window.mongo_range()}),
            "subscriptions.created_at",
        ),
    ]
    rows += [
        Row(
            event,
            counts.get(event, 0),
            webhooks.get(webhook.value, 0),
            f"processed_webhooks {webhook.value}",
        )
        for event, webhook in WEBHOOK_EVENTS.items()
    ]
    return rows


def cost_row(posthog: PostHogReader, db: Database[Document], window: Window) -> Row:
    """Return PostHog LLM spend (one-shot events plus graph generations) against the llm_calls ledger."""
    ((one_shot, generations),) = posthog.hogql(
        LLM_COST_HOGQL,
        {
            **window.hogql_values(),
            "llm_event": AiLlmCallCompleted.event,
            "generation_event": LLM_GENERATION_EVENT,
        },
    )
    spend = float(str(one_shot or 0)) + float(str(generations or 0))
    return Row(
        "LLM cost (USD)", spend, _ledger_cost(db, window), "llm_calls.cost_usd", COST_TOLERANCE
    )


def subscriber_row(posthog: PostHogReader, db: Database[Document]) -> Row:
    """Return persons marked subscribed now against users with an active subscription now.

    A $0 discount-code subscription is active, so it counts as a subscriber.
    """
    ((subscribed,),) = posthog.hogql(SUBSCRIBED_PERSONS_HOGQL)
    active = db.subscriptions.distinct("user_id", {"status": SubscriptionStatus.ACTIVE.value})
    return Row(
        "active subscribers (now)", int(str(subscribed)), len(active), "subscriptions status=active"
    )


def render(rows: Iterable[Row]) -> str:
    """Return the rows as an aligned table."""
    header = ("", "signal", "posthog", "truth", "truth source")
    lines = [
        (
            "ok" if row.matches else "XX",
            row.signal,
            f"{row.posthog:g}",
            f"{row.truth:g}",
            row.truth_source,
        )
        for row in rows
    ]
    widths = [max(len(line[i]) for line in [header, *lines]) for i in range(len(header))]
    return "\n".join(
        "  ".join(cell.ljust(width) for cell, width in zip(line, widths, strict=True))
        for line in [header, *lines]
    )


def reconcile(posthog: PostHogReader, db: Database[Document], window: Window) -> list[Row]:
    """Build every row of the reconciliation table."""
    builders: list[Callable[[], list[Row]]] = [
        lambda: count_rows(posthog, db, window),
        lambda: message_rows(posthog, db, window),
        lambda: [cost_row(posthog, db, window)],
        lambda: [subscriber_row(posthog, db)],
    ]
    return [row for build in builders for row in build()]
