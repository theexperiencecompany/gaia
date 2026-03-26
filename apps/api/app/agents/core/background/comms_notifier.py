"""Comms notifier loop — reads executor updates, runs comms graph, streams to user.

This coroutine runs concurrently with run_executor_background via
asyncio.gather in _run_chat_stream. It reads messages from the comms
inbox queue and invokes the comms_graph for each one, sequentially.

Sequential processing is critical: concurrent comms_graph invocations
on the same thread_id cause PostgreSQL checkpointer serialization errors.

Message types:
- {"type": "progress", "message": "..."} → comms sees [EXECUTOR_UPDATE]
- {"type": "final", "message": "..."}    → comms sees [EXECUTOR_RESULT]
- {"type": "error", "message": "..."}    → comms sees [EXECUTOR_ERROR]
- None                                    → sentinel, loop exits
"""

import asyncio
import json
from datetime import datetime
from typing import Any

from langchain_core.messages import HumanMessage

from shared.py.wide_events import log

from app.agents.core.graph_manager import GraphManager
from app.core.stream_manager import stream_manager
from app.helpers.agent_helpers import build_agent_config, execute_graph_streaming
from app.utils.stream_utils import process_data_chunk

# Map message type to prefix the comms agent sees
_TYPE_PREFIX = {
    "progress": "[EXECUTOR_UPDATE]",
    "final": "[EXECUTOR_RESULT]",
    "error": "[EXECUTOR_ERROR]",
}


async def run_comms_notifier(
    comms_inbox: asyncio.Queue[Any],
    conversation_id: str,
    user: dict[str, Any],
    user_time: datetime,
    stream_id: str,
    tool_data: dict[str, Any],
    tool_outputs: dict[str, str],
    todo_progress_accumulated: dict[str, Any],
    follow_up_actions: list[str],
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

    # Build config once — thread_id/stream_id don't change across iterations
    config = build_agent_config(
        conversation_id=conversation_id,
        user=user,
        user_time=user_time,
        thread_id=conversation_id,
        agent_name="comms_agent",
    )
    config.setdefault("configurable", {})["stream_id"] = stream_id

    while True:
        try:
            item = await asyncio.wait_for(comms_inbox.get(), timeout=300.0)
        except asyncio.TimeoutError:
            log.warning(
                f"run_comms_notifier: timed out waiting for inbox item on stream {stream_id}"
            )
            break

        # Sentinel: executor done, exit loop
        if item is None:
            break

        msg_type = item.get("type", "progress")
        msg_text = item.get("message", "")
        prefix = _TYPE_PREFIX.get(msg_type, "[EXECUTOR_UPDATE]")

        log.info(f"Comms notifier processing {msg_type} for stream {stream_id}")

        # Inject message as HumanMessage into the comms thread
        initial_state = {"messages": [HumanMessage(content=f"{prefix}\n{msg_text}")]}

        try:
            async for chunk in execute_graph_streaming(graph, initial_state, config):
                # Check cancellation
                if await stream_manager.is_cancelled(stream_id):
                    log.info(f"Comms notifier cancelled for stream {stream_id}")
                    return complete_message

                # Skip [DONE] marker — we send it in _run_chat_stream
                if chunk == "data: [DONE]\n\n":
                    continue

                # Process nostream marker (internal complete_message)
                if chunk.startswith("nostream: "):
                    nostream_json = json.loads(chunk.removeprefix("nostream: "))
                    if (
                        isinstance(nostream_json, dict)
                        and "complete_message" in nostream_json
                    ):
                        complete_message = str(nostream_json["complete_message"])
                    continue

                # Process data chunks (tool_data, tool_output, etc.)
                if chunk.startswith("data: "):
                    try:
                        follow_up_actions, _ = await process_data_chunk(
                            stream_id,
                            chunk,
                            tool_data,
                            tool_outputs,
                            todo_progress_accumulated,
                            follow_up_actions,
                        )
                    except Exception as e:
                        log.error(f"Error processing notifier chunk: {e}")
                        await stream_manager.publish_chunk(stream_id, chunk)
                else:
                    await stream_manager.publish_chunk(stream_id, chunk)

        except Exception as e:
            log.error(f"Comms notifier graph error for stream {stream_id}: {e}")
            await stream_manager.publish_chunk(
                stream_id,
                f"data: {json.dumps({'error': f'Notification error: {str(e)}'})}\n\n",
            )

    return complete_message
