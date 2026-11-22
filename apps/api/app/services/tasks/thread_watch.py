"""A GAIA task about an email thread: it runs when the thread gets mail either way."""

from app.constants.triggers import GMAIL_EMAIL_SENT_TRIGGER_NAME, GMAIL_NEW_MESSAGE_TRIGGER_NAME
from app.models.task_models import ExternalRef, TaskDocument
from app.models.trigger_subscription_models import (
    ConditionMatch,
    ConditionOperator,
    SubscriptionAction,
    SubscriptionCondition,
)
from app.services.tasks.subscription_config import DEFAULT_COOLDOWN_SECONDS
from app.services.tasks.subscriptions import SubscriptionRequest, subscribe

#: New mail on the thread, and the user's own replies on it.
THREAD_TRIGGERS = (GMAIL_NEW_MESSAGE_TRIGGER_NAME, GMAIL_EMAIL_SENT_TRIGGER_NAME)


async def watch_thread(task: TaskDocument, thread: ExternalRef) -> None:
    """Subscribe the task to its thread on the thread's own account; raises SubscriptionError."""
    on_thread = SubscriptionCondition(
        field_name="thread_id", operator=ConditionOperator.EQUALS, value=thread.id
    )
    for trigger_name in THREAD_TRIGGERS:
        await subscribe(
            task,
            SubscriptionRequest(
                trigger_name=trigger_name,
                action=SubscriptionAction.EXECUTE,
                conditions=[on_thread],
                match=ConditionMatch.ALL,
                cooldown_seconds=DEFAULT_COOLDOWN_SECONDS,
                trigger_data=None,
                account_id=thread.account,
                gate=None,
            ),
        )
