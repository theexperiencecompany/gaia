"""Backfill user:signed_up and subscription:activated for records that predate their tracking.

Each event goes through prepare_capture with a Dedupe built from its record (the
user or subscription id, and its Mongo created_at), so its uuid and timestamp
are the same on every run: PostHog upserts a resend instead of adding a row,
and a record whose person already has the event is not planned at all. Events
are marked backfilled and carry no $set, which would overwrite today's person
properties. They are attributed actor=user, trigger=system, surface=worker:
the person did it, a backfill reported it.

Sent through the normal capture pipeline, which stores a past timestamp as
given (prepare_capture sets $ignore_sent_at for a deduped event); the
historical_migration pipeline needs a paid plan this org does not have.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime

from pymongo.database import Database

from app.models.payment_models import SubscriptionDocument
from app.utils.money import to_major_units
from shared.py.analytics import Dedupe, UserId, prepare_capture
from shared.py.analytics.catalog.attribution import Actor, Attribution, EntrySurface, Trigger
from shared.py.analytics.catalog.auth import UserSignedUp
from shared.py.analytics.catalog.base import ServerEvent, Surface
from shared.py.analytics.catalog.billing import SubscriptionActivated
from shared.py.analytics.context import AnalyticsContext, analytics_context

from .mongo import Document
from .posthog_api import PostHogReader, Sender, hogql_complete

# The first user:signed_up PostHog holds; signups before it were never captured.
FIRST_TRACKED_SIGNUP = datetime(2026, 1, 29, tzinfo=UTC)
# The only plan GAIA has sold; subscription:activated names it.
PRO_PLAN_NAME = "Pro"
BACKFILL_CONTEXT = AnalyticsContext(
    attribution=Attribution(actor=Actor.USER, trigger=Trigger.SYSTEM, surface=EntrySurface.WORKER)
)

# Users whose person already holds the event, under any of its distinct ids.
USERS_WITH_EVENT_HOGQL = (
    "SELECT distinct_id FROM person_distinct_ids WHERE has({ids}, distinct_id) "
    "AND person_id IN (SELECT person_id FROM events WHERE event = {event} "
    "AND timestamp >= toDateTime({since}, 'UTC')) LIMIT {limit}"
)
# Users whose person holds an activation naming no subscription GAIA knows: the only
# activations that can stand for a subscription missing by id.
USERS_WITH_UNMATCHED_ACTIVATION_HOGQL = (
    "SELECT distinct_id FROM person_distinct_ids WHERE has({ids}, distinct_id) "
    "AND person_id IN (SELECT person_id FROM events WHERE event = {event} "
    "AND timestamp >= toDateTime({since}, 'UTC') "
    "AND NOT has({known}, toString(properties.subscription_id))) LIMIT {limit}"
)
TRACKED_SUBSCRIPTIONS_HOGQL = (
    "SELECT DISTINCT toString(properties.subscription_id) FROM events "
    "WHERE event = {event} AND timestamp >= toDateTime({since}, 'UTC') LIMIT {limit}"
)


@dataclass(frozen=True)
class Backfill:
    """One historical event, keyed by the record it reports."""

    user_id: UserId
    event: ServerEvent
    dedupe: Dedupe


@dataclass(frozen=True)
class HistoryPlan:
    """What a run will send, and the records it cannot build an event from."""

    signups: list[Backfill]
    activations: list[Backfill]
    unbuildable: list[str]

    def summary(self) -> str:
        """Return the counts."""
        return (
            f"{len(self.signups)} {UserSignedUp.event}, "
            f"{len(self.activations)} {SubscriptionActivated.event}, "
            f"{len(self.unbuildable)} records that cannot be built (not sent)"
        )

    def holding_out(self, users: set[str]) -> HistoryPlan:
        """Return the plan without the events of users, whose history is not yet readable."""
        return HistoryPlan(
            [b for b in self.signups if b.user_id.distinct_id not in users],
            [b for b in self.activations if b.user_id.distinct_id not in users],
            self.unbuildable,
        )


def _earliest(db: Database[Document], collection: str) -> datetime:
    first = db[collection].find_one({"created_at": {"$type": "date"}}, sort=[("created_at", 1)])
    if first is None:
        return FIRST_TRACKED_SIGNUP
    return _created_at(first)


def _created_at(record: Document) -> datetime:
    """Return a record's created_at; the queries select only records whose created_at is a date."""
    created = record["created_at"]
    if not isinstance(created, datetime):
        raise TypeError(f"{record['_id']} has created_at {created!r}, not a date")
    return created


def _already_tracked(
    read: PostHogReader, user_ids: list[str], event: str, since: datetime
) -> set[str]:
    rows = hogql_complete(
        read,
        USERS_WITH_EVENT_HOGQL,
        {"ids": user_ids, "event": event, "since": since.strftime("%Y-%m-%d %H:%M:%S")},
    )
    return {str(distinct_id) for (distinct_id,) in rows}


