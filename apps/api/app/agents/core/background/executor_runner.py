"""Background executor coroutine.

Spawned by call_executor tool via asyncio.create_task(). Runs the executor
agent graph with a Redis stream writer for tool events, then pushes a
sentinel to the comms inbox (SSE stream can close) and delivers the
executor result as a NEW bot message via WebSocket.

The executor:busy Redis key prevents concurrent executor spawns per
conversation. TTL of 30 minutes is a safety net — released explicitly.

After delivery, the result is injected into the comms agent's LangGraph
checkpoint via graph.aupdate_state() so subsequent turns see it in history.
"""

import asyncio
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from langchain_core.messages import AIMessage
from langchain_core.messages import HumanMessage, SystemMessage
from langsmith import traceable
from shared.py.wide_events import log

from app.agents.core.background.inbox import (
    deregister_executor_inbox,
    deregister_tool_event_collector,
    get_tool_event_collector,
    mark_executor_spawned,
    register_executor_inbox,
    register_tool_event_collector,
)
from app.agents.core.background.redis_writer import make_redis_stream_writer
from app.agents.core.subagents.subagent_runner import (
    execute_subagent_stream,
    prepare_executor_execution,
)
from app.agents.llm.client import init_llm
from app.agents.templates.agent_template import COMMS_PROMPT_TEMPLATE
from app.constants.cache import EXECUTOR_BUSY_PREFIX, EXECUTOR_QUEUE_PREFIX
from app.constants.general import NEW_MESSAGE_BREAKER
from app.core.websocket_manager import websocket_manager
from app.db.redis import redis_cache
from app.models.chat_models import MessageModel, UpdateMessagesRequest
from app.models.message_models import ReplyToMessageData
from app.services.conversation_service import update_messages

# Prevent GC of background tasks spawned from the queue
_queued_executor_tasks: set[asyncio.Task] = set()


