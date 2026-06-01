"""Background executor coroutine.

Spawned by call_executor tool via asyncio.create_task(). Runs the
executor agent graph with a Redis stream writer for tool events. When
the executor finishes, its terminal text is handed to the comms agent
as INTERNAL CONTEXT (SystemMessage with an [EXECUTOR_RESULT] prefix);
comms then generates the user-facing message in its own voice and that
message is saved + WS-broadcast.

The executor:busy Redis key prevents concurrent executor spawns per
conversation. TTL of 30 minutes is a safety net — released explicitly.
"""

import asyncio
from datetime import UTC, datetime
import json
from typing import Any
from uuid import uuid4

from langchain_core.messages import SystemMessage
from langsmith import traceable

from app.agents.core.background.inbox import (
    deregister_bg_subagent_results,
    deregister_executor_done_event,
    deregister_executor_spawned,
    deregister_pending_subagents,
    deregister_tool_event_collector,
    get_executor_done_event,
    get_tool_event_collector,
    mark_executor_spawned,
    register_tool_event_collector,
)
from app.agents.core.background.redis_writer import make_redis_stream_writer
from app.agents.core.graph_manager import GraphManager
from app.agents.core.subagents.subagent_runner import (
    execute_subagent_stream,
    prepare_executor_execution,
)
from app.constants.cache import EXECUTOR_BUSY_PREFIX, EXECUTOR_QUEUE_PREFIX
from app.core.stream_manager import StreamManager
from app.core.websocket_manager import websocket_manager
from app.db.mongodb.collections import conversations_collection
from app.db.redis import redis_cache
from app.helpers.agent_helpers import build_agent_config, execute_graph_silent
from app.models.chat_models import ConversationSource, MessageModel, UpdateMessagesRequest
from app.models.message_models import ReplyToMessageData
from app.services.conversation_service import update_messages
from app.services.platform_message_service import deliver_message_to_platform, is_bot_platform
from app.utils.stream_utils import (
    absorb_collector_event,
    apply_outputs_to_tool_data,
    reconstruct_subagent_groups,
)
from shared.py.wide_events import log

# Prevent GC of background tasks spawned from the queue
_queued_executor_tasks: set[asyncio.Task] = set()


async def _invoke_comms_graph(
    result_text: str,
    msg_type: str,
    conversation_id: str,
    user: dict,
) -> str:
    """Invoke the comms graph silently with the executor result as internal context.

    The result is injected as a SystemMessage with a stable prefix so comms
    treats it as ground-truth internal data (not a user turn). Comms applies
    its voice/persona and returns the user-facing text. The graph's
    checkpoint is updated naturally — no manual aupdate_state.

    Returns the comms-generated text, or an empty string on failure.
    """
    prefix = "[EXECUTOR_ERROR]" if msg_type == "error" else "[EXECUTOR_RESULT]"
    try:
        comms_graph = await GraphManager.get_graph("comms_agent")
        if not comms_graph:
            log.warning("_invoke_comms_graph: comms_agent graph unavailable")
            return ""
        config = build_agent_config(
            conversation_id=conversation_id,
            user=user,
            user_time=datetime.now(UTC),
            agent_name="comms_agent",
        )
        initial_state = {
            "messages": [
                SystemMessage(
                    content=f"{prefix}\n{result_text}",
                    name="background_executor",
                ),
            ],
        }
        notification_text, _ = await execute_graph_silent(comms_graph, initial_state, config)
        return notification_text
    except Exception as e:
        log.error("_invoke_comms_graph: failed", error=str(e))
        return ""


async def _lookup_user_message_content(
    conversation_id: str,
    user_message_id: str,
) -> str:
    """Look up the first 150 chars of a user message for reply-to preview."""
    try:
        conv_doc = await conversations_collection.find_one(
            {
                "conversation_id": conversation_id,
                "messages.message_id": user_message_id,
            },
            {"messages.$": 1},
        )
        if conv_doc and conv_doc.get("messages"):
            return conv_doc["messages"][0].get("response", "")[:150]
    except Exception as e:
        log.warning("_lookup_user_message_content: failed", error=str(e))
    return ""


