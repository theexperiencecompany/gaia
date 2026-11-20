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
import hashlib
import json

from redis.exceptions import RedisError

from app.constants.integrations import EVENT_ACCOUNT_ID_KEY
from app.constants.todos import BLOCKING_LABELS, EXECUTE_TRACKED_TODO_TASK, TodoActivityEvent
from app.constants.trigger_gates import GateOwner
from app.db.redis import redis_cache
from app.db.repositories.todos import todo_repository
from app.models.notification.notification_models import (
    NotificationContent,
    NotificationRequest,
    NotificationSourceEnum,
    notification_id,
)
from app.models.todo_models import ExternalRefSource, TodoDocument, TodoUpdate
from app.models.trigger_subscription_models import (
    ConditionOperator,
    SubscriptionAction,
    TriggerOrigin,
    TriggerSubscription,
    TriggerSubscriptionStatus,
)
from app.services.analytics_service import capture
from app.services.notification_service import notification_service
from app.services.todo_activity import record_activity
from app.services.todos.todo_notifications import todo_redirect_action
from app.services.tracked_todo_service import tracked_todo_service
from app.services.triggers.condition_matching import conditions_match
from app.services.triggers.todo_trigger_window import (
    TODO_TRIGGER_WINDOW_CLAIMED,
    buffer_todo_trigger_event,
    buffer_todo_trigger_event_until,
    trigger_window,
)
from app.services.triggers.trigger_gate import (
    GateBypass,
    GatedJob,
    GateHold,
    GateRun,
    GateSkip,
    automation_text,
    decide_gate,
)
from app.utils.redis_utils import RedisPoolManager
from app.workers.queue import enqueue_worker_job
from shared.py.analytics import UserId
from shared.py.analytics.catalog.attribution import Trigger
from shared.py.analytics.catalog.todos import TodosTriggerFired
from shared.py.analytics.context import analytics_context, worker_context
from shared.py.wide_events import log

COOLDOWN_KEY = "todo_subscription_cooldown:{subscription_id}"


async def dispatch_to_subscribed_todos(
    trigger_name: str,
    trigger_id: str | None,
    user_id: str | None,
    payload: dict[str, object],
) -> int:
    """Run every matching subscription's action, as integration-triggered work. Returns how many fired."""
    with analytics_context(worker_context(Trigger.INTEGRATION_TRIGGER)):
        return await _dispatch(trigger_name, trigger_id, user_id, payload)


async def _dispatch(
    trigger_name: str,
    trigger_id: str | None,
    user_id: str | None,
    payload: dict[str, object],
) -> int:
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


def _tracked_threads(todo: TodoDocument, subscription: TriggerSubscription) -> frozenset[str]:
    """Return the Gmail threads the todo owns or the subscription is pinned to."""
    pinned = {
        str(condition.value)
        for condition in subscription.conditions
        if condition.field_name == "thread_id" and condition.operator is ConditionOperator.EQUALS
    }
    ref = todo.external_ref
    if ref is not None and ref.source is ExternalRefSource.GMAIL_THREAD:
        pinned.add(ref.id)
    return frozenset(pinned)


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
    if (
        subscription.account_id is not None
        and payload.get(EVENT_ACCOUNT_ID_KEY) != subscription.account_id
    ):
        return False
    if not conditions_match(trigger_name, subscription.conditions, payload, subscription.match):
        return False
    # Before any window or cooldown claim: a skipped event must not burn the slot
    # the next real one needs, nor read as handled. Only an EXECUTE subscription has a gate.
    verdict = await decide_gate(
        subscription.gate,
        GatedJob(
            owner=GateOwner.TODO,
            id=subscription.id,
            user_id=todo.user_id,
            automation=automation_text(todo.title, todo.description),
            tracked_threads=_tracked_threads(todo, subscription),
        ),
        trigger_name=trigger_name,
        payload=payload,
    )
    if isinstance(verdict, GateSkip):
        return False
    if not isinstance(verdict, GateRun):
        # Quiet hours decide when it runs: at their end, or now because it cannot wait.
        coalesced = isinstance(verdict, GateHold)
    elif subscription.action is SubscriptionAction.EXECUTE:
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

    await fire_subscription(todo, subscription, payload, coalesced=coalesced, verdict=verdict)
    return True


