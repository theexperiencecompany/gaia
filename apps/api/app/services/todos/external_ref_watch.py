"""Keep an open todo about an outside object watching that object for changes."""

from collections.abc import Sequence
from typing import NamedTuple

from app.constants.todos import (
    INBOX_DESK_AUTOMATED_SENDERS,
    INBOX_DESK_WATCH_LABELS,
    INBOX_DESK_WATCH_WINDOW_SECONDS,
)
from app.constants.triggers import GMAIL_EMAIL_SENT_TRIGGER_NAME, GMAIL_NEW_MESSAGE_TRIGGER_NAME
from app.models.todo_models import ExternalRef, ExternalRefSource
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
    """How to see an outside object change: what an event must match, its triggers, its window."""

    conditions: tuple[SubscriptionCondition, ...]
    trigger_names: tuple[str, ...]
    window_seconds: int


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
            )
        case ExternalRefSource.INBOX_DESK:
            return _RefWatch(
                _DESK_MAIL, (GMAIL_NEW_MESSAGE_TRIGGER_NAME,), INBOX_DESK_WATCH_WINDOW_SECONDS
            )


async def watch_external_ref(
    todo_id: str, user_id: str, ref: ExternalRef, subscriptions: Sequence[TriggerSubscription]
) -> list[TriggerSubscription]:
    """Run the todo whenever ref changes, adding only the watches subscriptions lacks.

    Returns the watches it added; when one fails, the ones it added are removed again.
    """
    watch = _ref_watch(ref)
    watched = {
        sub.trigger_name for sub in subscriptions if set(watch.conditions) <= set(sub.conditions)
    }
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
            )
            # Only rows this call stored are rolled back: a concurrent winner's
            # row is not ours to remove if a later watch fails.
            if created:
                added.append(subscription)
    except Exception:
        await release_watches(todo_id, user_id, added)
        raise
    return added


async def release_watches(
    todo_id: str, user_id: str, subscriptions: Sequence[TriggerSubscription]
) -> None:
    """Remove exactly these watches from the todo, leaving any others it had."""
    for subscription in subscriptions:
        await unregister_subscription(todo_id, user_id, subscription.id)
