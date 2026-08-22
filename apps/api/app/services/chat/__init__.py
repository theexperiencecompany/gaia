"""Chat streaming package.

Holds the Redis-backed background chat streaming pipeline. Split by concern:
``stream`` orchestrates a single turn; ``chunks`` parses SSE chunks emitted by
the agent; ``state`` aggregates running token / tool-data state; ``workspace``
bumps the session's last_active; ``artifact_forwarder`` forwards artifact events
to the stream and the conversation registry; ``persistence`` writes the finished
conversation to MongoDB and bills token usage.

Import sub-modules directly (``from app.services.chat.stream import
run_chat_stream_background``) — re-exporting through this ``__init__`` would
eagerly pull ``stream.py``'s ``app.agents.core.agent`` dependency, creating an
import cycle with the agent helpers that consume :func:`extract_tool_data` from
``chunks``.
"""
