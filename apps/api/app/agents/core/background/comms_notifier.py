"""Comms notifier loop — reads executor updates, runs comms graph, streams to user.

This coroutine runs SEQUENTIALLY after the comms agent finishes in
_run_chat_stream. The comms agent naturally completes first (sending
"I'm on it!" acknowledgement), then this notifier blocks on the comms
inbox queue waiting for executor progress/final messages, invoking the
comms_graph for each one in order.

Sequential processing is intentional: concurrent comms_graph invocations
on the same thread_id would cause PostgreSQL checkpointer serialization
errors. The executor background task always pushes a sentinel (None) when
done, which causes this loop to exit.

Message types:
- {"type": "progress", "message": "..."} → comms sees [EXECUTOR_UPDATE]
- {"type": "final", "message": "..."}    → comms sees [EXECUTOR_RESULT]
- {"type": "error", "message": "..."}    → comms sees [EXECUTOR_ERROR]
- None                                    → sentinel, loop exits
"""

import asyncio
import json
from datetime import datetime
from typing import Any, Dict, List

from langchain_core.messages import HumanMessage, SystemMessage
from langsmith import traceable

from shared.py.wide_events import log

from app.agents.llm.client import init_llm
from app.agents.prompts.comms_prompts import COMMS_AGENT_PROMPT
from app.constants.general import NEW_MESSAGE_BREAKER
from app.core.stream_manager import stream_manager

# Map message type to prefix the comms agent sees
_TYPE_PREFIX = {
    "progress": "[EXECUTOR_UPDATE]",
    "final": "[EXECUTOR_RESULT]",
    "error": "[EXECUTOR_ERROR]",
}


async def _generate_notification_text(
    prefix: str,
    msg_text: str,
    user_name: str,
) -> str:
    """Call the LLM directly to generate a user-facing notification message.

    Bypasses the comms graph entirely to avoid checkpoint-continuation issues
    (empty LLM responses, middleware interference). Produces a standalone,
    persona-consistent notification using only the COMMS_AGENT_PROMPT + the
    executor result as context.

    Args:
        prefix: [EXECUTOR_RESULT], [EXECUTOR_UPDATE], or [EXECUTOR_ERROR]
        msg_text: The executor result/update/error text.
        user_name: User's name for prompt personalisation.

    Returns:
        Clean notification text, or empty string on failure.
    """
    try:
        llm = init_llm()
        system_prompt = COMMS_AGENT_PROMPT.replace("{user_name}", user_name or "there")
        response = await llm.ainvoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=f"{prefix}\n{msg_text}"),
        ])
        content = response.content if isinstance(response.content, str) else ""
        # Strip the NEW_MESSAGE_BREAKER sentinel — acall_model appends it but
        # since we're calling the LLM directly it won't be there; strip defensively.
        return content.replace(NEW_MESSAGE_BREAKER, "").strip()
    except Exception as e:
        log.error(f"_generate_notification_text failed: {e}")
        return ""


@traceable(name="comms_notifier", run_type="chain")
async def run_comms_notifier(
    comms_inbox: asyncio.Queue,
    conversation_id: str,
    user: dict,
    user_time: datetime,
    stream_id: str,
    tool_data: Dict[str, Any],
    tool_outputs: Dict[str, str],
    todo_progress_accumulated: Dict[str, Any],
    follow_up_actions: List[str],
) -> str:
    """Read comms inbox and invoke comms_graph for each executor message.

    Returns the last complete_message from the comms graph (used for
    MongoDB save in _run_chat_stream).

    Args:
        comms_inbox: Queue populated by executor (notify_comms tool + final result).
        conversation_id: Thread ID for comms_graph checkpoint continuity.
        user: User dict with user_id, email, name.
        user_time: User's local time.
        stream_id: Active SSE stream ID.
        tool_data: Mutable dict accumulating tool_data entries for MongoDB save.
        tool_outputs: Mutable dict accumulating tool outputs.
        todo_progress_accumulated: Mutable dict accumulating todo progress.
        follow_up_actions: Mutable list accumulating follow-up actions.

    Returns:
        The complete_message from the last comms graph invocation.
    """
    complete_message = ""
    user_name = user.get("name", "")

    while True:
        item = await comms_inbox.get()

        # Sentinel: executor done, exit loop
        if item is None:
            break

        # Check cancellation before processing
        if await stream_manager.is_cancelled(stream_id):
            log.info(f"Comms notifier cancelled for stream {stream_id}")
            return complete_message

        msg_type = item.get("type", "progress")
        msg_text = item.get("message", "")
        prefix = _TYPE_PREFIX.get(msg_type, "[EXECUTOR_UPDATE]")

        log.info(f"Comms notifier processing {msg_type} for stream {stream_id}")

        # Push a visual break so this response renders as a separate bubble
        # from the comms ack ("I'm on it") that preceded it.
        await stream_manager.publish_chunk(
            stream_id,
            f"data: {json.dumps({'response': '<NEW_MESSAGE_BREAK>'})}\n\n",
        )

        try:
            # Call the LLM directly instead of going through the comms graph.
            # Graph-based invocation (graph.ainvoke / execute_graph_silent) returns
            # "Empty response from model." on checkpoint-continuation runs due to
            # middleware interference. Direct LLM call is simple and reliable:
            # COMMS_AGENT_PROMPT + executor result → persona-consistent notification.
            notification_message = await _generate_notification_text(
                prefix=prefix,
                msg_text=msg_text,
                user_name=user_name,
            )

            if notification_message:
                complete_message = notification_message
                await stream_manager.publish_chunk(
                    stream_id,
                    f"data: {json.dumps({'response': notification_message})}\n\n",
                )
                log.info(
                    f"Comms notifier published notification for stream {stream_id}"
                )
            else:
                log.warning(
                    f"Comms notifier: empty notification for stream {stream_id}"
                )

        except Exception as e:
            log.error(f"Comms notifier error for stream {stream_id}: {e}")
            await stream_manager.publish_chunk(
                stream_id,
                f"data: {json.dumps({'error': f'Notification error: {str(e)}'})}\n\n",
            )

    return complete_message
