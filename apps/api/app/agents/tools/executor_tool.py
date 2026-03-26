"""Executor tool for comms agent to delegate tasks to executor agent.

Non-blocking: spawns executor as a background asyncio task and returns
immediately. The executor communicates progress via notify_comms tool,
and its final result is pushed to comms_inbox for the notifier loop.
"""

import asyncio
from datetime import datetime
from typing import Annotated

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from app.agents.core.background.executor_runner import run_executor_background
from app.agents.core.background.inbox import get_comms_inbox
from app.agents.tools.core.registry import get_tool_registry
from app.api.v1.middleware.tiered_rate_limiter import RateLimitExceededException
from app.constants.cache import EXECUTOR_BUSY_PREFIX, EXECUTOR_BUSY_TTL
from app.db.redis import redis_cache
from app.decorators.rate_limiting import LangChainRateLimitException
from shared.py.wide_events import log

# Prevent GC of background tasks
_executor_tasks: set[asyncio.Task[None]] = set()


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

    if not conversation_id:
        log.error("call_executor: missing thread_id in configurable")
        return "Internal error: conversation context unavailable. Please try again."

    try:
        log.set(tool={"name": "call_executor", "action": "dispatch"})
        user_id = configurable.get("user_id")
        stream_id = configurable.get("stream_id")

        # Atomically acquire executor lock (SET NX EX) to eliminate TOCTOU gap
        lock_key = f"{EXECUTOR_BUSY_PREFIX}{conversation_id}"
        acquired = await redis_cache.redis.set(
            lock_key, "1", nx=True, ex=EXECUTOR_BUSY_TTL
        )
        if not acquired:
            log.info(f"Executor already busy for conversation {conversation_id}")
            return (
                "I'm already working on a task for this conversation. "
                "I'll let you know when it's done before starting something new."
            )

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

        # Get comms inbox for this stream
        comms_inbox = get_comms_inbox(stream_id) if stream_id else None

        # Spawn executor in background
        bg_task = asyncio.create_task(
            run_executor_background(
                task=task,
                configurable=configurable,
                user_time=user_time,
                stream_id=stream_id or "",
                conversation_id=conversation_id,
                comms_inbox=comms_inbox,
            )
        )
        _executor_tasks.add(bg_task)
        bg_task.add_done_callback(_executor_tasks.discard)

        log.info(f"Executor dispatched to background for stream {stream_id}")
        return "Task accepted. I'm on it — you'll get progress updates as I work."

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
