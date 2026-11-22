"""What an app event does to a task when its subscription only tells, closes or unblocks it.

A notify subscription tells the user the event landed, once per event however often it is
redelivered. A complete subscription closes the task through the ordinary path. An unblock
subscription clears the flags that say the task waits on something outside GAIA, and tells
the user instead when there were none, so an unblock never reads as a subscription that did
not fire. None of them runs GAIA, so none has a gate or a run window: each is held to its
subscription's cooldown instead.
"""

import hashlib
import json

from app.constants.tasks import BLOCKING_FLAGS, TASK_EVENT_NOTIFY_BODY, TASK_EVENT_NOTIFY_TITLE
from app.db.repositories.tasks import task_repository
from app.models.notification.notification_models import (
    NotificationContent,
    NotificationRequest,
    NotificationSourceEnum,
    notification_id,
)
from app.models.task_models import TaskDocument
from app.models.trigger_subscription_models import SubscriptionAction, TriggerSubscription
from app.services.notification_service import notification_service
from app.services.tasks.completion import complete_task
from app.services.tasks.todo_rounds import task_redirect_action
from shared.py.analytics.catalog.tasks import EventFireOutcome
from shared.py.wide_events import log


async def act_on_event(
    task: TaskDocument, subscription: TriggerSubscription, payload: dict[str, object]
) -> EventFireOutcome:
    """Carry out a subscription's action other than a run; returns what it did."""
    match subscription.action:
        case SubscriptionAction.NOTIFY:
            await _notify(task, subscription, payload)
            return "notified"
        case SubscriptionAction.COMPLETE:
            await complete_task(
                task, f"Completed automatically: {subscription.trigger_name} fired."
            )
            return "completed"
        case SubscriptionAction.UNBLOCK:
            return await _unblock(task, subscription, payload)
        case SubscriptionAction.EXECUTE:
            raise ValueError(f"subscription {subscription.id} runs its task; it is not an action")


async def _notify(
    task: TaskDocument, subscription: TriggerSubscription, payload: dict[str, object]
) -> None:
    event = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
    await notification_service.notify(
        NotificationRequest(
            id=notification_id(task.user_id, "task_event", subscription.id, event),
            user_id=task.user_id,
            source=NotificationSourceEnum.TODO_TRIGGER,
            content=NotificationContent(
                title=TASK_EVENT_NOTIFY_TITLE.format(title=task.title),
                body=TASK_EVENT_NOTIFY_BODY.format(trigger_name=subscription.trigger_name),
                actions=[task_redirect_action(task.id)],
            ),
            metadata={"task_id": task.id, "subscription_id": subscription.id},
        )
    )


async def _unblock(
    task: TaskDocument, subscription: TriggerSubscription, payload: dict[str, object]
) -> EventFireOutcome:
    blocking = BLOCKING_FLAGS.intersection(task.status_flags)
    if not blocking:
        await _notify(task, subscription, payload)
        return "notified"
    await task_repository.remove_flags(task.id, user_id=task.user_id, flags=blocking)
    log.set_ns("task_event", unblocked=sorted(blocking))
    return "unblocked"
