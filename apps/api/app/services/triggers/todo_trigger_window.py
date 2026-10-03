"""A tracked todo's trigger window: one agent run per window, later events ride the next.

The first matching event opens the window and runs the todo at once, because a
reply should not wait. Events inside the window buffer on the todo's batch and
one drain run at the window's end delivers them together, opening the next
window. The window key holds its end, so every path that schedules a drain
targets that end and ARQ dedupes them into one job.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from redis.exceptions import RedisError

from app.constants.todos import EXECUTE_TRACKED_TODO_TASK
from app.db.redis import redis_cache
from app.models.todo_models import TodoDocument
from app.models.trigger_subscription_models import (
    SubscriptionAction,
    TriggerOrigin,
    TriggerSubscriptionStatus,
)
from app.services.triggers.batching import (
    BatchDrainJob,
    buffer_batch_event,
    drain_trigger_batch,
    schedule_drain_if_refilled,
)
from app.utils.occurrence import occurrence_stamp
from shared.py.wide_events import log

# Every subscription of a todo buffers onto one list, so they coalesce together.
TODO_TRIGGER_BATCH_KEY = "trigger_batch:todo:{todo_id}"
# Holds the open window's end (unix seconds) and expires with it.
TODO_TRIGGER_WINDOW_KEY = "todo_trigger_window:{todo_id}"
# What the first event of a window writes to claim its run: the window has no end
# until that run starts, so events held meanwhile wait only for the lock, not the window.
TODO_TRIGGER_WINDOW_CLAIMED = "claimed"
TODO_TRIGGER_DRAIN_JOB_ID = "trigger_batch:todo:{todo_id}:{window_end}"


@dataclass(frozen=True)
class TriggerWindow:
    """The window a trigger run of a todo opens now."""

    key: str
    seconds: int
    end: int


def trigger_window(todo: TodoDocument) -> TriggerWindow:
    """Size the window by the longest cooldown among the todo's active execute subscriptions."""
    seconds = max(
        (
            subscription.cooldown_seconds
            for subscription in todo.trigger_subscriptions
            if subscription.action is SubscriptionAction.EXECUTE
            and subscription.status is TriggerSubscriptionStatus.ACTIVE
        ),
        default=0,
    )
    now = occurrence_stamp(datetime.now(UTC))  # pragma: no mutate — naive now() stamps the same
    return TriggerWindow(
        key=TODO_TRIGGER_WINDOW_KEY.format(todo_id=todo.id), seconds=seconds, end=now + seconds
    )


async def open_trigger_window(window: TriggerWindow) -> None:
    """Open (or move on) the window for a trigger run starting now; a zero window stays shut.

    Redis failing only costs the coalescing: the run already holds its events,
    so it goes on and later events run at once instead of waiting.
    """
    if window.seconds <= 0:
        return
    client = redis_cache.redis
    if client is None:
        log.warning("todo_trigger.window_unavailable", window_key=window.key)
        return
    try:
        await client.set(window.key, str(window.end), ex=window.seconds)
    except (RedisError, OSError) as e:
        log.warning(
            "todo_trigger.window_unavailable",
            window_key=window.key,
            error=str(e),
            error_type=type(e).__name__,
        )


async def trigger_window_end(todo_id: str) -> int | None:
    """Return the end of the window a started run opened, or None when no run has opened one."""
    client = redis_cache.redis
    if client is None:
        return None
    raw = await client.get(TODO_TRIGGER_WINDOW_KEY.format(todo_id=todo_id))
    if raw is None or raw == TODO_TRIGGER_WINDOW_CLAIMED:
        return None
    return int(raw)


async def _drain_slot(todo_id: str) -> tuple[int, int]:
    """Return when the todo's buffered events run (its window's end, or now) and the seconds until then."""
    now = occurrence_stamp(datetime.now(UTC))  # pragma: no mutate — naive now() stamps the same
    window_end = max(await trigger_window_end(todo_id) or now, now)
    return window_end, window_end - now


def _drain_job(todo_id: str, window_end: int) -> BatchDrainJob:
    return BatchDrainJob(
        function=EXECUTE_TRACKED_TODO_TASK,
        args=(todo_id,),
        job_id=TODO_TRIGGER_DRAIN_JOB_ID.format(todo_id=todo_id, window_end=window_end),
        kwargs={"trigger_window": window_end},
    )


async def buffer_todo_trigger_event(todo_id: str, event: TriggerOrigin) -> bool:
    """Hold one event for the run at the end of the todo's window; False when it could not be held."""
    window_end, defer_seconds = await _drain_slot(todo_id)
    return await buffer_batch_event(
        TODO_TRIGGER_BATCH_KEY.format(todo_id=todo_id),
        event.model_dump(),
        defer_seconds,
        _drain_job(todo_id, window_end),
        {"todo_id": todo_id},
    )


async def drain_todo_trigger_events(todo_id: str) -> list[TriggerOrigin] | None:
    """Take every event held for the todo, oldest first; None when Redis is unavailable."""
    events = await drain_trigger_batch(TODO_TRIGGER_BATCH_KEY.format(todo_id=todo_id))
    if events is None:
        return None
    return [TriggerOrigin.model_validate(event) for event in events]


async def reschedule_todo_trigger_drain(todo_id: str) -> bool:
    """Schedule the drain run for events that landed while a run held the todo."""
    window_end, defer_seconds = await _drain_slot(todo_id)
    return await schedule_drain_if_refilled(
        TODO_TRIGGER_BATCH_KEY.format(todo_id=todo_id),
        defer_seconds,
        _drain_job(todo_id, window_end),
        {"todo_id": todo_id},
    )
