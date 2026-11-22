"""A GAIA task's app-event window: one run per window, later events ride the next.

The first matching event opens the window and runs the task at once, because a reply
should not wait. Events inside the window buffer on the task's batch, and one drain run
at the window's end carries them together and opens the next window. The window key
holds its end, so every path that schedules a drain targets that end and ARQ dedupes
them into one job. An event held for the end of the user's quiet hours stretches the
window to that end. Events that reach a task the system paused are kept apart and
replayed when it resumes.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from redis.exceptions import RedisError

from app.constants.tasks import RUN_TASK_JOB
from app.constants.todos import PAUSED_TRIGGER_HOLD_TTL
from app.db.redis import redis_cache
from app.models.task_models import TaskDocument
from app.models.trigger_subscription_models import (
    SubscriptionAction,
    TriggerOrigin,
    TriggerSubscription,
    TriggerSubscriptionStatus,
)
from app.services.triggers.batching import (
    MAX_TRIGGER_BATCH_EVENTS,
    BatchDrainJob,
    buffer_batch_event,
    drain_trigger_batch,
    schedule_drain_if_refilled,
)
from app.utils.occurrence import occurrence_stamp
from shared.py.wide_events import log

#: Every subscription of a task buffers onto one list, so they coalesce together.
TASK_EVENT_BATCH_KEY = "trigger_batch:task:{task_id}"
#: Holds the open window's end (unix seconds) and expires with it.
TASK_EVENT_WINDOW_KEY = "task_event_window:{task_id}"
#: What the first event of a window writes to claim its run: the window has no end until
#: that run starts, so events held meanwhile wait only for the run, not the window.
TASK_EVENT_WINDOW_CLAIMED = "claimed"
TASK_EVENT_DRAIN_JOB_ID = "trigger_batch:task:{task_id}:{window_end}"
#: Events that reached a task the system paused; its resume replays them.
TASK_EVENT_HOLD_KEY = "trigger_hold:task:{task_id}"
#: Held for a subscription's cooldown once it acts without a run (notify, complete, unblock).
TASK_SUBSCRIPTION_COOLDOWN_KEY = "task_subscription_cooldown:{subscription_id}"


@dataclass(frozen=True)
class EventWindow:
    """The window a run of a task on its app events opens now."""

    key: str
    seconds: int
    end: int


def event_window(task: TaskDocument) -> EventWindow:
    """Size the window by the longest cooldown among the task's active run subscriptions."""
    seconds = max(
        (
            subscription.cooldown_seconds
            for subscription in task.subscriptions
            if subscription.action is SubscriptionAction.EXECUTE
            and subscription.status is TriggerSubscriptionStatus.ACTIVE
        ),
        default=0,
    )
    now = occurrence_stamp(datetime.now(UTC))
    return EventWindow(
        key=TASK_EVENT_WINDOW_KEY.format(task_id=task.id), seconds=seconds, end=now + seconds
    )


def subscription_cooldown(subscription: TriggerSubscription) -> EventWindow:
    """Return the cooldown a subscription that acts without a run holds between two events."""
    seconds = subscription.cooldown_seconds
    return EventWindow(
        key=TASK_SUBSCRIPTION_COOLDOWN_KEY.format(subscription_id=subscription.id),
        seconds=seconds,
        end=occurrence_stamp(datetime.now(UTC)) + seconds,
    )


async def claim_event_window(window: EventWindow) -> bool:
    """Take the window's one immediate run; False while a run already holds it.

    Set-if-absent, so two events in the same second cannot both run. Redis being down
    runs the event: a duplicate run is recoverable, a missed reply is not.
    """
    if window.seconds <= 0:
        return True
    client = redis_cache.redis
    if client is None:
        log.warning("task_event.window_unavailable", window_key=window.key)
        return True
    try:
        claimed = await client.set(
            window.key, TASK_EVENT_WINDOW_CLAIMED, nx=True, ex=window.seconds
        )
    except (RedisError, OSError) as e:
        log.warning(
            "task_event.window_unavailable",
            window_key=window.key,
            error=str(e),
            error_type=type(e).__name__,
        )
        return True
    return bool(claimed)


async def open_event_window(window: EventWindow) -> None:
    """Open (or move on) the window for a run starting now; a zero window stays shut.

    Redis failing only costs the coalescing: the run already holds its events, so it goes
    on and later events run at once instead of waiting.
    """
    if window.seconds <= 0:
        return
    client = redis_cache.redis
    if client is None:
        log.warning("task_event.window_unavailable", window_key=window.key)
        return
    try:
        await client.set(window.key, str(window.end), ex=window.seconds)
    except (RedisError, OSError) as e:
        log.warning(
            "task_event.window_unavailable",
            window_key=window.key,
            error=str(e),
            error_type=type(e).__name__,
        )


async def event_window_end(task_id: str) -> int | None:
    """Return the end of the window a started run opened, or None when no run has opened one."""
    client = redis_cache.redis
    if client is None:
        return None
    raw = await client.get(TASK_EVENT_WINDOW_KEY.format(task_id=task_id))
    if raw is None or raw == TASK_EVENT_WINDOW_CLAIMED:
        return None
    return int(raw)