def plan_signups(read: PostHogReader, db: Database[Document]) -> list[Backfill]:
    """Plan a signup for every user created before tracking whose person has none."""
    users = list(
        db.users.find(
            {"created_at": {"$lt": FIRST_TRACKED_SIGNUP, "$type": "date"}}, {"created_at": 1}
        )
    )
    tracked = _already_tracked(
        read, [str(user["_id"]) for user in users], UserSignedUp.event, _earliest(db, "users")
    )
    return [signup(user) for user in users if str(user["_id"]) not in tracked]


def signup(user: Document) -> Backfill:
    """Build the signup a users record reports, keyed and timed by the record."""
    return Backfill(
        UserId(str(user["_id"])),
        UserSignedUp(backfilled=True),
        Dedupe(key=str(user["_id"]), occurred_at=_created_at(user)),
    )


def activation(row: SubscriptionDocument) -> Backfill:
    """Build the activation a subscription row reports; raise ValueError when it cannot be."""
    if row.created_at is None or row.currency is None:
        raise ValueError("no created_at or currency")
    # A 0 is a real discount-code charge: reported as 0, never dropped, as the live activation does.
    amount = (
        None
        if row.recurring_pre_tax_amount is None
        else float(to_major_units(row.recurring_pre_tax_amount, row.currency))
    )
    return Backfill(
        UserId(row.user_id),
        SubscriptionActivated(
            subscription_id=row.dodo_subscription_id,
            plan_name=PRO_PLAN_NAME,
            currency=row.currency,
            amount=amount,
            amount_charged_pre_tax=amount,
            currency_charged=row.currency if amount is not None else None,
            backfilled=True,
        ),
        Dedupe(key=row.dodo_subscription_id, occurred_at=row.created_at),
    )


def plan_activations(
    read: PostHogReader, db: Database[Document]
) -> tuple[list[Backfill], list[str]]:
    """Plan an activation for every subscription PostHog has none for, by id or by an unmatched one on its owner's person."""
    rows = [SubscriptionDocument.model_validate(raw) for raw in db.subscriptions.find({})]
    earliest = _earliest(db, "subscriptions")
    since = earliest.strftime("%Y-%m-%d %H:%M:%S")
    tracked_ids = {
        str(subscription_id)
        for (subscription_id,) in hogql_complete(
            read,
            TRACKED_SUBSCRIPTIONS_HOGQL,
            {"event": SubscriptionActivated.event, "since": since},
        )
    }
    owners_tracked = {
        str(distinct_id)
        for (distinct_id,) in hogql_complete(
            read,
            USERS_WITH_UNMATCHED_ACTIVATION_HOGQL,
            {
                "ids": sorted({row.user_id for row in rows}),
                "known": sorted({row.dodo_subscription_id for row in rows}),
                "event": SubscriptionActivated.event,
                "since": since,
            },
        )
    }
    to_backfill, unbuildable = untracked_activations(rows, tracked_ids, owners_tracked)
    planned: list[Backfill] = []
    for row in to_backfill:
        try:
            planned.append(activation(row))
        except ValueError as error:
            unbuildable.append(f"subscription {row.dodo_subscription_id}: {error}")
    return planned, unbuildable


def untracked_activations(
    rows: list[SubscriptionDocument], tracked_ids: set[str], owners_tracked: set[str]
) -> tuple[list[SubscriptionDocument], list[str]]:
    """Split the subscriptions with no activation by id into ones to backfill and ones to review.

    An activation found only on the owner's person proves one subscription: it
    covers a lone untracked one, and leaves several for a human, since which
    one it reports is unknown.
    """
    untracked: defaultdict[str, list[SubscriptionDocument]] = defaultdict(list)
    for row in rows:
        if row.dodo_subscription_id not in tracked_ids:
            untracked[row.user_id].append(row)
    to_backfill: list[SubscriptionDocument] = []
    review: list[str] = []
    for user_id, owned in untracked.items():
        if user_id not in owners_tracked:
            to_backfill += owned
        elif len(owned) > 1:
            ids = ", ".join(row.dodo_subscription_id for row in owned)
            review.append(
                f"user {user_id}: {len(owned)} subscriptions have no activation by id and one "
                f"is on the person; which one it reports is unknown ({ids})"
            )
    return to_backfill, review


def plan(read: PostHogReader, db: Database[Document]) -> HistoryPlan:
    """Plan both backfills."""
    activations, unbuildable = plan_activations(read, db)
    return HistoryPlan(plan_signups(read, db), activations, unbuildable)


def apply(sender: Sender, backfills: list[Backfill]) -> None:
    """Send each backfill through the catalog's capture preparation."""
    with analytics_context(BACKFILL_CONTEXT):
        for backfill in backfills:
            prepare_capture(backfill.user_id, backfill.event, Surface.SERVER, backfill.dedupe).send(
                sender.client
            )
