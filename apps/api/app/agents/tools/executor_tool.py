"""Executor tools for comms agent: delegate tasks and cancel running tasks.

Non-blocking: spawns executor as a background asyncio task and returns
immediately. The executor saves its terminal text as a new bot message
in MongoDB and pushes it via WebSocket when it completes — see
run_executor_background.
"""

import asyncio
import json
from typing import Annotated
from uuid import uuid4

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from app.agents.core.background.executor_queue import (
    build_lock_value,
    decode_raw_item,
    enqueue_task,
    parse_lock_value,
    try_acquire_lock,
)
from app.agents.core.background.executor_runner import run_executor_background
from app.agents.core.background.session import (
    ExecutorRun,
    RunKind,
    mark_executor_spawned,
)
from app.api.v1.middleware.tiered_rate_limiter import RateLimitExceededException
from app.constants.cache import (
    EXECUTOR_BUSY_PREFIX,
    EXECUTOR_QUEUE_PREFIX,
    EXECUTOR_QUEUE_TTL,
)
from app.constants.general import CALL_EXECUTOR_NAME
from app.constants.streaming import WS_EVENT_EXECUTOR_CANCELLED
from app.core.stream_manager import StreamManager
from app.core.websocket_manager import websocket_manager
from app.db.redis import redis_cache
from app.decorators.rate_limiting import LangChainRateLimitException
from shared.py.wide_events import log

# Prevent GC of background tasks
_executor_tasks: set[asyncio.Task[None]] = set()


@tool
async def call_executor(
    config: RunnableConfig,
    task: Annotated[
        str,
        "The task to execute - describe what needs to be done",
    ],
    active_todo_id: Annotated[
        str | None,
        "Optional tracked-todo ID to BIND this executor run to. When set, "
        "the executor's canvas writes default to this todo's canvas and a "
        "🎯 ACTIVE TODO banner is added to its context. Use when delegating "
        "work that's clearly about a specific existing tracked todo (e.g. "
        "'update progress on todo X', 'continue working on Y'). Omit for "
        "general tasks.",
    ] = None,
) -> str:
    """Delegate a task to the executor agent for background execution.

    Use this when the user asks you to do something that requires action
    (creating todos, checking calendar, sending emails, searching, etc.)
    or when you need context from your capabilities.

    The executor runs in the background and posts its result to the
    conversation as a new bot message when it completes.
    """
    base_configurable = config.get("configurable", {})
    # Shallow-copy so the executor's overrides (todo binding) never mutate the
    # comms agent's live RunnableConfig. The model is inherited from the comms
    # configurable (set by per-plan routing).
    configurable = {**base_configurable}
    if active_todo_id:
        configurable["active_todo_id"] = active_todo_id
    conversation_id = configurable.get("thread_id", "")

    if not conversation_id:
        log.error("call_executor: missing thread_id in configurable")
        return "Internal error: conversation context unavailable. Please try again."

    task_id = str(uuid4())

    try:
        return await _dispatch_executor(
            task=task,
            task_id=task_id,
            configurable=configurable,
            conversation_id=conversation_id,
        )
    except (LangChainRateLimitException, RateLimitExceededException) as e:
        return _rate_limit_message(e)
    except Exception as e:  # noqa: BLE001
        log.error("Error dispatching executor", error=str(e))
        await redis_cache.delete(
            f"{EXECUTOR_BUSY_PREFIX}{conversation_id}",
        )
        return f"Error starting task: {e!s}"


def _rate_limit_message(e: LangChainRateLimitException | RateLimitExceededException) -> str:
    """Build the comms-facing message for an executor rate-limit hit."""
    if isinstance(e, LangChainRateLimitException):
        feature = e.feature
    else:
        detail: dict[str, str] = e.detail if isinstance(e.detail, dict) else {}
        feature = detail.get("feature", "")
    log.warning("Rate limit exceeded for executor task", feature=feature)
    return (
        f"Rate limit exceeded for {feature or 'this feature'}. "
        "The user has already been notified of this limit; "
        "acknowledge briefly without repeating the limit details."
    )


