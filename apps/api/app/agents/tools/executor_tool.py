"""Executor tool for comms agent to delegate tasks to executor agent.

Non-blocking: spawns executor as a background asyncio task and returns
immediately. The executor delivers its result as a NEW bot message via
WebSocket when it completes (see _deliver_bg_notification).
"""

import asyncio
import json
from datetime import datetime
from typing import Annotated
from uuid import uuid4

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from app.agents.core.background.executor_runner import run_executor_background
from app.agents.core.background.inbox import mark_executor_spawned
from app.agents.tools.core.registry import get_tool_registry
from app.api.v1.middleware.tiered_rate_limiter import RateLimitExceededException
from app.constants.cache import (
    EXECUTOR_BUSY_PREFIX,
    EXECUTOR_BUSY_TTL,
    EXECUTOR_QUEUE_PREFIX,
    EXECUTOR_QUEUE_TTL,
)
from app.db.redis import redis_cache
from app.decorators.rate_limiting import LangChainRateLimitException
from shared.py.wide_events import log

# Prevent GC of background tasks
_executor_tasks: set[asyncio.Task] = set()


@tool
async def call_executor(
    config: RunnableConfig,
    task: Annotated[str, "The task to execute - describe what needs to be done"],
) -> str:
    """
    Delegate a task to the executor agent for execution.

    Use this when the user asks you to do something that requires action
    (creating todos, checking calendar, sending emails, searching, etc.)
    or when you need context from your capabilities.

    The executor runs in the background. You will receive progress updates
    and the final result via [EXECUTOR_UPDATE] and [EXECUTOR_RESULT] messages.
    """
    configurable = config.get("configurable", {})
    conversation_id = configurable.get("thread_id", "")

    # Generate a unique task_id for tracking this executor invocation
    task_id = str(uuid4())

    try:
        log.set(tool={"name": "call_executor", "action": "dispatch", "task_id": task_id})
        user_id = configurable.get("user_id")
        stream_id = configurable.get("stream_id")
        user_message_id = configurable.get("user_message_id")

        # Check executor lock — if busy, queue the task and return immediately.
        # Only one executor can run per conversation (stateful checkpoint under
        # executor_{conversation_id}). Queued tasks are processed sequentially
        # after the current executor finishes.
        lock_key = f"{EXECUTOR_BUSY_PREFIX}{conversation_id}"
        if await redis_cache.get(lock_key):
            queue_key = f"{EXECUTOR_QUEUE_PREFIX}{conversation_id}"
            # configurable may contain non-serializable LangGraph internals
            # (e.g. Runtime objects). Only carry the scalar values we need.
            _CONFIGURABLE_SCALAR_KEYS = {
                "thread_id",
                "conversation_id",
                "user_id",
                "user_email",
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
            }
            safe_configurable = {
                k: v
                for k, v in configurable.items()
                if k in _CONFIGURABLE_SCALAR_KEYS and isinstance(v, (str, int, float, bool, type(None)))
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
            log.info(
                f"Executor busy — task queued (task_id={task_id}) for conversation {conversation_id}"
            )
            return (
                f"I'm already working on a task for this conversation. "
                f"Your request has been queued (task_id: {task_id}) and I'll handle it right after."
            )

        # Set executor lock
        await redis_cache.set(lock_key, "1", ttl=EXECUTOR_BUSY_TTL)

        # Load user's MCP tools
        if user_id:
            try:
                tool_registry = await get_tool_registry()
                loaded = await tool_registry.load_user_mcp_tools(user_id)
                if loaded:
                    log.info(
                        f"Loaded MCP tools for user {user_id}: {list(loaded.keys())}"
                    )
            except Exception as e:
                log.warning(f"Failed to load user MCP tools: {e}")

        # Parse user time
        user_time_str = configurable.get("user_time", "")
        user_time = (
            datetime.fromisoformat(user_time_str) if user_time_str else datetime.now()
        )

        # Mark this stream as having an active executor BEFORE spawning the
        # task so chat_service knows an executor was dispatched for this stream.
        if stream_id:
            mark_executor_spawned(stream_id)

        # Spawn executor in background — it delivers its own notification
        # as a NEW bot message via WebSocket when it completes.
        bg_task = asyncio.create_task(
            run_executor_background(
                task=task,
                configurable=configurable,
                user_time=user_time,
                stream_id=stream_id or "",
                conversation_id=conversation_id,
                task_id=task_id,
                user_message_id=user_message_id,
            )
        )
        _executor_tasks.add(bg_task)
        bg_task.add_done_callback(_executor_tasks.discard)

        log.info(f"Executor dispatched (task_id={task_id}) to background for stream {stream_id}")
        return f"Task accepted (task_id: {task_id}). I'm on it — you'll get progress updates as I work."

    except (LangChainRateLimitException, RateLimitExceededException) as e:
        if isinstance(e, LangChainRateLimitException):
            feature = e.feature
        else:
            detail: dict = e.detail if isinstance(e.detail, dict) else {}
            feature = detail.get("feature", "")
        log.warning(f"Rate limit exceeded for executor task: {feature}")
        return f"Rate limit exceeded for {feature or 'this feature'}. The user has been shown an upgrade prompt."
    except Exception as e:
        log.error(f"Error dispatching executor: {e}")
        await redis_cache.delete(f"{EXECUTOR_BUSY_PREFIX}{conversation_id}")
        return f"Error starting task: {str(e)}"


tools = [call_executor]
