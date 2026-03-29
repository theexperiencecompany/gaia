"""Comms notifier loop — drains executor messages to keep SSE alive.

This coroutine runs SEQUENTIALLY after the comms agent finishes in
_run_chat_stream. It blocks on the comms inbox queue waiting for the
executor sentinel (None), keeping the SSE connection alive so the
frontend can receive live tool events from the executor.

Notification text is NOT generated here — _deliver_bg_notification in
executor_runner.py handles that via WebSocket + comms checkpoint injection.
This avoids duplicate notifications (SSE + WebSocket) and ensures the
notification is always in the conversation history.

Message types consumed:
- {"type": "progress", "message": "..."} → logged, not streamed
- {"type": "final", "message": "..."}    → logged, not streamed
- {"type": "error", "message": "..."}    → logged, not streamed
- None                                    → sentinel, loop exits
"""

import asyncio
from datetime import datetime
from typing import Any

from langsmith import traceable
from shared.py.wide_events import log

from app.core.stream_manager import stream_manager


@traceable(name="comms_notifier", run_type="chain")
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
    """Drain comms inbox to keep SSE alive for executor tool events.

    Notification delivery is handled by _deliver_bg_notification via
    WebSocket, not by this function. This just waits for the sentinel
    so the SSE stream stays open for live tool event streaming.

    Returns empty string (notification text is delivered separately).

    Args:
        comms_inbox: Queue populated by executor (notify_comms tool + final result).
        conversation_id: Thread ID for logging.
        user: User dict (unused, kept for interface compatibility).
        user_time: User's local time (unused, kept for interface compatibility).
        stream_id: Active SSE stream ID.
        tool_data: Mutable dict (unused, kept for interface compatibility).
        tool_outputs: Mutable dict (unused, kept for interface compatibility).
        todo_progress_accumulated: Mutable dict (unused, kept for interface compatibility).
        follow_up_actions: Mutable list (unused, kept for interface compatibility).

    Returns:
        Empty string — notification text is delivered via WebSocket.
    """
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
            log.info(f"Comms notifier received sentinel for stream {stream_id}")
            break

        # Check cancellation before processing
        if await stream_manager.is_cancelled(stream_id):
            log.info(f"Comms notifier cancelled for stream {stream_id}")
            return ""

        msg_type = item.get("type", "progress")
        log.info(f"Comms notifier drained {msg_type} message for stream {stream_id}")

    return ""