async def _dispatch_executor(
    *,
    task: str,
    task_id: str,
    configurable: dict,
    conversation_id: str,
) -> str:
    """Core dispatch logic — acquire lock, queue if busy, or spawn."""
    log.set(
        tool={
            "name": CALL_EXECUTOR_NAME,
            "action": "dispatch",
            "task_id": task_id,
        },
    )
    stream_id = configurable.get("stream_id")
    user_message_id = configurable.get("user_message_id")

    lock_key = f"{EXECUTOR_BUSY_PREFIX}{conversation_id}"
    lock_value = build_lock_value(stream_id, task_id)

    if not await try_acquire_lock(lock_key, lock_value):
        # The lock is held. Distinguish two cases by the holder's stream_id:
        #   - SAME stream_id → the comms model called call_executor twice within
        #     ONE turn. Queuing it would run the whole task a SECOND time
        #     (observed: deep research executed twice for a single user message).
        #     Reject it — the first dispatch already covers this turn.
        #   - DIFFERENT stream_id → a genuinely new request arrived while the
        #     executor is busy; queue it to run next.
        held_value = await redis_cache.client.get(lock_key) if redis_cache.client else None
        held_stream_id = parse_lock_value(str(held_value))[0] if held_value else ""
        if stream_id and held_stream_id == stream_id:
            log.warning(
                "Duplicate call_executor in same turn — ignored, not queued",
                task_id=task_id,
                stream_id=stream_id,
                conversation_id=conversation_id,
            )
            return (
                "That task is already running from this same message — not "
                "starting it again. The results are on the way."
            )

        # Executor is busy with a different turn — queue for later execution
        queue_key = f"{EXECUTOR_QUEUE_PREFIX}{conversation_id}"
        await enqueue_task(
            queue_key=queue_key,
            task=task,
            task_id=task_id,
            configurable=configurable,
            conversation_id=conversation_id,
            user_message_id=user_message_id,
        )
        log.info(
            "Executor busy — task queued",
            task_id=task_id,
            conversation_id=conversation_id,
        )
        return (
            "I'm already working on a task for this conversation. "
            f"Your request has been queued (task_id: {task_id}) "
            "and I'll handle it right after."
        )

    # MCP tools load lazily inside each subagent's first use — the old eager
    # warmup hit get_all_connected_tools() on every executor call and
    # dominated cold-start latency.

    if stream_id:
        mark_executor_spawned(stream_id)

    run = ExecutorRun.from_configurable(
        configurable,
        stream_id=stream_id or "",
        conversation_id=conversation_id,
        kind=RunKind.LIVE,
        task_id=task_id,
        user_message_id=user_message_id,
    )
    bg_task = asyncio.create_task(
        run_executor_background(
            run=run,
            task=task,
            configurable=configurable,
        ),
    )
    _executor_tasks.add(bg_task)
    bg_task.add_done_callback(_executor_tasks.discard)

    log.info(
        "Executor dispatched to background",
        task_id=task_id,
        stream_id=stream_id,
    )
    return f"Task accepted (task_id: {task_id}). I'm on it — you'll get progress updates as I work."


@tool
async def cancel_executor(
    config: RunnableConfig,
    task_ids: Annotated[
        list[str],
        "List of task_ids to cancel. Empty list = cancel ALL (running + queued).",
    ] = [],  # noqa: B006
) -> str:
    """Cancel background executor tasks by their task_ids.

    task_ids behavior:
    - Empty list [] = cancel EVERYTHING (running task + all queued).
      Use for: "stop everything", "cancel all", or generic "stop that".
    - Specific task_ids = cancel only those (running or queued), keep rest.
      Use for: "cancel the search task" / "stop the second one".
      Match user intent to task_ids from call_executor responses in
      conversation history (e.g. "Task accepted (task_id: abc-123)"
      or "queued (task_id: xyz-456)").

    CRITICAL: NEVER use this tool unless the user EXPLICITLY asks to stop,
    cancel, or abort. Valid triggers: "stop that", "cancel it", "abort",
    "kill that task", "don't do that anymore", "cancel the X task".

    DO NOT use if the user is just changing the subject, asking a new
    question, or saying "nevermind" about a NEW request. Only the USER
    decides to cancel.
    """
    configurable = config.get("configurable", {})
    conversation_id = configurable.get("thread_id", "")

    if not conversation_id:
        return "No conversation context available."

    lock_key = f"{EXECUTOR_BUSY_PREFIX}{conversation_id}"
    queue_key = f"{EXECUTOR_QUEUE_PREFIX}{conversation_id}"
    cancel_all = len(task_ids) == 0

    # Use raw client.get() — lock value is a plain string ("stream_id:task_id"),
    # not JSON. redis_cache.get() would fail to deserialize it.
    raw_lock = await redis_cache.client.get(lock_key) if redis_cache.client else None
    lock_value: str | None = str(raw_lock) if raw_lock is not None else None
    has_queue = redis_cache.client and await redis_cache.client.llen(queue_key) > 0

    if not lock_value and not has_queue:
        return "No executor tasks are running or queued for this conversation."

    try:
        cancelled = await _cancel_running_task(
            lock_key,
            lock_value,
            task_ids,
            cancel_all,
            conversation_id,
        )
        # Running task was present but not targeted for cancellation
        skipped_running = bool(lock_value) and not cancelled
        cancelled += await _cancel_queued_tasks(
            queue_key,
            task_ids,
            cancel_all,
            conversation_id,
        )

        if not cancelled:
            return "None of the specified task_ids matched any running or queued tasks."

        # Tell the client an agent-initiated cancel happened so it can clear the
        # stuck executor-pending loading state and finalize in-flight tool cards
        # — it has no other way to learn of a cancel it didn't initiate.
        await _broadcast_executor_cancelled(
            user_id=configurable.get("user_id", ""),
            conversation_id=conversation_id,
            cancelled=cancelled,
        )

        result = f"Cancelled: {', '.join(cancelled)}."
        if skipped_running:
            result += " Currently running task was not in the cancel list — still running."
        return result

    except Exception as e:  # noqa: BLE001
        log.error("cancel_executor failed", error=str(e))
        await redis_cache.delete(lock_key)
        return f"Cancellation attempted but hit an error: {e}"


