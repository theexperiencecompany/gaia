"""
Streaming constants for Redis pub/sub background execution.

Used by:
- stream_manager.py
- Tests
"""

from typing import Final

# Special control messages for pub/sub channel
STREAM_DONE_SIGNAL = "__STREAM_DONE__"
STREAM_CANCELLED_SIGNAL = "__STREAM_CANCELLED__"
STREAM_ERROR_SIGNAL = "__STREAM_ERROR__"

# WebSocket control event pushed when an executor task is cancelled by the
# agent (cancel_executor), so the client can clear the stuck executor-pending
# loading state and finalize any in-flight tool cards.
WS_EVENT_EXECUTOR_CANCELLED = "executor.cancelled"

# SSE keepalive frame and cadence, well under a reverse proxy's silent-connection
# read timeout (nginx defaults to 60s). Byte-sensitive (no space after the colon)
# — see models/stream_events.py.
SSE_KEEPALIVE_INTERVAL_SECONDS: Final[float] = 15.0
SSE_KEEPALIVE_FRAME: Final[str] = 'data: {"keepalive":true}\n\n'