async def fire_subscription(
    todo: TodoDocument,
    subscription: TriggerSubscription,
    payload: dict[str, object],
    *,
    coalesced: bool = False,
    verdict: GateRun | GateHold | GateBypass = GateRun(),
) -> None:
    """Run a subscription's action for an event already matched to it, and count the fire.

    A held verdict runs it when the user's quiet hours end; a bypass runs it now.
    """
    await _perform_action(todo, subscription, payload, coalesced=coalesced, verdict=verdict)
    # After the action, not on arrival: an event that was filtered out or
    # suppressed by cooldown is not a fire, and counting it as one would make
    # every funnel off this event read high.
    capture(
        UserId(todo.user_id),
        TodosTriggerFired(
            trigger_name=subscription.trigger_name,
            action=subscription.action.value,
            resolution=subscription.resolution.value,
            condition_count=len(subscription.conditions),
            coalesced=coalesced,
        ),
    )


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


def _fire_note(verdict: GateRun | GateHold | GateBypass, *, coalesced: bool) -> str:
    """Say when the fired action runs, for the trigger_fired activity line."""
    match verdict:
        case GateHold():
            return "; held until your quiet hours end"
        case GateBypass():
            return f". {verdict.stamp.summary}"
        case GateRun():
            return "; held for the todo's next run" if coalesced else ""


async def _perform_action(
    todo: TodoDocument,
    subscription: TriggerSubscription,
    payload: dict[str, object],
    *,
    coalesced: bool,
    verdict: GateRun | GateHold | GateBypass,
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
    note = _fire_note(verdict, coalesced=coalesced)
    await record_activity(
        todo.id,
        todo.user_id,
        TodoActivityEvent.TRIGGER_FIRED,
        f"{subscription.trigger_name} matched; action: {subscription.action.value}{note}",
    )
    try:
        match subscription.action:
            case SubscriptionAction.EXECUTE:
                await _execute(todo, subscription, payload, coalesced=coalesced, verdict=verdict)
            case SubscriptionAction.NOTIFY:
                await _notify(todo, subscription, payload)
            case SubscriptionAction.COMPLETE:
                await _complete(todo, subscription)
            case SubscriptionAction.UNBLOCK:
                await _unblock(todo, subscription, payload)
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
    verdict: GateRun | GateHold | GateBypass,
) -> None:
    """Run the todo now, stamped with where it came from, or hold the event for a later run.

    A held event that cannot be buffered runs now: an extra run is recoverable,
    a lost reply is not.
    """
    origin = TriggerOrigin(
        subscription_id=subscription.id,
        trigger_name=subscription.trigger_name,
        payload=payload,
        quiet_hours_bypass=verdict.stamp if isinstance(verdict, GateBypass) else None,
    )
    if isinstance(verdict, GateHold):
        if await buffer_todo_trigger_event_until(todo.id, origin, verdict.until):
            log.info("todo_subscription.execution_held_for_quiet_hours", todo_id=todo.id)
            return
    elif coalesced and await buffer_todo_trigger_event(todo.id, origin):
        log.info("todo_subscription.execution_coalesced", todo_id=todo.id)
        return
    pool = await RedisPoolManager.get_pool()
    await enqueue_worker_job(pool, EXECUTE_TRACKED_TODO_TASK, todo.id, origin)
    log.info("todo_subscription.execution_enqueued", todo_id=todo.id)


async def _notify(
    todo: TodoDocument, subscription: TriggerSubscription, payload: dict[str, object]
) -> None:
    """Tell the user the event landed, once per event however often it is redelivered."""
    event = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
    await notification_service.notify(
        NotificationRequest(
            id=notification_id(todo.user_id, "todo_trigger", subscription.id, event),
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


async def _unblock(
    todo: TodoDocument, subscription: TriggerSubscription, payload: dict[str, object]
) -> None:
    """Clear the blocking labels, or degrade to notify when there are none.

    A todo that was never blocked has nothing to unblock, and silently doing
    nothing would look identical to the subscription not firing at all.
    """
    if todo.id is None:
        return
    blocking = BLOCKING_LABELS.intersection(todo.labels)
    if not blocking:
        log.info("todo_subscription.unblock_degraded_to_notify", todo_id=todo.id)
        await _notify(todo, subscription, payload)
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
