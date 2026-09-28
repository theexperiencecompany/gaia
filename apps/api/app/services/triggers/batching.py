"""Coalescing window for integration trigger events.

Composio's GMAIL_NEW_GMAIL_MESSAGE fires once per message, not once per poll,
so dispatching a run per event turns a busy inbox into 56 runs in three
minutes, each paying the agent's fixed ~53k-token prompt into a cold cache.

Events accumulate in a Redis list while a single deferred ARQ job is in
flight for their owner; when it runs it drains the whole list into one batch.
ARQ's _job_id dedup collapses the fan-out: later events in the window are
rejected as duplicate enqueues and survive only as buffered payloads.

The mechanics are owner-agnostic: a BatchDrainJob names the run that drains a
list, and workflows and tracked todos each supply their own. Only workflow
triggers with a declared poll interval coalesce — a meeting reminder delayed
by its window is a missed meeting.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
import json
from typing import Any
from uuid import uuid4

from redis.exceptions import RedisError

from app.constants.log_tags import LogTag
from app.db.redis import redis_cache
from app.models.trigger_configs import GmailPollInboxConfig
from app.models.workflow_models import TriggerConfig
from app.utils.redis_utils import RedisPoolManager
from app.workers.queue import enqueue_worker_job
from shared.py.wide_events import log

# One list per workflow holding the JSON payloads awaiting their batched run.
TRIGGER_BATCH_KEY = "trigger_batch:{workflow_id}"

WORKFLOW_BATCH_TASK = "execute_workflow_by_id"

# Most events one batched run will carry. A run that swallowed an entire backlog
# would blow the per-request token ceiling and fail wholesale, so the newest
# events win and the overflow is logged rather than silently dropped.
MAX_TRIGGER_BATCH_EVENTS = 50

# The buffer must outlive its own deferred job even when the worker lags — a
# 1-minute window's 4x TTL still lost a batch to a 268s worker outage. The
# floor keeps short windows restart-proof; the multiplier bounds long ones.
TRIGGER_BATCH_TTL_MULTIPLIER = 4
TRIGGER_BATCH_TTL_FLOOR_SECONDS = 60 * 60

# Window for per-email triggers with no declared interval (gmail_new_message).
# Daily, deliberately: everything built on this trigger is digest-shaped, and
# one free-tier run costs the whole free daily budget.
PER_EMAIL_FALLBACK_WINDOW_SECONDS = 24 * 60 * 60


@dataclass(frozen=True)
class BatchDrainJob:
    """The ARQ job that drains a batch; its job_id is what dedupes a window's enqueues."""

    function: str
    args: tuple[object, ...]
    job_id: str
    kwargs: Mapping[str, object] = field(default_factory=dict)


def coalesce_window_seconds(trigger_config: TriggerConfig) -> int:
    """Seconds to batch this trigger's events over, or 0 to fire immediately.

    A poll trigger's window IS its configured interval, so "polls your inbox
    every N minutes" finally describes what the workflow does. The account-level
    per-email trigger declares no interval at all, so it gets the daily fallback
    — it fires once per inbound email, which is never a cadence anyone chose.
    """
    trigger_data = trigger_config.trigger_data
    if isinstance(trigger_data, GmailPollInboxConfig):
        return trigger_data.interval * 60
    if trigger_config.trigger_name == "gmail_new_message":
        return PER_EMAIL_FALLBACK_WINDOW_SECONDS
    return 0


def _batch_ttl_seconds(window_seconds: int) -> int:
    return max(window_seconds * TRIGGER_BATCH_TTL_MULTIPLIER, TRIGGER_BATCH_TTL_FLOOR_SECONDS)


async def buffer_batch_event(
    batch_key: str,
    data: Mapping[str, object],
    window_seconds: int,
    drain: BatchDrainJob,
    log_fields: Mapping[str, str],
) -> bool:
    """Add one event to a batch and ensure its drain run is scheduled window_seconds out.

    Returns False when the batch is unreachable, so the caller can fall back to
    dispatching immediately — a burst of runs is bad, but silently losing the
    user's triggers is worse.
    """
    client = redis_cache.redis
    if client is None:
        log.warning(
            f"{LogTag.TRIGGER} Redis unavailable — trigger event cannot be batched", **log_fields
        )
        return False

    try:
        buffered = await client.rpush(batch_key, json.dumps(data, default=str))
        if buffered > MAX_TRIGGER_BATCH_EVENTS:
            await client.ltrim(batch_key, -MAX_TRIGGER_BATCH_EVENTS, -1)
            log.warning(
                f"{LogTag.TRIGGER} Trigger batch full — oldest events dropped",
                **log_fields,
                dropped_count=buffered - MAX_TRIGGER_BATCH_EVENTS,
                max_batch=MAX_TRIGGER_BATCH_EVENTS,
            )
        await client.expire(batch_key, _batch_ttl_seconds(window_seconds))
    except RedisError as exc:
        # Same degradation as a missing client: the caller dispatches immediately.
        # If the rpush landed before the failure the event may ALSO ride a later
        # batch — a rare duplicate is the right trade against dropping it.
        log.warning(
            f"{LogTag.TRIGGER} Redis write failed — trigger event cannot be batched",
            **log_fields,
            error=str(exc),
            error_type=type(exc).__name__,
        )
        return False

    # While the drain run is queued or executing, every further event's enqueue is
    # deduped away on its job id and rides the buffer. `keep_result = 0`
    # (WorkerSettings) frees the id when the run ends, opening a fresh window.
    try:
        pool = await RedisPoolManager.get_pool()
        job = await enqueue_worker_job(
            pool,
            drain.function,
            *drain.args,
            _job_id=drain.job_id,
            _defer_by=window_seconds,
            **drain.kwargs,
        )
    except Exception as exc:
        # Buffered but nothing scheduled to drain it — without the fallback it
        # sits until the next event or expires unprocessed. Same duplicate trade
        # as the Redis-write failure above.
        log.warning(
            f"{LogTag.TRIGGER} Batch run scheduling failed — dispatching event immediately",
            **log_fields,
            error=str(exc),
            error_type=type(exc).__name__,
        )
        return False

    log.info(
        f"{LogTag.TRIGGER} Trigger event buffered for batched run",
        **log_fields,
        buffered_count=min(buffered, MAX_TRIGGER_BATCH_EVENTS),
        window_seconds=window_seconds,
        scheduled_run=job is not None,
    )
    return True


