"""Background executor coroutine.

Spawned by call_executor tool via asyncio.create_task(). Runs the executor
agent graph with a Redis stream writer for tool events, then pushes the
final result + sentinel to the comms inbox so the notifier can generate
the comms response.

The executor:busy Redis key prevents concurrent executor spawns per
conversation. TTL of 30 minutes is a safety net — released explicitly.
"""

import asyncio
import json
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from langchain_core.messages import HumanMessage, SystemMessage
from langsmith import traceable
from shared.py.wide_events import log

from app.agents.core.background.inbox import (
    deregister_executor_inbox,
    mark_executor_spawned,
    register_executor_inbox,
)
from app.agents.core.background.redis_writer import make_redis_stream_writer
from app.agents.core.subagents.subagent_runner import (
    execute_subagent_stream,
    prepare_executor_execution,
)
from app.agents.llm.client import init_llm
from app.agents.prompts.comms_prompts import COMMS_AGENT_PROMPT
from app.constants.cache import EXECUTOR_BUSY_PREFIX, EXECUTOR_QUEUE_PREFIX
from app.constants.general import NEW_MESSAGE_BREAKER
from app.db.redis import redis_cache
from app.models.chat_models import MessageModel, UpdateMessagesRequest
from app.services.conversation_service import update_messages

# Prevent GC of background tasks spawned from the queue
_queued_executor_tasks: set[asyncio.Task] = set()


@traceable(name="executor_background", run_type="chain")
async def run_executor_background(
    task: str,
    configurable: dict,
    user_time: datetime,
    stream_id: str,
    conversation_id: str,
    comms_inbox: Optional[asyncio.Queue] = None,
) -> None:
    """Run executor agent in background and push result to comms inbox.

    Designed for asyncio.create_task(). Never raises — all exceptions
    caught and routed to comms_inbox so the notifier can inform the user.

    Args:
        task: Task string from comms to executor.
        configurable: RunnableConfig.configurable dict.
        user_time: User's local time.
        stream_id: Active SSE stream ID for tool event publishing.
        conversation_id: Conversation ID used as the Redis lock key.
        comms_inbox: Queue to push progress/final results for comms notifier.
    """
    lock_key = f"{EXECUTOR_BUSY_PREFIX}{conversation_id}"

    # Register executor inbox for subagent → executor communication
    register_executor_inbox(stream_id)

    try:
        ctx, error = await prepare_executor_execution(
            task=task,
            configurable=configurable,
            user_time=user_time,
            stream_id=stream_id,
        )

        if error or ctx is None:
            msg = error or "Executor agent not available"
            log.error(f"Background executor prep failed: {msg}")
            if comms_inbox:
                await comms_inbox.put({"type": "error", "message": msg})
            return

        writer = make_redis_stream_writer(stream_id)
        result = await execute_subagent_stream(ctx=ctx, stream_writer=writer)

        log.info(f"Background executor completed for stream {stream_id}")

        if comms_inbox:
            # Push final result to comms inbox (live stream path)
            await comms_inbox.put({"type": "final", "message": result})
        else:
            # Queued path — no live stream. Invoke comms silently and save.
            await _deliver_queued_result(
                result=result,
                msg_type="final",
                configurable=configurable,
                conversation_id=conversation_id,
                user_time=user_time,
            )

    except Exception as e:
        log.error(f"Background executor failed for stream {stream_id}: {e}")
        if comms_inbox:
            await comms_inbox.put({"type": "error", "message": str(e)})
        else:
            await _deliver_queued_result(
                result=str(e),
                msg_type="error",
                configurable=configurable,
                conversation_id=conversation_id,
                user_time=user_time,
            )
    finally:
        # Always release lock and signal notifier to stop
        await redis_cache.delete(lock_key)
        deregister_executor_inbox(stream_id)
        if comms_inbox:
            await comms_inbox.put(None)  # sentinel — notifier loop exits

        # Process next queued task if one exists.
        # Queued tasks run without a live SSE stream — the executor performs
        # the requested actions (creates todos, sends emails, etc.) and its
        # result is silently saved to the LangGraph checkpoint. No comms
        # response is streamed because the original SSE stream is already closed.
        await _process_next_queued_task(conversation_id)


