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

# WebSocket control event pushed to web/mobile when an executor task is
# cancelled by the agent (cancel_executor). The frontend cannot otherwise learn
# of an agent-initiated cancel — it lets the client clear the stuck
# executor-pending loading state and finalize any in-flight tool cards.
WS_EVENT_EXECUTOR_CANCELLED = "executor.cancelled"

# SSE keepalive frame and cadence.
#
# `StreamManager.subscribe_stream` emits one when the Redis event log goes idle;
# `with_heartbeat` emits one when nothing has reached the SOCKET for the same
# interval, whatever the reason. Both must stay well under the read timeout a
# reverse proxy applies to a silent upstream connection (nginx defaults to 60s).
#
# The frame is byte-sensitive: the compact literal (no space after the colon) is
# the shape the frontend parser has always received. See models/stream_events.py.
SSE_KEEPALIVE_INTERVAL_SECONDS: Final[float] = 15.0
SSE_KEEPALIVE_FRAME: Final[str] = 'data: {"keepalive":true}\n\n'
