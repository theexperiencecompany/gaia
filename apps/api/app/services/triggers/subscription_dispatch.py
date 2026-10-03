"""Fan a fired Composio trigger out to the tracked todos subscribed to it.

Called from TriggerHandler.process_event before the no-matching-workflow
short-circuit, because an event with no workflow can still have a todo waiting on
it — and today that event is dropped.

Resolution mirrors GmailTriggerHandler.find_workflows and runs both
strategies, for the same reason it does: per-resource triggers are found by the
Composio instance id on the webhook, while account-level triggers (Gmail) have no
instance to register and can only be found by user and trigger name. A lookup on
instance ids alone finds nothing for Gmail, which is the entire reply-watching
case.
"""

from datetime import UTC, datetime

from redis.exceptions import RedisError

from app.constants.todos import BLOCKING_LABELS, EXECUTE_TRACKED_TODO_TASK, TodoActivityEvent
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
    TriggerOrigin,
    TriggerSubscription,
    TriggerSubscriptionStatus,
)
from app.services.analytics_service import AnalyticsEvents, capture_event
from app.services.notification_service import notification_service
from app.services.todo_activity import record_activity
from app.services.todos.todo_notifications import todo_redirect_action
from app.services.tracked_todo_service import tracked_todo_service
from app.services.triggers.condition_matching import conditions_match
from app.services.triggers.todo_trigger_window import (
    TODO_TRIGGER_WINDOW_CLAIMED,
    buffer_todo_trigger_event,
    trigger_window,
)
from app.utils.redis_utils import RedisPoolManager
from app.workers.queue import enqueue_worker_job
from shared.py.wide_events import log

COOLDOWN_KEY = "todo_subscription_cooldown:{subscription_id}"


async def dispatch_to_subscribed_todos(
    trigger_name: str,
    trigger_id: str | None,
    user_id: str | None,
    payload: dict[str, object],
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
    payload: dict[str, object],
) -> bool:
    """Gate one subscription on trigger, instance, status, conditions and cooldown, then act."""
    if subscription.trigger_name != trigger_name:
        return False
    # A resource-scoped subscription must only fire for one of the instances it
    # registered — without this gate, an event from one resource would fire a
    # todo subscribed to a different one. Account-level subscriptions register no instance.
    if subscription.composio_trigger_ids and trigger_id not in subscription.composio_trigger_ids:
        return False
    if subscription.status is not TriggerSubscriptionStatus.ACTIVE:
        return False
    if not conditions_match(trigger_name, subscription.conditions, payload, subscription.match):
        return False
    if subscription.action is SubscriptionAction.EXECUTE:
        # A run costs an agent turn, so the todo runs once per window and an event
        # inside it rides the next run instead of being dropped.
        window = trigger_window(todo)
        coalesced = not await _claim_slot(
            subscription, window.key, window.seconds, TODO_TRIGGER_WINDOW_CLAIMED
        )
    elif await _claim_slot(
        subscription,
        COOLDOWN_KEY.format(subscription_id=subscription.id),
        subscription.cooldown_seconds,
    ):
        coalesced = False
    else:
        log.info(
            "todo_subscription.cooldown_suppressed",
            todo_id=todo.id,
            subscription_id=subscription.id,
        )
        return False

    await _perform_action(todo, subscription, payload, coalesced=coalesced)
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
            "coalesced": coalesced,
        },
    )
    return True


async def _claim_slot(
    subscription: TriggerSubscription, key: str, seconds: int, value: str = "1"
) -> bool:
    """Take a cooldown or trigger-window slot for seconds, or report it is still held.

    Set-if-absent rather than read-then-write: two events for one subscription
    can arrive in the same second, and a read-then-write would let both
    through. The key is written when the action is about to run, not on mere
    arrival, so a filtered-out event doesn't burn the window.
    """
    if seconds <= 0:
        return True
    client = redis_cache.redis
    if client is None:
        # Redis down: fire rather than suppress. A duplicate action is recoverable;
        # a missed reply-watch is the failure this whole feature exists to prevent.
        log.warning("todo_subscription.cooldown_unavailable", subscription_id=subscription.id)
        return True
    try:
        claimed = await client.set(key, value, nx=True, ex=seconds)
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
    todo: TodoDocument,
    subscription: TriggerSubscription,
    payload: dict[str, object],
    *,
    coalesced: bool,
) -> None:
    log.set(
        component="trigger_subscription",
        operation="fire",
        todo_id=todo.id,
        subscription_id=subscription.id,
        trigger_name=subscription.trigger_name,
        subscription_action=subscription.action.value,
        coalesced=coalesced,
    )
    held = "; held for the todo's next run" if coalesced else ""
    await record_activity(
        todo.id,
        todo.user_id,
        TodoActivityEvent.TRIGGER_FIRED,
        f"{subscription.trigger_name} matched; action: {subscription.action.value}{held}",
    )
    try:
        match subscription.action:
            case SubscriptionAction.EXECUTE:
                await _execute(todo, subscription, payload, coalesced=coalesced)
            case SubscriptionAction.NOTIFY:
                await _notify(todo, subscription)
            case SubscriptionAction.COMPLETE:
                await _complete(todo, subscription)
            case SubscriptionAction.UNBLOCK:
                await _unblock(todo, subscription)
    except Exception as e:
        # The fire is already on the timeline; without this it reads as if the action ran.
        await record_activity(
            todo.id,
            todo.user_id,
            TodoActivityEvent.TRIGGER_ACTION_FAILED,
            f"{subscription.action.value} failed: {type(e).__name__}",
        )
        raise


async def _execute(
    todo: TodoDocument,
    subscription: TriggerSubscription,
    payload: dict[str, object],
    *,
    coalesced: bool,
) -> None:
    """Run the todo now, stamped with where it came from, or hold the event for its next run.

    A held event that cannot be buffered runs now: an extra run is recoverable,
    a lost reply is not.
    """
    origin = TriggerOrigin(
        subscription_id=subscription.id,
        trigger_name=subscription.trigger_name,
        payload=payload,
    )
    if coalesced and await buffer_todo_trigger_event(todo.id, origin):
        log.info("todo_subscription.execution_coalesced", todo_id=todo.id)
        return
    pool = await RedisPoolManager.get_pool()
    await enqueue_worker_job(pool, EXECUTE_TRACKED_TODO_TASK, todo.id, origin)
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
