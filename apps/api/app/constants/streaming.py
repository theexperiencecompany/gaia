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

# Every chat stream frame is one "data: <json>" line.
SSE_DATA_PREFIX: Final[str] = "data: "