async def _deliver_queued_result(
    result: str,
    msg_type: str,
    configurable: dict,
    conversation_id: str,
    user_time: datetime,
) -> None:
    """Generate a comms notification for a queued executor result and save to MongoDB.

    Called when a queued executor completes with no live SSE stream. Calls the
    LLM directly (same approach as comms_notifier live path) to avoid the
    checkpoint-continuation empty-response issue that plagued execute_graph_silent.

    Args:
        result: Executor result text (or error message).
        msg_type: "final" or "error" — controls the prefix shown to comms.
        configurable: Scalar configurable dict from the queued task item.
        conversation_id: Conversation to save the bot message into.
        user_time: User's local time for config.
    """
    prefix = "[EXECUTOR_RESULT]" if msg_type == "final" else "[EXECUTOR_ERROR]"

    # Reconstruct minimal user dict from scalar configurable keys
    user: dict = {
        "user_id": configurable.get("user_id", ""),
        "email": configurable.get("user_email", ""),
        "name": configurable.get("user_name", ""),
    }
    user_name = configurable.get("user_name", "")

    try:
        try:
            llm = init_llm(preferred_provider="openai")
        except (RuntimeError, ValueError):
            llm = init_llm()  # Fall back to default provider
        system_prompt = COMMS_AGENT_PROMPT.replace("{user_name}", user_name or "there")
        response = await llm.ainvoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=f"{prefix}\n{result}"),
        ])
        content = response.content if isinstance(response.content, str) else ""
        complete_message = content.replace(NEW_MESSAGE_BREAKER, "").strip()
    except Exception as e:
        log.error(f"_deliver_queued_result: LLM call failed: {e}")
        complete_message = ""

    # Fallback to raw executor result if LLM returned empty
    if not complete_message:
        log.warning(
            "_deliver_queued_result: empty LLM response, using raw executor result"
        )
        complete_message = result

    bot_message_id = str(uuid4())
    bot_message = MessageModel(
        type="bot",
        response=complete_message,
        date=datetime.now(timezone.utc).isoformat(),
    )
    bot_message.message_id = bot_message_id

    try:
        await update_messages(
            UpdateMessagesRequest(
                conversation_id=conversation_id,
                messages=[bot_message],
            ),
            user=user,
        )
        log.info(
            f"_deliver_queued_result: saved comms message {bot_message_id} "
            f"for conversation {conversation_id}"
        )
    except Exception as e:
        log.error(f"_deliver_queued_result: failed to save bot message: {e}")


async def _process_next_queued_task(conversation_id: str) -> None:
    """Pop the next queued task for this conversation and spawn it.

    Called from run_executor_background's finally block. Acquires the executor
    lock before spawning so the queued run is still protected against
    concurrent access to the executor_{conversation_id} checkpoint.
    """
    if not redis_cache.client:
        return

    queue_key = f"{EXECUTOR_QUEUE_PREFIX}{conversation_id}"
    raw = await redis_cache.client.lpop(queue_key)
    if not raw:
        return

    try:
        item: dict = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as e:
        log.error(f"Failed to parse queued executor task for {conversation_id}: {e}")
        return

    task = item.get("task", "")
    configurable: dict = item.get("configurable", {})
    user_time_str: str = item.get("user_time_str", "")
    user_time = (
        datetime.fromisoformat(user_time_str) if user_time_str else datetime.now()
    )

    # Use a synthetic stream_id — no SSE channel exists for queued tasks
    queued_stream_id = f"queued_{uuid4()}"

    # Re-acquire the lock before spawning (same pattern as call_executor)
    lock_key = f"{EXECUTOR_BUSY_PREFIX}{conversation_id}"
    await redis_cache.set(lock_key, "1", ttl=1800)

    # Mark spawned so any concurrent chat_service check is correct
    mark_executor_spawned(queued_stream_id)

    # Update stream_id in configurable so notify_comms/notify_executor
    # don't try to push to the now-closed original stream
    configurable = {**configurable, "stream_id": queued_stream_id}

    bg_task = asyncio.create_task(
        run_executor_background(
            task=task,
            configurable=configurable,
            user_time=user_time,
            stream_id=queued_stream_id,
            conversation_id=conversation_id,
            comms_inbox=None,  # no live stream — runs silently
        )
    )
    _queued_executor_tasks.add(bg_task)
    bg_task.add_done_callback(_queued_executor_tasks.discard)

    log.info(
        f"Queued executor task spawned for conversation {conversation_id} "
        f"as stream {queued_stream_id}"
    )