async def _deliver_bg_notification(
    result: str,
    msg_type: str,
    conversation_id: str,
    user: dict,
    task_id: Optional[str] = None,
    user_message_id: Optional[str] = None,
    tool_data: Optional[List[Dict[str, Any]]] = None,
) -> None:
    """Generate notification for executor completion, save as NEW message, push via WebSocket.

    This is the unified delivery path for both live and queued executor results.
    The notification is always a standalone bot message — never appended to an
    existing message. The frontend receives it via WebSocket and inserts a new bubble.

    After saving, injects the notification into the comms agent's LangGraph
    checkpoint so subsequent turns can see the completion in conversation history.

    Args:
        result: Executor result text (or error message).
        msg_type: "final" or "error" — controls the prefix shown to comms LLM.
        conversation_id: Conversation to save the new bot message into.
        user: User dict with user_id, email, name.
        task_id: Optional unique identifier for this executor task.
        user_message_id: Optional ID of the user message that triggered this task,
                         used for reply-to linking.
        tool_data: Optional tool_data entries to include (for queued tasks where
                   no SSE stream carried them to the frontend live).
    """
    prefix = "[EXECUTOR_RESULT]" if msg_type == "final" else "[EXECUTOR_ERROR]"
    user_name = user.get("name", "")

    # Generate notification text via LLM
    try:
        llm = init_llm()
        system_prompt = COMMS_PROMPT_TEMPLATE.format(user_name=user_name or "there")
        response = await llm.ainvoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=f"{prefix}\n{result}"),
        ])
        content = response.text if hasattr(response, "text") else ""
        notification_text = content.replace(NEW_MESSAGE_BREAKER, "").strip()
    except Exception as e:
        log.error(f"_deliver_bg_notification LLM failed: {e}")
        notification_text = ""

    # Fallback to raw executor result
    if not notification_text:
        notification_text = result

    # Build and save NEW bot message
    bot_message_id = str(uuid4())
    bot_message = MessageModel(
        type="bot",
        response=notification_text,
        date=datetime.now(timezone.utc).isoformat(),
    )
    bot_message.message_id = bot_message_id

    # Attach tool_data for queued tasks (live tasks have it on the comms ack message)
    if tool_data:
        bot_message.tool_data = tool_data  # type: ignore[assignment]

    # Attach reply-to-message data so frontend can link notification to original message
    if user_message_id:
        # Look up original user message content for the reply preview
        user_msg_content = ""
        try:
            from app.db.mongodb.collections import conversations_collection

            conv_doc = await conversations_collection.find_one(
                {
                    "conversation_id": conversation_id,
                    "messages.message_id": user_message_id,
                },
                {"messages.$": 1},
            )
            if conv_doc and conv_doc.get("messages"):
                user_msg_content = conv_doc["messages"][0].get("response", "")[:150]
        except Exception as e:
            log.warning(f"_deliver_bg_notification: failed to look up user message: {e}")

        bot_message.replyToMessage = ReplyToMessageData(
            id=user_message_id,
            content=user_msg_content,
            role="user",
        )

    try:
        await update_messages(
            UpdateMessagesRequest(
                conversation_id=conversation_id,
                messages=[bot_message],
            ),
            user=user,
        )
    except Exception as e:
        log.error(f"_deliver_bg_notification: failed to save message: {e}")
        return

    # Push via WebSocket — conversation-scoped payload.
    user_id = user.get("user_id", "")
    message_payload: Dict[str, Any] = {
        "type": "bot",
        "response": notification_text,
        "message_id": bot_message_id,
        "date": bot_message.date,
    }
    if tool_data:
        message_payload["tool_data"] = tool_data
    if task_id:
        message_payload["task_id"] = task_id
    if user_message_id:
        message_payload["replyToMessage"] = {
            "id": user_message_id,
            "content": user_msg_content,
            "role": "user",
        }

    ws_event = {
        "type": "conversation.new_message",
        "conversation_id": conversation_id,
        "message": message_payload,
    }

    # Deliver via WebSocket with retry. Try direct send first (same
    # process), then always fall back to broadcast_to_user (crosses
    # process boundaries via RabbitMQ).
    ws_delivered = False
    for attempt in range(2):
        try:
            if user_id in websocket_manager.connections:
                disconnected = set()
                for ws in websocket_manager.connections[user_id]:
                    try:
                        await ws.send_json(ws_event)
                        ws_delivered = True
                    except Exception:
                        disconnected.add(ws)
                for ws in disconnected:
                    websocket_manager.connections[user_id].discard(ws)

            if not ws_delivered:
                await websocket_manager.broadcast_to_user(user_id, ws_event)
                ws_delivered = True

            break
        except Exception as ws_err:
            log.warning(
                f"_deliver_bg_notification: WebSocket attempt {attempt + 1} failed "
                f"for user {user_id}: {ws_err}"
            )
            if attempt == 0:
                await asyncio.sleep(0.5)

    log.info(
        f"_deliver_bg_notification: delivered message {bot_message_id} "
        f"(task_id={task_id}, ws={ws_delivered}) for conversation {conversation_id}"
    )

    # ── Inject into comms checkpoint so subsequent turns see the completion ──
    # Without this, the LLM would never know the task finished and would
    # hallucinate that it's still running on the next user message.
    # Uses a Redis mutex to prevent concurrent checkpoint writes (e.g. if
    # another comms invocation starts at the same time).
    task_label = f" (task_id: {task_id})" if task_id else ""
    checkpoint_prefix = "[TASK_COMPLETED]" if msg_type == "final" else "[TASK_ERROR]"
    checkpoint_msg = f"{checkpoint_prefix}{task_label} {notification_text}"

    checkpoint_mutex_key = f"comms:checkpoint_mutex:{conversation_id}"
    try:
        from app.agents.core.graph_manager import GraphManager

        # Acquire mutex (short TTL as safety net)
        await redis_cache.set(checkpoint_mutex_key, "1", ttl=30)

        comms_graph = await GraphManager.get_graph("comms_agent")
        if comms_graph:
            checkpoint_config = {"configurable": {"thread_id": conversation_id}}
            await comms_graph.aupdate_state(
                checkpoint_config,
                {"messages": [AIMessage(content=checkpoint_msg)]},
                as_node="agent",
            )
            log.info(
                f"_deliver_bg_notification: injected completion into comms checkpoint "
                f"for conversation {conversation_id}"
            )
    except Exception as e:
        log.error(
            f"_deliver_bg_notification: failed to update comms checkpoint "
            f"for conversation {conversation_id}: {e}"
        )
    finally:
        await redis_cache.delete(checkpoint_mutex_key)