async def _drain_slot(task_id: str) -> tuple[int, int]:
    """Return when the task's buffered events run (its window's end, or now) and the seconds until then."""
    now = occurrence_stamp(datetime.now(UTC))
    window_end = max(await event_window_end(task_id) or now, now)
    return window_end, window_end - now


def _drain_job(task_id: str, window_end: int) -> BatchDrainJob:
    return BatchDrainJob(
        function=RUN_TASK_JOB,
        args=(task_id, None),
        job_id=TASK_EVENT_DRAIN_JOB_ID.format(task_id=task_id, window_end=window_end),
        kwargs={"trigger_window": window_end},
    )


async def buffer_task_event(task_id: str, event: TriggerOrigin) -> bool:
    """Hold one event for the run at the end of the task's window; False when it could not be held."""
    window_end, defer_seconds = await _drain_slot(task_id)
    return await buffer_batch_event(
        TASK_EVENT_BATCH_KEY.format(task_id=task_id),
        event.model_dump(),
        defer_seconds,
        _drain_job(task_id, window_end),
        {"task_id": task_id},
    )


async def stretch_event_window(task_id: str, until: datetime) -> bool:
    """Hold the task's window open until at least until; False when it could not be stretched."""
    key = TASK_EVENT_WINDOW_KEY.format(task_id=task_id)
    client = redis_cache.redis
    if client is None:
        log.warning("task_event.window_unavailable", window_key=key)
        return False
    now = occurrence_stamp(datetime.now(UTC))
    try:
        window_end = max(occurrence_stamp(until), await event_window_end(task_id) or now)
        await client.set(key, str(window_end), ex=max(window_end - now, 1))
    except (RedisError, OSError) as e:
        log.warning(
            "task_event.window_unavailable",
            window_key=key,
            error=str(e),
            error_type=type(e).__name__,
        )
        return False
    return True


async def buffer_task_event_until(task_id: str, event: TriggerOrigin, until: datetime) -> bool:
    """Hold one event for a run no sooner than until; False when it could not be held."""
    return await stretch_event_window(task_id, until) and await buffer_task_event(task_id, event)


async def buffered_task_events(task_id: str) -> list[TriggerOrigin]:
    """Return the events buffered for the task's next run, oldest first, leaving them buffered."""
    client = redis_cache.redis
    if client is None:
        return []
    raw = await client.lrange(TASK_EVENT_BATCH_KEY.format(task_id=task_id), 0, -1)
    return [TriggerOrigin.model_validate_json(event) for event in raw]


async def drain_task_events(task_id: str) -> list[TriggerOrigin] | None:
    """Take every event buffered for the task, oldest first; None when Redis is unavailable."""
    events = await drain_trigger_batch(TASK_EVENT_BATCH_KEY.format(task_id=task_id))
    if events is None:
        return None
    return [TriggerOrigin.model_validate(event) for event in events]


async def reschedule_task_event_drain(task_id: str) -> bool:
    """Schedule the drain run for events that landed while a run held the task."""
    window_end, defer_seconds = await _drain_slot(task_id)
    return await schedule_drain_if_refilled(
        TASK_EVENT_BATCH_KEY.format(task_id=task_id),
        defer_seconds,
        _drain_job(task_id, window_end),
        {"task_id": task_id},
    )


async def keep_event_while_paused(task_id: str, event: TriggerOrigin) -> bool:
    """Keep one event for the task's resume without scheduling a run; False when it could not be kept."""
    client = redis_cache.redis
    if client is None:
        log.warning("task_event.hold_unavailable", task_id=task_id)
        return False
    key = TASK_EVENT_HOLD_KEY.format(task_id=task_id)
    try:
        await client.rpush(key, event.model_dump_json())
        await client.ltrim(key, -MAX_TRIGGER_BATCH_EVENTS, -1)
        await client.expire(key, int(PAUSED_TRIGGER_HOLD_TTL.total_seconds()))
    except (RedisError, OSError) as e:
        log.warning(
            "task_event.hold_unavailable",
            task_id=task_id,
            error=str(e),
            error_type=type(e).__name__,
        )
        return False
    return True


async def release_events_kept_while_paused(task_id: str) -> int:
    """Move the events kept while the task was paused onto its batch and schedule their run.

    Each event moves atomically, so it is replayed once; a failure to schedule raises with
    the events already on the batch, where the next release schedules them.
    """
    client = redis_cache.redis
    if client is None:
        raise RuntimeError(f"Redis is unavailable, so the events kept for {task_id} cannot replay")
    hold_key = TASK_EVENT_HOLD_KEY.format(task_id=task_id)
    batch_key = TASK_EVENT_BATCH_KEY.format(task_id=task_id)
    moved = 0
    while await client.lmove(hold_key, batch_key) is not None:
        moved += 1
    await reschedule_task_event_drain(task_id)
    return moved