async def _broadcast_executor_cancelled(
    *,
    user_id: str,
    conversation_id: str,
    cancelled: list[str],
) -> None:
    """Push the executor-cancelled control event to the user's clients."""
    if not user_id:
        return
    try:
        await websocket_manager.broadcast_to_user(
            user_id,
            {
                "type": WS_EVENT_EXECUTOR_CANCELLED,
                "conversation_id": conversation_id,
                "cancelled": cancelled,
            },
        )
    except Exception as e:  # noqa: BLE001 — best-effort UI signal
        log.warning("Failed to broadcast executor.cancelled", error=str(e))


async def _cancel_running_task(
    lock_key: str,
    lock_value: str | None,
    task_ids: list[str],
    cancel_all: bool,
    conversation_id: str,
) -> list[str]:
    """Cancel the currently running executor if it matches task_ids."""
    if not lock_value:
        return []

    active_stream_id, active_task_id = parse_lock_value(lock_value)
    should_cancel = cancel_all or active_task_id in task_ids

    if not should_cancel:
        return []

    if active_stream_id and active_stream_id not in ("", "1"):
        await StreamManager.cancel_stream(active_stream_id)

    await redis_cache.delete(lock_key)

    log.info(
        "cancel_executor: stopped running task",
        task_id=active_task_id,
        stream_id=active_stream_id,
        conversation_id=conversation_id,
    )
    return [active_task_id or "running"]


async def _cancel_queued_tasks(
    queue_key: str,
    task_ids: list[str],
    cancel_all: bool,
    conversation_id: str,
) -> list[str]:
    """Cancel queued tasks — all or selectively by task_id."""
    if not redis_cache.client:
        return []

    queue_len = await redis_cache.client.llen(queue_key)
    if queue_len == 0:
        return []

    if cancel_all:
        await redis_cache.client.delete(queue_key)
        log.info(
            "cancel_executor: cleared entire queue",
            queue_len=queue_len,
            conversation_id=conversation_id,
        )
        return [f"{queue_len} queued task(s)"]

    return await _remove_queued_by_ids(
        queue_key,
        task_ids,
        conversation_id,
    )


async def _remove_queued_by_ids(
    queue_key: str,
    task_ids: list[str],
    conversation_id: str,
) -> list[str]:
    """Selectively remove specific task_ids from the queue."""
    if redis_cache.client is None:
        raise RuntimeError("redis_cache.client is not initialized")

    all_items = await redis_cache.client.lrange(queue_key, 0, -1)
    keep: list[str] = []
    cancelled: list[str] = []
    target_ids = set(task_ids)

    for raw_item in all_items:
        try:
            item = json.loads(raw_item)
            if item.get("task_id") in target_ids:
                cancelled.append(item.get("task_id", "queued"))
            else:
                keep.append(decode_raw_item(raw_item))
        except ValueError:
            keep.append(decode_raw_item(raw_item))

    if cancelled:
        await redis_cache.client.delete(queue_key)
        if keep:
            await redis_cache.client.rpush(queue_key, *keep)
            await redis_cache.client.expire(
                queue_key,
                EXECUTOR_QUEUE_TTL,
            )
        log.info(
            "cancel_executor: removed queued tasks",
            removed=len(cancelled),
            remaining=len(keep),
            conversation_id=conversation_id,
        )

    return cancelled


tools = [call_executor, cancel_executor]