@traceable(name="executor_background", run_type="chain")
async def run_executor_background(
    task: str,
    configurable: dict,
    user_time: datetime,
    stream_id: str,
    conversation_id: str,
    task_id: Optional[str] = None,
    user_message_id: Optional[str] = None,
) -> None:
    """Run executor agent in background, then deliver result as a NEW message.

    Designed for asyncio.create_task(). Never raises — all exceptions
    caught and handled.

    When executor completes, _deliver_bg_notification saves a NEW bot
    message to MongoDB, pushes it via WebSocket, and injects the result
    into the comms agent's LangGraph checkpoint.

    Args:
        task: Task string from comms to executor.
        configurable: RunnableConfig.configurable dict.
        user_time: User's local time.
        stream_id: Stream ID for tool event collection.
        conversation_id: Conversation ID used as the Redis lock key.
        task_id: Unique ID for this executor task (for tracking/correlation).
        user_message_id: ID of the user message that triggered this task.
    """
    lock_key = f"{EXECUTOR_BUSY_PREFIX}{conversation_id}"
    result_text = ""
    result_type = "final"

    # Reconstruct user dict from configurable
    user: dict = {
        "user_id": configurable.get("user_id", ""),
        "email": configurable.get("user_email", ""),
        "name": configurable.get("user_name", ""),
    }

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
            result_text = error or "Executor agent not available"
            result_type = "error"
            log.error(f"Background executor prep failed: {result_text}")
            return

        writer = make_redis_stream_writer(stream_id)
        result_text = await execute_subagent_stream(ctx=ctx, stream_writer=writer)

        log.info(f"Background executor completed (task_id={task_id}) for stream {stream_id}")

    except Exception as e:
        log.error(f"Background executor failed for stream {stream_id}: {e}")
        result_text = str(e)
        result_type = "error"
    finally:
        # Release lock and signal SSE stream that tool events are done
        await redis_cache.delete(lock_key)
        deregister_executor_inbox(stream_id)

        # Push result + sentinel to comms_inbox so _run_chat_stream can:
        # 1. Read the result for SSE notification delivery
        # 2. Close SSE on sentinel
        from app.agents.core.background.inbox import get_comms_inbox

        inbox = get_comms_inbox(stream_id)
        if inbox:
            if result_text:
                await inbox.put({"type": result_type, "message": result_text})
            await inbox.put(None)  # sentinel

        # Deliver notification as a NEW bot message for ALL paths.
        # Uses WebSocket broadcast for live push + saves to MongoDB +
        # injects into comms checkpoint for conversation history.
        if result_text:
            collected_tool_data: Optional[List[Dict[str, Any]]] = None
            # Collect tool_data from the event collector
            collector = get_tool_event_collector(stream_id)
            if collector:
                collected_tool_data = [
                    e["tool_data"] for e in collector if "tool_data" in e
                ]
                if not collected_tool_data:
                    collected_tool_data = None

            try:
                await _deliver_bg_notification(
                    result=result_text,
                    msg_type=result_type,
                    conversation_id=conversation_id,
                    user=user,
                    task_id=task_id,
                    user_message_id=user_message_id,
                    tool_data=collected_tool_data,
                )
            except Exception as e:
                log.error(f"Background notification delivery failed: {e}")

        # Clean up tool event collector for this stream
        deregister_tool_event_collector(stream_id)

        # Process next queued task if one exists
        await _process_next_queued_task(conversation_id)


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
    task_id = item.get("task_id")
    queued_user_message_id = item.get("user_message_id")
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

    # Register tool event collector for the queued task so tool_data is captured
    register_tool_event_collector(queued_stream_id)

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
            task_id=task_id,
            user_message_id=queued_user_message_id,
        )
    )
    _queued_executor_tasks.add(bg_task)
    bg_task.add_done_callback(_queued_executor_tasks.discard)

    log.info(
        f"Queued executor task spawned (task_id={task_id}) for conversation "
        f"{conversation_id} as stream {queued_stream_id}"
    )
