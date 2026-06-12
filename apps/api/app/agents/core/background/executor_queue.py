"""Per-conversation executor queue and busy-lock mechanics.

One executor runs per conversation at a time, guarded by the
``executor:busy:{conversation_id}`` Redis lock. While the lock is held,
``call_executor`` enqueues additional tasks onto
``executor:queue:{conversation_id}``; when a run finishes, its finalize step
pops the next task here and spawns it.

This module owns the Redis mechanics only — enqueue, pop/prepare, and lock
value handling. ``pop_next_queued_run`` PREPARES the next run (lock overwrite,
session registration, stream start, ``executor.stream_started`` WS event) and
returns it; the runner spawns it. That one-way dependency (runner → queue)
keeps the import graph acyclic.
"""

from dataclasses import dataclass
from datetime import datetime
import json
from typing import Any
from uuid import uuid4

from app.agents.core.background.session import ExecutorRun, RunKind, create_session
from app.constants.cache import (
    EXECUTOR_BUSY_PREFIX,
    EXECUTOR_BUSY_TTL,
    EXECUTOR_QUEUE_PREFIX,
    EXECUTOR_QUEUE_TTL,
)
from app.core.stream_manager import StreamManager
from app.core.websocket_manager import websocket_manager
from app.db.redis import redis_cache
from shared.py.wide_events import log

# Cosmetic prefix for queued stream ids — kept for log greppability only.
# The run kind is carried explicitly on ExecutorRun, never parsed from the id.
QUEUED_STREAM_ID_PREFIX = "queued_"

# Keys from configurable that are safe to serialize into queue items.
# Filters out non-serializable LangGraph internals (e.g. Runtime objects).
_CONFIGURABLE_SCALAR_KEYS = frozenset(
    {
        "thread_id",
        "conversation_id",
        "user_id",
        "email",
        "user_timezone",
        "user_name",
        "user_time",
        "stream_id",
        "provider",
        "model_name",
        "max_tokens",
        "selected_tool",
        "tool_category",
        "subagent_id",
        "vfs_session_id",
        "user_message_id",
        "active_todo_id",
        "execution_mode",
        "conversation_source",
        "source_category",
        # Workflow context must survive queueing: without it a queued workflow
        # run loses its id and the delivery path silently downgrades the result
        # from the completion notification to a plain conversation message.
        "workflow_id",
        "workflow_title",
        "workflow_notify_on_completion",
    }
)


@dataclass(frozen=True)
class PreparedQueuedTask:
    """A queued task popped and fully prepared for spawning."""

    run: ExecutorRun
    task: str
    configurable: dict[str, Any]
    user_time: datetime


# ── Busy lock ────────────────────────────────────────────────────────


def build_lock_value(stream_id: str | None, task_id: str) -> str:
    """Build 'stream_id:task_id' lock value for the executor busy key."""
    return f"{stream_id or ''}:{task_id}"


def parse_lock_value(lock_value: str) -> tuple[str, str]:
    """Parse 'stream_id:task_id' from the executor busy lock value."""
    if ":" in lock_value:
        stream_id, task_id = lock_value.split(":", 1)
        return stream_id, task_id
    return lock_value, ""


async def try_acquire_lock(lock_key: str, lock_value: str) -> bool:
    """Atomically acquire the executor lock via SET NX.

    Returns True if the lock was acquired, False if already held.
    Falls back to True (allow execution) if Redis is unavailable.
    """
    if not redis_cache.client:
        return True
    return bool(
        await redis_cache.client.set(
            lock_key,
            lock_value,
            ex=EXECUTOR_BUSY_TTL,
            nx=True,
        ),
    )


# ── Enqueue ──────────────────────────────────────────────────────────


async def enqueue_task(
    queue_key: str,
    task: str,
    task_id: str,
    configurable: dict,
    conversation_id: str,
    user_message_id: str | None,
) -> None:
    """Push a task to the executor queue for deferred execution."""
    safe_configurable = {
        k: v
        for k, v in configurable.items()
        if k in _CONFIGURABLE_SCALAR_KEYS and isinstance(v, str | int | float | bool | None)
    }
    queue_item = json.dumps(
        {
            "task": task,
            "task_id": task_id,
            "configurable": safe_configurable,
            "user_time_str": configurable.get("user_time", ""),
            "conversation_id": conversation_id,
            "user_message_id": user_message_id,
        }
    )
    if redis_cache.client:
        await redis_cache.client.rpush(queue_key, queue_item)
        await redis_cache.client.expire(queue_key, EXECUTOR_QUEUE_TTL)


def decode_raw_item(raw: bytes | memoryview | str) -> str:
    """Decode a raw Redis list item to a string."""
    if isinstance(raw, str):
        return raw
    return bytes(raw).decode()


# ── Pop + prepare ────────────────────────────────────────────────────


async def pop_next_queued_run(conversation_id: str) -> PreparedQueuedTask | None:
    """Pop the next queued task for this conversation and prepare it for spawning.

    Called from the runner's finalize step. Overwrites the executor busy lock
    with the next task's value (no intervening delete) before returning, so the
    queued run inherits the lock atomically and a concurrent call_executor
    cannot acquire it via SET NX in a delete→re-set gap.

    Registers the QUEUED session (with the executor pre-marked spawned — queued
    runs have no chat_service to register for them), starts stream progress
    tracking, and broadcasts ``executor.stream_started`` so the frontend opens a
    live SSE subscription. Spawning is the caller's job.

    Returns None if the queue was empty or unparseable (caller releases the lock).
    """
    if not redis_cache.client:
        return None

    queue_key = f"{EXECUTOR_QUEUE_PREFIX}{conversation_id}"
    raw = await redis_cache.client.lpop(queue_key)
    if not raw:
        return None

    try:
        item: dict = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as e:
        log.error(
            "Failed to parse queued executor task",
            conversation_id=conversation_id,
            error=str(e),
        )
        return None

    task = item.get("task", "")
    task_id = item.get("task_id")
    queued_user_message_id = item.get("user_message_id")
    configurable: dict = item.get("configurable", {})
    user_time_str: str = item.get("user_time_str", "")
    user_time = datetime.fromisoformat(user_time_str) if user_time_str else datetime.now()

    queued_stream_id = f"{QUEUED_STREAM_ID_PREFIX}{uuid4()}"
    user_id: str = configurable.get("user_id", "")

    lock_key = f"{EXECUTOR_BUSY_PREFIX}{conversation_id}"
    await redis_cache.set(
        lock_key,
        build_lock_value(queued_stream_id, task_id or ""),
        ttl=EXECUTOR_BUSY_TTL,
    )

    session = create_session(queued_stream_id, RunKind.QUEUED)
    session.executor_spawned = True

    await StreamManager.start_stream(
        stream_id=queued_stream_id,
        conversation_id=conversation_id,
        user_id=user_id,
    )

    if user_id:
        await websocket_manager.broadcast_to_user(
            user_id,
            {
                "type": "executor.stream_started",
                "stream_id": queued_stream_id,
                "conversation_id": conversation_id,
                "task_id": task_id,
            },
        )

    configurable = {**configurable, "stream_id": queued_stream_id}
    run = ExecutorRun.from_configurable(
        configurable,
        stream_id=queued_stream_id,
        conversation_id=conversation_id,
        kind=RunKind.QUEUED,
        task_id=task_id,
        user_message_id=queued_user_message_id,
    )
    return PreparedQueuedTask(run=run, task=task, configurable=configurable, user_time=user_time)
