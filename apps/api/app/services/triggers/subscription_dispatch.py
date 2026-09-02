"""Fan a fired Composio trigger out to the tracked todos subscribed to it.

Called from ``TriggerHandler.process_event`` before the no-matching-workflow
short-circuit, because an event with no workflow can still have a todo waiting on
it — and today that event is dropped.

Resolution mirrors ``GmailTriggerHandler.find_workflows`` and runs both
strategies, for the same reason it does: per-resource triggers are found by the
Composio instance id on the webhook, while account-level triggers (Gmail) have no
instance to register and can only be found by user and trigger name. A lookup on
instance ids alone finds nothing for Gmail, which is the entire reply-watching
case.
"""

from datetime import UTC, datetime
from typing import Any

from redis.exceptions import RedisError

from app.constants.todos import BLOCKING_LABELS
from app.db.redis import redis_cache
from app.db.repositories.todos import todo_repository
from app.models.notification.notification_models import (
    NotificationContent,
    NotificationRequest,
    NotificationSourceEnum,
)
from app.models.todo_models import TodoDocument, TodoUpdate
from app.models.trigger_subscription_models import (
    SubscriptionAction,
    SubscriptionStatus,
    TriggerOrigin,
    TriggerSubscription,
)
from app.services.analytics_service import AnalyticsEvents, capture_event
from app.services.notification_service import notification_service
from app.services.todos.todo_notifications import todo_redirect_action
from app.services.tracked_todo_service import tracked_todo_service
from app.services.triggers.condition_matching import conditions_match
from app.utils.redis_utils import RedisPoolManager
from app.workers.queue import enqueue_worker_job
from shared.py.wide_events import log

COOLDOWN_KEY = "todo_subscription_cooldown:{subscription_id}"


async def dispatch_to_subscribed_todos(
    trigger_name: str,
    trigger_id: str | None,
    user_id: str | None,
    payload: dict[str, Any],
) -> int:
    """Run every matching subscription's action. Returns how many fired."""
    todos = await _resolve_subscribers(trigger_name, trigger_id, user_id)
    if not todos:
        return 0

    fired = 0
    for todo in todos:
        for subscription in todo.trigger_subscriptions:
            try:
                if await _fire_if_matching(todo, subscription, trigger_name, trigger_id, payload):
                    fired += 1
            except Exception as e:
                # One subscription's queue/notification/repository failure must not
                # strand the other matching todos in the same fan-out.
                log.error(
                    "todo_subscription.fire_failed",
                    todo_id=todo.id,
                    subscription_id=subscription.id,
                    trigger_name=trigger_name,
                    error=str(e),
                    error_type=type(e).__name__,
                    exc_info=True,
                )

    log.set_ns("trigger", todo_subscribers=len(todos), todo_actions_fired=fired)
    return fired


async def _resolve_subscribers(
    trigger_name: str, trigger_id: str | None, user_id: str | None
) -> list[TodoDocument]:
    """Both lookup strategies, deduped — a todo can match either way."""
    by_id = await todo_repository.find_active_by_composio_trigger(trigger_id) if trigger_id else []
    by_account = (
        await todo_repository.find_active_by_user_and_trigger(user_id, trigger_name)
        if user_id
        else []
    )

    seen: set[str] = set()
    resolved: list[TodoDocument] = []
    for todo in [*by_id, *by_account]:
        if todo.id is None or todo.id in seen:
            continue
        seen.add(todo.id)
        resolved.append(todo)
    return resolved


async def _fire_if_matching(
    todo: TodoDocument,
    subscription: TriggerSubscription,
    trigger_name: str,
    trigger_id: str | None,
    payload: dict[str, Any],
) -> bool:
    """Gate one subscription on trigger, instance, status, conditions and cooldown, then act."""
    if subscription.trigger_name != trigger_name:
        return False
    # Instance isolation: a resource-scoped subscription must only fire for one of
    # the instances it registered. The account-level lookup returns every todo on
    # this trigger name for the user, so without this gate an event from one
    # resource would fire a todo subscribed to a different one. Account-level
    # subscriptions register no instance and match on user + trigger name alone.
    if subscription.composio_trigger_ids and trigger_id not in subscription.composio_trigger_ids:
        return False
    if subscription.status is not SubscriptionStatus.ACTIVE:
        return False
    if not conditions_match(trigger_name, subscription.conditions, payload, subscription.match):
        return False
    if not await _claim_cooldown(subscription):
        log.info(
            "todo_subscription.cooldown_suppressed",
            todo_id=todo.id,
            subscription_id=subscription.id,
        )
        return False

    await _perform_action(todo, subscription, payload)
    # After the action, not on arrival: an event that was filtered out or
    # suppressed by cooldown is not a fire, and counting it as one would make
    # every funnel off this event read high.
    capture_event(
        todo.user_id,
        AnalyticsEvents.TODO_TRIGGER_FIRED,
        {
            "trigger_name": trigger_name,
            "action": subscription.action.value,
            "resolution": subscription.resolution.value,
            "condition_count": len(subscription.conditions),
        },
    )
    return True


