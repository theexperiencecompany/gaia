"""
Streaming constants for Redis pub/sub background execution.

Used by:
- stream_manager.py
- Tests
"""

# Special control messages for pub/sub channel
STREAM_DONE_SIGNAL = "__STREAM_DONE__"
STREAM_CANCELLED_SIGNAL = "__STREAM_CANCELLED__"
STREAM_ERROR_SIGNAL = "__STREAM_ERROR__"

# WebSocket control event pushed to web/mobile when an executor task is
# cancelled by the agent (cancel_executor). The frontend cannot otherwise learn
# of an agent-initiated cancel — it lets the client clear the stuck
# executor-pending loading state and finalize any in-flight tool cards.
WS_EVENT_EXECUTOR_CANCELLED = "executor.cancelled"
