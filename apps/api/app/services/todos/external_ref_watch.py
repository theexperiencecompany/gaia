"""Keep an open todo about an outside object watching that object for changes."""

from collections.abc import Sequence
from typing import NamedTuple

from app.constants.todos import (
    INBOX_DESK_AUTOMATED_SENDERS,
    INBOX_DESK_WATCH_LABELS,
    INBOX_DESK_WATCH_WINDOW_SECONDS,
)
from app.constants.trigger_gates import SystemGatePreset
from app.constants.triggers import GMAIL_EMAIL_SENT_TRIGGER_NAME, GMAIL_NEW_MESSAGE_TRIGGER_NAME
from app.db.repositories.todos import todo_repository
from app.models.todo_models import ExternalRef, ExternalRefSource
from app.models.trigger_gate_models import SystemGate, TriggerGate
from app.models.trigger_subscription_models import (
    ConditionOperator,
    SubscriptionAction,
    SubscriptionCondition,
    TriggerSubscription,
)
from app.services.triggers.subscription_service import (
    DEFAULT_COOLDOWN_SECONDS,
    register_subscription,
    unregister_subscription,
)


class _RefWatch(NamedTuple):
    """How to see an outside object change: what an event must match, its triggers, window and gate."""

    conditions: tuple[SubscriptionCondition, ...]
    trigger_names: tuple[str, ...]
    window_seconds: int
    # The one account the object lives in; None watches every account.
    account_id: str | None = None
    gate: TriggerGate | None = None

    def covers(self, subscription: TriggerSubscription) -> bool:
        """Whether subscription already fires on every event this watch needs."""
        return (
            subscription.trigger_name in self.trigger_names
            and set(self.conditions) <= set(subscription.conditions)
            and subscription.account_id == self.account_id
        )


# A person's new mail in the Primary inbox; the desk's fetch skips the same senders.
_DESK_MAIL = (
    *(
        SubscriptionCondition(
            field_name="label_ids", operator=ConditionOperator.CONTAINS, value=label
        )
        for label in INBOX_DESK_WATCH_LABELS
    ),
    *(
        SubscriptionCondition(
            field_name="sender", operator=ConditionOperator.NOT_CONTAINS, value=sender
        )
        for sender in INBOX_DESK_AUTOMATED_SENDERS
    ),
)
_DESK_GATE = SystemGate(preset=SystemGatePreset.INBOX_DESK)


def _ref_watch(ref: ExternalRef) -> _RefWatch:
    """Say what to watch for ref: a thread both ways, or the desk's mailbox for new mail."""
    match ref.source:
        case ExternalRefSource.GMAIL_THREAD:
            on_thread = SubscriptionCondition(
                field_name="thread_id", operator=ConditionOperator.EQUALS, value=ref.id
            )
            return _RefWatch(
                (on_thread,),
                (GMAIL_NEW_MESSAGE_TRIGGER_NAME, GMAIL_EMAIL_SENT_TRIGGER_NAME),
                DEFAULT_COOLDOWN_SECONDS,
                ref.account,
            )
        case ExternalRefSource.INBOX_DESK:
            return _RefWatch(
                _DESK_MAIL,
                (GMAIL_NEW_MESSAGE_TRIGGER_NAME,),
                INBOX_DESK_WATCH_WINDOW_SECONDS,
                gate=_DESK_GATE,
            )


async def watch_external_ref(
    todo_id: str, user_id: str, ref: ExternalRef, subscriptions: Sequence[TriggerSubscription]
) -> list[TriggerSubscription]:
    """Run the todo whenever ref changes, adding only the watches subscriptions lacks.

    A watch it already has that never had ref's gate gets it. Returns the watches it
    added; when one fails, the ones it added are removed again.
    """
    watch = _ref_watch(ref)
    watched = {sub.trigger_name for sub in subscriptions if watch.covers(sub)}
    added: list[TriggerSubscription] = []
    try:
        for trigger_name in watch.trigger_names:
            if trigger_name in watched:
                continue
            subscription, _outcome, created = await register_subscription(
                todo_id=todo_id,
                user_id=user_id,
                trigger_name=trigger_name,
                conditions=list(watch.conditions),
                action=SubscriptionAction.EXECUTE,
                cooldown_seconds=watch.window_seconds,
                account_id=watch.account_id,
                gate=watch.gate,
            )
            # Only rows this call stored are rolled back: a concurrent winner's
            # row is not ours to remove if a later watch fails.
            if created:
                added.append(subscription)
    except Exception:
        await release_watches(todo_id, user_id, added)
        raise
    await gate_watches(todo_id, user_id, ref, subscriptions)
    return added


def ungated_watches(
    ref: ExternalRef, subscriptions: Sequence[TriggerSubscription]
) -> list[TriggerSubscription]:
    """Return ref's watches that never had its gate; one the user turned off still has it."""
    watch = _ref_watch(ref)
    if watch.gate is None:
        return []
    return [
        sub
        for sub in subscriptions
        if watch.covers(sub) and sub.action is SubscriptionAction.EXECUTE and sub.gate is None
    ]


async def gate_watches(
    todo_id: str, user_id: str, ref: ExternalRef, subscriptions: Sequence[TriggerSubscription]
) -> bool:
    """Put ref's gate on its watches that never had one; True when this call gated one."""
    gate = _ref_watch(ref).gate
    ungated = ungated_watches(ref, subscriptions)
    if gate is None or not ungated:
        return False
    gated = await todo_repository.gate_ungated_subscriptions(
        todo_id, user_id=user_id, subscription_ids=[sub.id for sub in ungated], gate=gate
    )
    return gated is not None


async def release_watches(
    todo_id: str, user_id: str, subscriptions: Sequence[TriggerSubscription]
) -> None:
    """Remove exactly these watches from the todo, leaving any others it had."""
    for subscription in subscriptions:
        await unregister_subscription(todo_id, user_id, subscription.id)