async def _claim_cooldown(subscription: TriggerSubscription) -> bool:
    """Take the subscription's cooldown slot, or report it is still held.

    Set-if-absent rather than read-then-write: two events for one subscription can
    arrive in the same second, and a read-then-write would let both through.

    The key is written here — when the action is about to run — not when an event
    merely arrives, so an event that was filtered out or deferred past a held
    execution lock does not burn the window and suppress the real one.
    """
    if subscription.cooldown_seconds <= 0:
        return True
    client = redis_cache.redis
    if client is None:
        # Redis down: fire rather than suppress. A duplicate action is recoverable;
        # a missed reply-watch is the failure this whole feature exists to prevent.
        log.warning("todo_subscription.cooldown_unavailable", subscription_id=subscription.id)
        return True
    try:
        claimed = await client.set(
            COOLDOWN_KEY.format(subscription_id=subscription.id),
            "1",
            nx=True,
            ex=subscription.cooldown_seconds,
        )
    except (RedisError, OSError) as e:
        log.warning(
            "todo_subscription.cooldown_unavailable",
            subscription_id=subscription.id,
            error=str(e),
            error_type=type(e).__name__,
        )
        return True
    return bool(claimed)


async def _perform_action(
    todo: TodoDocument, subscription: TriggerSubscription, payload: dict[str, Any]
) -> None:
    log.set(
        component="trigger_subscription",
        operation="fire",
        todo_id=todo.id,
        subscription_id=subscription.id,
        trigger_name=subscription.trigger_name,
        subscription_action=subscription.action.value,
    )
    match subscription.action:
        case SubscriptionAction.EXECUTE:
            await _execute(todo, subscription, payload)
        case SubscriptionAction.NOTIFY:
            await _notify(todo, subscription)
        case SubscriptionAction.COMPLETE:
            await _complete(todo, subscription)
        case SubscriptionAction.UNBLOCK:
            await _unblock(todo, subscription)


async def _execute(
    todo: TodoDocument, subscription: TriggerSubscription, payload: dict[str, Any]
) -> None:
    """Enqueue the todo's normal execution, stamped with where it came from."""
    pool = await RedisPoolManager.get_pool()
    await enqueue_worker_job(
        pool,
        "execute_tracked_todo",
        todo.id,
        TriggerOrigin(
            subscription_id=subscription.id,
            trigger_name=subscription.trigger_name,
            payload=payload,
        ),
    )
    log.info("todo_subscription.execution_enqueued", todo_id=todo.id)


async def _notify(todo: TodoDocument, subscription: TriggerSubscription) -> None:
    """Tell the user the event landed. No state change — that is the point."""
    await notification_service.create_notification(
        NotificationRequest(
            user_id=todo.user_id,
            source=NotificationSourceEnum.TODO_TRIGGER,
            content=NotificationContent(
                title=f"Update on: {todo.title}",
                body=f"An event you were watching ({subscription.trigger_name}) just fired.",
                actions=[todo_redirect_action("View todo", todo.id)],
            ),
            metadata={"todo_id": todo.id, "subscription_id": subscription.id},
        )
    )
    log.info("todo_subscription.notified", todo_id=todo.id)


async def _complete(todo: TodoDocument, subscription: TriggerSubscription) -> None:
    """Complete through the ordinary path, which is idempotent and tears down."""
    if todo.id is None:
        return
    await tracked_todo_service.complete_tracked_todo(
        todo.id,
        todo.user_id,
        summary=f"Completed automatically: {subscription.trigger_name} fired.",
    )
    log.info("todo_subscription.completed_todo", todo_id=todo.id)


async def _unblock(todo: TodoDocument, subscription: TriggerSubscription) -> None:
    """Clear the blocking labels, or degrade to notify when there are none.

    A todo that was never blocked has nothing to unblock, and silently doing
    nothing would look identical to the subscription not firing at all.
    """
    if todo.id is None:
        return
    blocking = BLOCKING_LABELS.intersection(todo.labels)
    if not blocking:
        log.info("todo_subscription.unblock_degraded_to_notify", todo_id=todo.id)
        await _notify(todo, subscription)
        return

    await todo_repository.update(
        todo.id,
        user_id=todo.user_id,
        update=TodoUpdate(labels=[lbl for lbl in todo.labels if lbl not in blocking]),
    )
    log.info(
        "todo_subscription.unblocked",
        todo_id=todo.id,
        removed_labels=sorted(blocking),
        unblocked_at=datetime.now(UTC).isoformat(),
    )
