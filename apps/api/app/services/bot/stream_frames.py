"""Bot SSE wire frames.

Every frame a bot chat stream can put on the wire, built in one place instead
of hand-formatted at each yield site in ``endpoints/bot.py``. The bot adapters
switch on these exact shapes, so the wire bytes are the contract: see
``tests/unit/services/bot/test_stream_frames.py``, which pins each builder
against the literal it replaced.
"""

from collections.abc import Mapping
import json
from typing import Any

# The single generic keepalive the transport (not the agent) emits: an SSE
# comment line, which every client ignores while still resetting proxy and
# client inactivity timers. Not a `data:` frame, so it has no JSON body.
_COMMENT_KEEPALIVE = ": keepalive\n\n"


def sse_frame(data: Mapping[str, Any]) -> str:
    """Serialize one payload as an SSE ``data:`` frame.

    Note: the bot protocol never names an ``event:`` — every frame is a bare
    ``data:`` line whose JSON body carries the discriminator key (``text``,
    ``error``, ``notice``, ...), so this takes no event argument.
    """
    return f"data: {json.dumps(data)}\n\n"


def session_token_frame(session_token: str) -> str:
    """The first frame of every stream: the short-lived bot session token."""
    return sse_frame({"session_token": session_token})


def comment_keepalive_frame() -> str:
    """The SSE comment that opens the connection and keeps proxies awake."""
    return _COMMENT_KEEPALIVE


def keepalive_frame() -> str:
    """A forwarded keepalive, so bot clients reset their inactivity timers."""
    return sse_frame({"keepalive": True})


def text_frame(text: str) -> str:
    """Assistant text for the message in flight (web ``response`` renamed)."""
    return sse_frame({"text": text})


def notice_frame(notice_text: str) -> str:
    """Free-form out-of-band text (paywall, rate limit) the client delivers itself."""
    return sse_frame({"notice": {"text": notice_text}})


def approval_frame(approval_payload: Mapping[str, Any]) -> str:
    """A HIL approval card, rendered by the bot client as an out-of-band prompt."""
    return sse_frame({"approval": approval_payload})


def message_boundary_frame(boundary: object) -> str:
    """An assistant message ended — the client closes (or retracts) its bubble."""
    return sse_frame({"message_boundary": boundary})


def error_frame(error_code: str) -> str:
    """A terminal error. The code is the contract the bot adapters switch on."""
    return sse_frame({"error": error_code})


def done_frame(conversation_id: str) -> str:
    """The terminal success frame, naming the conversation the turn landed in."""
    return sse_frame({"done": True, "conversation_id": conversation_id})


def stream_error_frame() -> str:
    """The generic failure told to the bot when the Redis subscription breaks."""
    return error_frame("Stream error occurred")