async def _get_conversation_source(conversation_id: str, user_id: str) -> ConversationSource | None:
    """Return the conversation's persisted originating source (web/whatsapp/...).

    This is the authoritative delivery-routing key: it says which channel the
    conversation belongs to, independent of the run that produced the message
    (so a scheduled/workflow run posting into a bot conversation still routes to
    that platform). Returns None on miss/error — treated as a non-bot conversation.
    """
    try:
        doc = await conversations_collection.find_one(
            {"conversation_id": conversation_id, "user_id": user_id},
            {"source": 1},
        )
    except Exception as e:
        log.warning("_get_conversation_source: lookup failed", error=str(e))
        return None
    return ConversationSource.coerce(doc.get("source")) if doc else None


def _collect_queued_tool_events(
    stream_id: str,
) -> list[dict[str, Any]] | None:
    """Drain the tool event collector for a queued stream into a tool_data list.

    Only called for queued tasks — live tasks already have tool_data on the
    comms ack message (attached by chat_service after the executor finishes).
    """
    collector = get_tool_event_collector(stream_id)
    if not collector:
        return None
    accumulated: dict[str, Any] = {"tool_data": []}
    tool_outputs: dict[str, str] = {}
    for evt in collector:
        absorb_collector_event(evt, accumulated, tool_outputs)
    apply_outputs_to_tool_data(accumulated["tool_data"], tool_outputs)
    reconstruct_subagent_groups(accumulated)
    return accumulated.get("tool_data") or None


async def _broadcast_message(user_id: str, ws_event: dict[str, Any]) -> None:
    """Best-effort WebSocket broadcast with one retry."""
    for attempt in range(2):
        try:
            await websocket_manager.broadcast_to_user(user_id, ws_event)
            return
        except Exception as ws_err:
            log.warning(
                "_broadcast_message: broadcast attempt failed",
                attempt=attempt + 1,
                user_id=user_id,
                error=str(ws_err),
            )
            if attempt == 0:
                await asyncio.sleep(0.5)


@traceable(name="bg_notification_delivery", run_type="chain")
async def _deliver_bg_notification(
    result_text: str,
    msg_type: str,
    conversation_id: str,
    user: dict,
    task_id: str | None = None,
    user_message_id: str | None = None,
    tool_data: list[dict[str, Any]] | None = None,
    is_queued: bool = False,
) -> None:
    """Run comms once with the executor result, then save + deliver the message.

    Comms is invoked silently — no SSE stream. Its generated text becomes the
    user-visible bot message. The executor's terminal text is NOT shown to the
    user directly; it's internal context for comms.

    The message is always saved to the conversation, then delivered over EXACTLY
    ONE transport chosen by the conversation's own ``source``:
      - bot conversations (whatsapp/telegram/discord/slack) → that platform's
        API (bots have no WebSocket — it's their only inbound path)
      - everything else (web/mobile/system) → the WebSocket push web/mobile listen on
    Routing keys on the conversation, not the run that produced the message, so a
    background/scheduled run posting into a bot conversation still reaches it.

    Args:
        result_text: Executor's terminal text (or error message).
        msg_type: "final" or "error" — selects the [EXECUTOR_RESULT/ERROR] prefix.
        conversation_id: Conversation to save the new bot message into.
        user: User dict with user_id, email, name.
        task_id: Optional unique identifier for this executor task.
        user_message_id: Optional ID of the user message that triggered this task,
                         used for reply-to linking.
        tool_data: Optional tool_data entries (only set for queued tasks where
                   no live SSE consumer attached them to a comms ack message).
        is_queued: Whether this task ran from the queue (vs live). Gates the
                   reply-quote attach — live tasks land directly after the
                   user's last message so quoting it is visual noise; queued
                   tasks may have other messages between them and the original.
    """
    user_id = user.get("user_id", "")

    notification_text = await _invoke_comms_graph(result_text, msg_type, conversation_id, user)
    # If comms is unavailable, fall back to the raw executor text rather than
    # dropping the message entirely.
    if not notification_text:
        notification_text = result_text

    bot_message = MessageModel(
        type="bot",
        response=notification_text,
        date=datetime.now(UTC).isoformat(),
    )
    bot_message.message_id = str(uuid4())
    if tool_data:
        bot_message.tool_data = tool_data  # type: ignore[assignment]

    user_msg_content = ""
    show_reply_quote = is_queued and bool(user_message_id)
    if show_reply_quote:
        user_msg_content = await _lookup_user_message_content(conversation_id, user_message_id)
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
        log.error("_deliver_bg_notification: failed to save message", error=str(e))
        return

    # Deliver over exactly one transport, decided by the conversation's source.
    # Bot conversations go to their platform's API; web/mobile/system go to the
    # WebSocket push. (The web conversation list excludes bot sources, so a
    # WebSocket push for a bot conversation would be dropped anyway.)
    conversation_source = await _get_conversation_source(conversation_id, user_id)
    if is_bot_platform(conversation_source):
        delivered = await deliver_message_to_platform(
            conversation_source,
            user_id,
            notification_text,
        )
        transport = "platform"
    else:
        ws_payload: dict[str, Any] = {
            "type": "bot",
            "response": notification_text,
            "message_id": bot_message.message_id,
            "date": bot_message.date,
        }
        if tool_data:
            ws_payload["tool_data"] = tool_data
        if task_id:
            ws_payload["task_id"] = task_id
        if show_reply_quote:
            ws_payload["replyToMessage"] = {
                "id": user_message_id,
                "content": user_msg_content,
                "role": "user",
            }
        await _broadcast_message(
            user_id,
            {
                "type": "conversation.new_message",
                "conversation_id": conversation_id,
                "message": ws_payload,
            },
        )
        delivered = True
        transport = "websocket"

    log.info(
        "_deliver_bg_notification: delivered message",
        message_id=bot_message.message_id,
        task_id=task_id,
        conversation_id=conversation_id,
        conversation_source=conversation_source.value if conversation_source else None,
        transport=transport,
        delivered=delivered,
    )


