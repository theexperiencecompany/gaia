"""Coalescing window for poll-based integration triggers.

Composio's ``GMAIL_NEW_GMAIL_MESSAGE`` fires **once per message**: the trigger's
``interval`` controls how often Composio polls Gmail, not how many messages ride
in one webhook. Dispatching a workflow run per event therefore turns a busy
inbox into one full agent run per email — 56 runs in three minutes for a user
with a normal morning, each paying the agent's fixed ~53k-token prompt and
racing the others into a cold prompt cache.

This module gives those triggers the batching their config already promises.
Events accumulate in a Redis list while a single deferred ARQ job is in flight
for the workflow; when the job runs it drains the whole list and hands the agent
one batch. ARQ's ``_job_id`` dedup is what collapses the fan-out: the first
event schedules the run, every later event in the window is rejected as a
duplicate enqueue and survives only as a buffered payload.

Only triggers with a declared poll interval coalesce. Everything else keeps
firing immediately, because a trigger like ``calendar_event_starting_soon`` is
worthless late — a meeting reminder delayed by its window is a missed meeting.
"""

import json
from typing import Any

from app.constants.log_tags import LogTag
from app.db.redis import redis_cache
from app.models.trigger_configs import GmailPollInboxConfig
from app.models.workflow_models import TriggerConfig
from app.utils.redis_utils import RedisPoolManager
from app.workers.queue import enqueue_worker_job
from shared.py.wide_events import log

# One list per workflow holding the JSON payloads awaiting their batched run.
TRIGGER_BATCH_KEY = "trigger_batch:{workflow_id}"

# Most events one batched run will carry. A run that swallowed an entire backlog
# would blow the per-request token ceiling and fail wholesale, so the newest
# events win and the overflow is logged rather than silently dropped.
MAX_TRIGGER_BATCH_EVENTS = 50

# The buffer only has to outlive its own deferred job. Sized well past the
# window so a slow queue can't strand a batch, and short enough that an
# abandoned workflow's payloads don't linger.
TRIGGER_BATCH_TTL_MULTIPLIER = 4


def coalesce_window_seconds(trigger_config: TriggerConfig) -> int:
    """Seconds to batch this trigger's events over, or 0 to fire immediately.

    The window IS the user's configured poll interval, so "polls your inbox
    every N minutes" finally describes what the workflow does.
    """
    trigger_data = trigger_config.trigger_data
    if isinstance(trigger_data, GmailPollInboxConfig):
        return trigger_data.interval * 60
    return 0


async def buffer_trigger_event(
    workflow_id: str,
    user_id: str,
    data: dict[str, Any],
    window_seconds: int,
    context: dict[str, Any],
) -> bool:
    """Add one event to the workflow's batch and ensure a run is scheduled.

    Returns False when the batch is unreachable, so the caller can fall back to
    dispatching immediately — a burst of runs is bad, but silently losing the
    user's triggers is worse.
    """
    client = redis_cache.redis
    if client is None:
        log.warning(
            f"{LogTag.TRIGGER} Redis unavailable — trigger event cannot be batched",
            workflow_id=workflow_id,
            user_id=user_id,
        )
        return False

    key = TRIGGER_BATCH_KEY.format(workflow_id=workflow_id)
    buffered = await client.rpush(key, json.dumps(data, default=str))
    if buffered > MAX_TRIGGER_BATCH_EVENTS:
        await client.ltrim(key, -MAX_TRIGGER_BATCH_EVENTS, -1)
        log.warning(
            f"{LogTag.TRIGGER} Trigger batch full — oldest events dropped",
            workflow_id=workflow_id,
            user_id=user_id,
            dropped_count=buffered - MAX_TRIGGER_BATCH_EVENTS,
            max_batch=MAX_TRIGGER_BATCH_EVENTS,
        )
        buffered = MAX_TRIGGER_BATCH_EVENTS
    await client.expire(key, window_seconds * TRIGGER_BATCH_TTL_MULTIPLIER)

    # One id per workflow: while a batch run is queued or executing, every
    # further event's enqueue is deduped away and it simply rides the buffer.
    # `keep_result = 0` (WorkerSettings) frees the id the moment the run ends,
    # so the next event opens a fresh window instead of being stranded.
    pool = await RedisPoolManager.get_pool()
    job = await enqueue_worker_job(
        pool,
        "execute_workflow_by_id",
        workflow_id,
        {**context, "trigger_batch_key": key},
        _job_id=f"trigger_batch:{workflow_id}",
        _defer_by=window_seconds,
    )

    log.info(
        f"{LogTag.TRIGGER} Trigger event buffered for batched run",
        workflow_id=workflow_id,
        user_id=user_id,
        buffered_count=buffered,
        window_seconds=window_seconds,
        scheduled_run=job is not None,
    )
    return True


async def drain_trigger_batch(batch_key: str) -> list[dict[str, Any]]:
    """Take every buffered event for this batch, leaving the key empty.

    Read-and-delete in one transaction so events arriving mid-drain open the
    next window instead of being consumed by a run that already built its
    prompt without them.
    """
    client = redis_cache.redis
    if client is None:
        log.warning(f"{LogTag.TRIGGER} Redis unavailable — trigger batch cannot be drained")
        return []

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
