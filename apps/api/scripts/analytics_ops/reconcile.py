"""Print PostHog next to its ground truth for every signal the dashboards report, and fail on drift.

Ground truth is Mongo: users, conversations, processed_webhooks (Dodo's own
deliveries, kept 30 days), subscriptions, support_requests and the llm_calls
ledger. PostHog is read unfiltered, so both sides include test accounts.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
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


@dataclass(frozen=True)
class Signals:
    """One side's count of every signal the dashboards report, over one window."""

    signups: int
    support_requests: int
    subscriptions_started: int
    # Per PostHog billing event name; the Mongo side counts the Dodo deliveries that cause each.
    billing: Mapping[str, int]
    messages_by_source: Mapping[str, int]
    llm_cost_usd: float
    subscribers_now: int


def posthog_signals(posthog: PostHogReader, window: Window) -> Signals:
    """Read every signal from PostHog, unfiltered, over window."""
    span = window.hogql_values()
    counts = {
        str(event): int(str(count))
        for event, count in posthog.hogql(
            EVENT_COUNTS_HOGQL, {**span, "events": list(COUNTED_EVENTS)}
        )
    }
    messages = {
        str(source): int(str(count))
        for source, count in posthog.hogql(
            MESSAGES_HOGQL, {**span, "event": ChatMessageSubmitted.event}
        )
    }
    ((one_shot, generations),) = posthog.hogql(
        LLM_COST_HOGQL,
        {**span, "llm_event": AiLlmCallCompleted.event, "generation_event": LLM_GENERATION_EVENT},
    )
    ((subscribed,),) = posthog.hogql(SUBSCRIBED_PERSONS_HOGQL)
    return Signals(
        signups=counts.get(UserSignedUp.event, 0),
        support_requests=counts.get(SupportFormSubmitted.event, 0),
        subscriptions_started=counts.get(SubscriptionActivated.event, 0),
        billing={event: counts.get(event, 0) for event in WEBHOOK_EVENTS},
        messages_by_source=messages,
        llm_cost_usd=float(str(one_shot or 0)) + float(str(generations or 0)),
        subscribers_now=int(str(subscribed)),
    )


def human_messages_by_source(db: Database[Document], window: Window) -> dict[str, int]:
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


def mongo_signals(db: Database[Document], window: Window) -> Signals:
    """Read every signal's ground truth from Mongo over window; subscribers are counted as of now."""
    in_window = {"created_at": window.mongo_range()}
    webhooks = _processed_webhooks(db, window)
    return Signals(
        signups=db.users.count_documents(in_window),
        support_requests=db.support_requests.count_documents(in_window),
        subscriptions_started=db.subscriptions.count_documents(in_window),
        billing={event: webhooks.get(kind.value, 0) for event, kind in WEBHOOK_EVENTS.items()},
        messages_by_source=human_messages_by_source(db, window),
        llm_cost_usd=_ledger_cost(db, window),
        subscribers_now=len(
            db.subscriptions.distinct("user_id", {"status": SubscriptionStatus.ACTIVE.value})
        ),
    )


def compare(posthog: Signals, truth: Signals) -> list[Row]:
    """Pair each PostHog signal with its truth; a $0 discount-code subscription counts as a subscriber."""
    rows = [
        Row("signups", posthog.signups, truth.signups, "users.created_at"),
        Row(
            "support requests",
            posthog.support_requests,
            truth.support_requests,
            "support_requests.created_at",
        ),
        Row(
            f"{SubscriptionActivated.event} (rows)",
            posthog.subscriptions_started,
            truth.subscriptions_started,
            "subscriptions.created_at",
        ),
    ]
    rows += [
        Row(
            event,
            posthog.billing[event],
            truth.billing[event],
            f"processed_webhooks {WEBHOOK_EVENTS[event].value}",
        )
        for event in WEBHOOK_EVENTS
    ]
    sources = sorted(posthog.messages_by_source.keys() | truth.messages_by_source.keys())
    rows += [
        Row(
            f"messages, {source}",
            posthog.messages_by_source.get(source, 0),
            truth.messages_by_source.get(source, 0),
            "conversations.messages type=user",
        )
        for source in sources
    ]
    rows += [
        Row(
            "LLM cost (USD)",
            posthog.llm_cost_usd,
            truth.llm_cost_usd,
            "llm_calls.cost_usd",
            COST_TOLERANCE,
        ),
        Row(
            "active subscribers (now)",
            posthog.subscribers_now,
            truth.subscribers_now,
            "subscriptions status=active",
        ),
    ]
    return rows


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
    return compare(posthog_signals(posthog, window), mongo_signals(db, window))