def _user_from_configurable(configurable: dict[str, Any]) -> dict:
    """Shape a comms-friendly user dict from the executor's configurable."""
    return {
        "user_id": configurable.get("user_id", ""),
        "email": configurable.get("email", ""),
        "name": configurable.get("user_name", ""),
    }


def _cleanup_queued_stream_state(stream_id: str) -> None:
    """Tear down per-stream orchestration state that chat_service would normally clean.

    Queued streams have no chat_service finally block, so this mirror is needed.
    """
    deregister_executor_done_event(stream_id)
    deregister_tool_event_collector(stream_id)
    deregister_pending_subagents(stream_id)
    deregister_executor_spawned(stream_id)
    deregister_bg_subagent_results(stream_id)


async def _dispatch_executor_result(
    *,
    result_text: str,
    result_type: str,
    conversation_id: str,
    user: dict,
    task_id: str | None,
    user_message_id: str | None,
    stream_id: str,
    is_queued: bool,
) -> None:
    """Hand the executor's terminal text to comms and surface the message to the user.

    Live tasks have tool_data attached to the comms ack message by chat_service.
    Queued tasks have no live SSE consumer, so we attach tool_data here instead.
    """
    queued_tool_data = _collect_queued_tool_events(stream_id) if is_queued else None
    try:
        await _deliver_bg_notification(
            result_text=result_text,
            msg_type=result_type,
            conversation_id=conversation_id,
            user=user,
            task_id=task_id,
            user_message_id=user_message_id,
            tool_data=queued_tool_data,
            is_queued=is_queued,
        )
    except Exception as e:
        log.error("Background notification delivery failed", error=str(e))


async def _finalize_executor_run(
    *,
    stream_id: str,
    conversation_id: str,
    user: dict,
    result_text: str,
    result_type: str,
    task_id: str | None,
    user_message_id: str | None,
) -> None:
    """The full post-run cleanup: signal done, notify, tear down state, hand off lock."""
    was_cancelled = bool(stream_id) and await StreamManager.is_cancelled(stream_id)
    is_queued = stream_id.startswith("queued_")

    # Signal SSE consumer that tool events are done so it can drain the collector
    # into the comms ack and publish [DONE]. Comms re-narration runs in parallel.
    done_event = get_executor_done_event(stream_id)
    if done_event is not None:
        done_event.set()

    if was_cancelled:
        log.info(
            "Skipping notification for cancelled executor",
            task_id=task_id,
            stream_id=stream_id,
        )
    elif result_text:
        await _dispatch_executor_result(
            result_text=result_text,
            result_type=result_type,
            conversation_id=conversation_id,
            user=user,
            task_id=task_id,
            user_message_id=user_message_id,
            stream_id=stream_id,
            is_queued=is_queued,
        )

    if is_queued:
        _cleanup_queued_stream_state(stream_id)
        if not was_cancelled:
            await StreamManager.publish_chunk(stream_id, "data: [DONE]\n\n")
            await StreamManager.complete_stream(stream_id)

    # Atomic lock handoff: _process_next_queued_task overwrites the lock before
    # spawning, so a concurrent call_executor cannot grab it via SET NX in a
    # delete→re-set gap. Only release the lock when nothing was handed off.
    spawned_next = await _process_next_queued_task(conversation_id) if not was_cancelled else False
    if not spawned_next:
        await redis_cache.delete(f"{EXECUTOR_BUSY_PREFIX}{conversation_id}")


