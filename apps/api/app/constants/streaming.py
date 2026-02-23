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