async def buffer_trigger_event(
    workflow_id: str,
    user_id: str,
    data: dict[str, Any],
    window_seconds: int,
    context: dict[str, Any],
) -> bool:
    """Add one event to the workflow's batch; the workflow itself is the drain run."""
    key = TRIGGER_BATCH_KEY.format(workflow_id=workflow_id)
    return await buffer_batch_event(
        key,
        data,
        window_seconds,
        BatchDrainJob(
            function=WORKFLOW_BATCH_TASK,
            args=(workflow_id, {**context, "trigger_batch_key": key}),
            job_id=f"trigger_batch:{workflow_id}",
        ),
        {"workflow_id": workflow_id, "user_id": user_id},
    )


async def drain_trigger_batch(batch_key: str) -> list[dict[str, Any]] | None:
    """Take every buffered event for this batch, leaving the key empty.

    Read-and-delete in one transaction so events arriving mid-drain open the
    next window instead of being lost to a run that already built its prompt.
    Returns None when Redis is unavailable, rather than a false drained-empty.
    """
    client = redis_cache.redis
    if client is None:
        log.warning(f"{LogTag.TRIGGER} Redis unavailable — trigger batch cannot be drained")
        return None

    async with client.pipeline(transaction=True) as pipe:
        pipe.lrange(batch_key, 0, -1)
        pipe.delete(batch_key)
        raw_events, _ = await pipe.execute()

    events: list[dict[str, Any]] = []
    for raw in raw_events:
        try:
            events.append(json.loads(raw))
        except ValueError:
            log.warning(
                f"{LogTag.TRIGGER} Discarding unparseable buffered trigger event",
                batch_key=batch_key,
            )
    return events


async def schedule_drain_if_refilled(
    batch_key: str,
    window_seconds: int,
    drain: BatchDrainJob,
    log_fields: Mapping[str, str],
) -> bool:
    """Schedule a follow-up drain when events landed while the current run held the batch.

    An event arriving mid-run buffers fine, but its enqueue is rejected — the
    run's job id is still occupied — so without this it would sit stranded
    until the next event. Called by the worker when a run ends.
    """
    client = redis_cache.redis
    if client is None or await client.llen(batch_key) == 0:
        return False

    # Renew the buffer's TTL alongside the new job: an owner rescheduled over and
    # over (budget wall all day on a short window) would otherwise see the buffer's
    # original TTL expire mid-cycle, silently dropping the events it exists to drain.
    await client.expire(batch_key, _batch_ttl_seconds(window_seconds))

    pool = await RedisPoolManager.get_pool()
    await enqueue_worker_job(
        pool,
        drain.function,
        *drain.args,
        _job_id=drain.job_id,
        _defer_by=window_seconds,
        **drain.kwargs,
    )
    log.info(
        f"{LogTag.TRIGGER} Trigger batch refilled mid-run — follow-up run scheduled",
        **log_fields,
        window_seconds=window_seconds,
    )
    return True


async def reschedule_if_refilled(
    workflow_id: str, batch_key: str, window_seconds: int, context: dict[str, Any]
) -> bool:
    """Schedule the workflow's follow-up run under a fresh id; this run still holds its own."""
    return await schedule_drain_if_refilled(
        batch_key,
        window_seconds,
        BatchDrainJob(
            function=WORKFLOW_BATCH_TASK,
            args=(
                workflow_id,
                {
                    **{k: v for k, v in context.items() if k != "trigger_data"},
                    "trigger_batch_key": batch_key,
                },
            ),
            job_id=f"trigger_batch:{workflow_id}:refill:{uuid4().hex[:12]}",
        ),
        {"workflow_id": workflow_id},
    )