@traceable(name="executor_background", run_type="chain")
async def run_executor_background(
    task: str,
    configurable: dict[str, Any],
    user_time: datetime,
    stream_id: str,
    conversation_id: str,
    task_id: str | None = None,
    user_message_id: str | None = None,
) -> None:
    """Run executor agent in background and hand its result to comms for delivery.

    Designed for asyncio.create_task(). Never raises — all exceptions
    caught and routed through comms as an [EXECUTOR_ERROR] message.

    Tool events stream live to the SSE consumer during execution. When
    execution finishes:
      1. The executor-done event is set so any waiting chat stream can
         close the SSE.
      2. _deliver_bg_notification invokes comms with the executor result
         as internal context and posts the user-facing message via WS.

    Inherits `langfuse_trace_id` from the parent's `configurable` so this run's
    LLM/tool spans land on the same Langfuse trace as comms.
    """
    user = _user_from_configurable(configurable)
    result_text = ""
    result_type = "final"

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
            log.error("Background executor prep failed", error=result_text)
        else:
            writer = make_redis_stream_writer(stream_id)
            result_text = await execute_subagent_stream(ctx=ctx, stream_writer=writer)
            log.info(
                "Background executor completed",
                task_id=task_id,
                stream_id=stream_id,
            )
    except Exception as e:
        log.error("Background executor failed", stream_id=stream_id, error=str(e))
        result_text = str(e)
        result_type = "error"
    finally:
        await _finalize_executor_run(
            stream_id=stream_id,
            conversation_id=conversation_id,
            user=user,
            result_text=result_text,
            result_type=result_type,
            task_id=task_id,
            user_message_id=user_message_id,
        )


async def _process_next_queued_task(conversation_id: str) -> bool:
    """Pop the next queued task for this conversation and spawn it.

    Called from run_executor_background's finally block. Overwrites the executor
    busy lock with the next task's value (no intervening delete) before spawning,
    so the queued run inherits the lock atomically and a concurrent call_executor
    cannot acquire it via SET NX in a delete→re-set gap.

    Returns True if a queued task was popped and spawned (caller keeps the lock),
    False if the queue was empty or unparseable (caller releases the lock).
    """
    if not redis_cache.client:
        return False

    queue_key = f"{EXECUTOR_QUEUE_PREFIX}{conversation_id}"
    raw = await redis_cache.client.lpop(queue_key)
    if not raw:
        return False

    try:
        item: dict = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as e:
        log.error(
            "Failed to parse queued executor task",
            conversation_id=conversation_id,
            error=str(e),
        )
        return False

    task = item.get("task", "")
    task_id = item.get("task_id")
    queued_user_message_id = item.get("user_message_id")
    configurable: dict = item.get("configurable", {})
    user_time_str: str = item.get("user_time_str", "")
    user_time = datetime.fromisoformat(user_time_str) if user_time_str else datetime.now()

    queued_stream_id = f"queued_{uuid4()}"
    user_id: str = configurable.get("user_id", "")

    lock_key = f"{EXECUTOR_BUSY_PREFIX}{conversation_id}"
    await redis_cache.set(lock_key, f"{queued_stream_id}:{task_id}", ttl=1800)

    mark_executor_spawned(queued_stream_id)
    # Queued runs have no chat_service to register the collector for them.
    register_tool_event_collector(queued_stream_id)

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
        "Queued executor task spawned",
        task_id=task_id,
        conversation_id=conversation_id,
        stream_id=queued_stream_id,
    )
    return True
