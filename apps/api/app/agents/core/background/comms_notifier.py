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


async def _stream_notification_tokens(
    prefix: str,
    msg_text: str,
    user_name: str,
    stream_id: str,
) -> str:
    """Call the LLM with astream and publish tokens to the SSE stream as they arrive.

    Bypasses the comms graph entirely to avoid checkpoint-continuation issues
    (empty LLM responses, middleware interference). Streams tokens directly so
    the SSE connection stays alive during inference and the notification appears
    progressively to the user.

    Args:
        prefix: [EXECUTOR_RESULT], [EXECUTOR_UPDATE], or [EXECUTOR_ERROR]
        msg_text: The executor result/update/error text.
        user_name: User's name for prompt personalisation.
        stream_id: Active SSE stream ID to publish tokens to.

    Returns:
        Full notification text accumulated from all tokens, or empty string on failure.
    """
    try:
        llm = init_llm()
        system_prompt = COMMS_AGENT_PROMPT.replace("{user_name}", user_name or "there")
        accumulated = ""
        async for chunk in llm.astream([
            SystemMessage(content=system_prompt),
            HumanMessage(content=f"{prefix}\n{msg_text}"),
        ]):
            token = chunk.content if isinstance(chunk.content, str) else ""
            token = token.replace(NEW_MESSAGE_BREAKER, "")
            if token:
                accumulated += token
                await stream_manager.publish_chunk(
                    stream_id,
                    f"data: {json.dumps({'response': token})}\n\n",
                )
        return accumulated.strip()
    except Exception as e:
        log.error(f"_stream_notification_tokens failed: {e}", exc_info=True)
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
            # Stream tokens directly from the LLM to the SSE stream.
            # Graph-based invocation (graph.ainvoke / execute_graph_silent) returns
            # "Empty response from model." on checkpoint-continuation runs due to
            # middleware interference. Streaming tokens directly keeps the SSE
            # connection alive during inference and shows the notification progressively.
            notification_message = await _stream_notification_tokens(
                prefix=prefix,
                msg_text=msg_text,
                user_name=user_name,
                stream_id=stream_id,
            )

            if notification_message:
                complete_message = notification_message
                log.info(
                    f"Comms notifier streamed notification for stream {stream_id}"
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
