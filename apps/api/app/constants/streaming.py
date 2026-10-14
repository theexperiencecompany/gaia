"""
Streaming constants for Redis pub/sub background execution.

Used by:
- stream_manager.py
- Tests
"""

from enum import StrEnum
from typing import Final

# Special control messages for pub/sub channel
STREAM_DONE_SIGNAL = "__STREAM_DONE__"
STREAM_CANCELLED_SIGNAL = "__STREAM_CANCELLED__"
STREAM_ERROR_SIGNAL = "__STREAM_ERROR__"

# WebSocket control event pushed when an executor task is cancelled by the
# agent (cancel_executor), so the client can clear the stuck executor-pending
# loading state and finalize any in-flight tool cards.
WS_EVENT_EXECUTOR_CANCELLED = "executor.cancelled"

# WebSocket event announcing a detached run's own stream, and how the client folds it.
WS_EVENT_EXECUTOR_STREAM_STARTED = "executor.stream_started"


class DetachedStreamKind(StrEnum):
    """How a client folds a detached stream (mirrored in the web ExecutorStreamStartedEvent).

    An executor run owns its message's text, cards and status; a background
    subagent, or a background browser job, only upserts its own cards into a
    message another run may still be writing.
    """

    EXECUTOR = "executor"
    SUBAGENT = "subagent"


# SSE keepalive frame and cadence, well under a reverse proxy's silent-connection
# read timeout (nginx defaults to 60s). Byte-sensitive (no space after the colon)
# — see models/stream_events.py.
SSE_KEEPALIVE_INTERVAL_SECONDS: Final[float] = 15.0
SSE_KEEPALIVE_FRAME: Final[str] = 'data: {"keepalive":true}\n\n'
