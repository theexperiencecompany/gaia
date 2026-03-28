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

from langchain_core.messages import SystemMessage
from langsmith import traceable

from shared.py.wide_events import log

from app.agents.core.graph_manager import GraphManager
from app.core.stream_manager import stream_manager
from app.helpers.agent_helpers import build_agent_config, execute_graph_silent

# Map message type to prefix the comms agent sees
_TYPE_PREFIX = {
    "progress": "[EXECUTOR_UPDATE]",
    "final": "[EXECUTOR_RESULT]",
    "error": "[EXECUTOR_ERROR]",
}


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

    graph = await GraphManager.get_graph("comms_agent")
    if not graph:
        log.error("run_comms_notifier: comms graph not available")
        return complete_message

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

        # Build config for this comms invocation (same thread_id = full history)
        config = build_agent_config(
            conversation_id=conversation_id,
            user=user,
            user_time=user_time,
            thread_id=conversation_id,
            agent_name="comms_agent",
        )
        config.setdefault("configurable", {})["stream_id"] = stream_id

        # Inject as SystemMessage so the LLM treats it as background context
        # injected by the system, not as a new message from the user. This keeps
        # the conversation thread coherent: User → AI → [System: executor result] → AI.
        initial_state = {"messages": [SystemMessage(content=f"{prefix}\n{msg_text}")]}

        # Push a visual break so this response renders as a separate bubble
        # from the comms ack ("I'm on it") that preceded it.
        await stream_manager.publish_chunk(
            stream_id,
            f"data: {json.dumps({'response': '<NEW_MESSAGE_BREAK>'})}\n\n",
        )

        try:
            # Use silent execution and publish the complete response as a single
            # chunk. The streaming path's per-event agent_name check is unreliable
            # for the second comms run (LangGraph checkpoint continuation), but
            # execute_graph_silent reliably captures the full response text.
            notification_message, _ = await execute_graph_silent(
                graph, initial_state, config
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
            log.error(f"Comms notifier graph error for stream {stream_id}: {e}")
            await stream_manager.publish_chunk(
                stream_id,
                f"data: {json.dumps({'error': f'Notification error: {str(e)}'})}\n\n",
            )

    return complete_message
