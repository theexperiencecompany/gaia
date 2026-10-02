"""Keep an open todo about an outside object watching that object for changes."""

from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import NamedTuple

from app.constants.triggers import GMAIL_EMAIL_SENT_TRIGGER_NAME, GMAIL_NEW_MESSAGE_TRIGGER_NAME
from app.models.todo_models import ExternalRef, ExternalRefSource
from app.models.trigger_subscription_models import (
    ConditionOperator,
    SubscriptionAction,
    SubscriptionCondition,
    TriggerSubscription,
)
from app.services.triggers.subscription_service import (
    register_subscription,
    unregister_subscription,
)


class _RefWatch(NamedTuple):
    """How to see an outside object change: the payload field naming it, and its triggers."""

    field_name: str
    trigger_names: tuple[str, ...]


# A Gmail thread moves both ways: mail arrives on it, and the user replies from Gmail.
_REF_WATCHES: Mapping[ExternalRefSource, _RefWatch] = MappingProxyType(
    {
        ExternalRefSource.GMAIL_THREAD: _RefWatch(
            "thread_id", (GMAIL_NEW_MESSAGE_TRIGGER_NAME, GMAIL_EMAIL_SENT_TRIGGER_NAME)
        ),
    }
)


async def watch_external_ref(
    todo_id: str, user_id: str, ref: ExternalRef, subscriptions: Sequence[TriggerSubscription]
) -> list[TriggerSubscription]:
    """Run the todo whenever ref changes, adding only the watches subscriptions lacks.

    Returns the watches it added; when one fails, the ones it added are removed again.
    """
    watch = _REF_WATCHES[ref.source]
    on_ref = SubscriptionCondition(
        field_name=watch.field_name, operator=ConditionOperator.EQUALS, value=ref.id
    )
    watched = {sub.trigger_name for sub in subscriptions if on_ref in sub.conditions}
    added: list[TriggerSubscription] = []
    try:
        for trigger_name in watch.trigger_names:
            if trigger_name in watched:
                continue
            subscription, _outcome = await register_subscription(
                todo_id=todo_id,
                user_id=user_id,
                trigger_name=trigger_name,
                conditions=[on_ref],
                action=SubscriptionAction.EXECUTE,
            )
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
