"""Set each subscriber's paid-state person properties from the Mongo subscription the app reads.

The projection is the webhook's own (paid_person_properties), so a backfilled
person reads exactly as one the webhook set. Sent as a plain $set at now:
$set is idempotent, and only persons whose PostHog values differ are sent, so a
re-run after an apply sends nothing.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime

from app.models.payment_models import SubscriptionDocument, SubscriptionStatus
from app.services.payments.subscription_events import paid_person_properties
from shared.py.analytics import UserId

from .mongo import Document
from .posthog_api import PostHogReader, Sender, hogql_complete

PERSON_STATE_HOGQL = (
    "SELECT distinct_id, toString(person.properties.plan), "
    "toString(person.properties.is_subscribed), toString(person.properties.subscription_status), "
    "toString(person.properties.subscription_cancel_at_period_end) "
    "FROM person_distinct_ids WHERE has({ids}, distinct_id) LIMIT {limit}"
)
# A row with no timestamps sorts before any that has one.
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
# Re-reads after a send before a still-moving state stops the run rather than racing it.
SETTLE_ROUNDS = 3
PROPERTY_ORDER = (
    "plan",
    "is_subscribed",
    "subscription_status",
    "subscription_cancel_at_period_end",
)


@dataclass(frozen=True)
class PaidState:
    """One user's projected paid state."""

    user_id: UserId
    properties: dict[str, object]


def _as_posthog_string(value: object) -> str:
    """Render a property the way HogQL's toString shows it, so the two sides compare."""
    return str(value).lower() if isinstance(value, bool) else str(value)


def _preference(row: SubscriptionDocument) -> tuple[bool, datetime, datetime]:
    """Rank a user's rows as the app reads them: the newest active row, else the newest lapsed one."""
    if row.status == SubscriptionStatus.ACTIVE.value:
        return (True, row.created_at or _EPOCH, row.updated_at or _EPOCH)
    return (False, row.updated_at or _EPOCH, row.created_at or _EPOCH)


def latest_states(rows: Iterable[Document]) -> list[PaidState]:
    """Project the row the app reads for each user; exit 1 on a row whose owner is not a user id."""
    latest: dict[str, SubscriptionDocument] = {}
    for raw in rows:
        row = SubscriptionDocument.model_validate(raw)
        current = latest.get(row.user_id)
        if current is None or _preference(row) >= _preference(current):
            latest[row.user_id] = row
    owners: dict[str, UserId] = {}
    bad_owners: list[str] = []
    for user_id in sorted(latest):
        try:
            owners[user_id] = UserId(user_id)
        except ValueError:
            bad_owners.append(user_id)
    if bad_owners:
        raise SystemExit(f"subscriptions owned by non-user ids, fix them first: {bad_owners}")
    return [
        PaidState(
            owners[user_id],
            paid_person_properties(
                SubscriptionStatus(row.status),
                cancel_at_period_end=bool(row.cancel_at_next_billing_date),
            ),
        )
        for user_id, row in sorted(latest.items())
    ]


def stale_states(read: PostHogReader, states: list[PaidState]) -> list[PaidState]:
    """Return the states whose person in PostHog does not already carry these exact values."""
    rows = hogql_complete(
        read, PERSON_STATE_HOGQL, {"ids": [state.user_id.distinct_id for state in states]}
    )
    current = {str(row[0]): tuple(str(cell) for cell in row[1:]) for row in rows}
    return [
        state
        for state in states
        if current.get(state.user_id.distinct_id)
        != tuple(_as_posthog_string(state.properties[key]) for key in PROPERTY_ORDER)
    ]


def summarize(states: list[PaidState]) -> str:
    """Return the per-status and subscribed counts of a set of states."""
    by_status = Counter(str(state.properties["subscription_status"]) for state in states)
    subscribed = sum(1 for state in states if state.properties["is_subscribed"] is True)
    statuses = ", ".join(f"{status} {count}" for status, count in sorted(by_status.items()))
    return f"{len(states)} users ({statuses}); is_subscribed=true {subscribed}"


def apply(sender: Sender, states: list[PaidState]) -> None:
    """Send one $set per state."""
    for state in states:
        sender.client.set(distinct_id=state.user_id.distinct_id, properties=state.properties)


def apply_until_settled(
    sender: Sender, states: list[PaidState], reread: Callable[[], list[PaidState]]
) -> None:
    """Send states, then re-read Mongo and resend whatever moved, until nothing does.

    A billing write that lands between the read and the send sets its newer
    state first; the resend puts it back on top of the older one this run sent.
    """
    sent = {state.user_id.distinct_id: state for state in states}
    pending = states
    for _ in range(SETTLE_ROUNDS):
        apply(sender, pending)
        pending = [
            state
            for state in reread()
            if state.user_id.distinct_id in sent and sent[state.user_id.distinct_id] != state
        ]
        if not pending:
            return
        sent.update((state.user_id.distinct_id, state) for state in pending)
    raise SystemExit(
        f"paid state still changing after {SETTLE_ROUNDS} re-reads for "
        f"{[state.user_id.distinct_id for state in pending]}; re-run once billing settles"
    )
