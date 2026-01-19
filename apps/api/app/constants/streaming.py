"""
Streaming constants for Redis pub/sub background execution.

Used by:
- stream_manager.py
- Tests
"""

# Redis key prefixes for stream management
STREAM_CHANNEL_PREFIX = "stream:channel:"
STREAM_SIGNAL_PREFIX = "stream:signal:"
STREAM_PROGRESS_PREFIX = "stream:progress:"

# Time-to-live for Redis keys (auto-cleanup after 5 minutes)
STREAM_TTL = 300

# Special control messages for pub/sub channel
STREAM_DONE_SIGNAL = "__STREAM_DONE__"
STREAM_CANCELLED_SIGNAL = "__STREAM_CANCELLED__"
STREAM_ERROR_SIGNAL = "__STREAM_ERROR__"
