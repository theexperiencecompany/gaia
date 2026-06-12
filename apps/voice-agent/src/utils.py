"""Pure utility functions for the voice agent — sanitization, metadata extraction, timing."""

from datetime import datetime
import json
import time

from livekit.agents.llm import ChatContext

from shared.py.logging import get_contextual_logger
from src.constants import (
    DIRECTIVE_PREFIX_RE,
    MARKDOWN_RE,
    OPEN_OPENUI_FENCE_TAIL_RE,
    OPENUI_FENCE_RE,
    SENTINEL_RE,
    TAG_RE,
    WHITESPACE_RE,
)

logger = get_contextual_logger("voice")


def sanitize_for_tts(piece: str) -> str:
    """Strip OpenUI fences, directive prefixes, tags, sentinels, and markdown from a chunk."""
    piece = OPENUI_FENCE_RE.sub(" ", piece)
    piece = DIRECTIVE_PREFIX_RE.sub(" ", piece)
    piece = TAG_RE.sub(" ", piece)
    piece = SENTINEL_RE.sub(" ", piece)
    piece = MARKDOWN_RE.sub(" ", piece)
    return WHITESPACE_RE.sub(" ", piece).strip()


def has_open_tag_at_tail(s: str) -> bool:
    """True when the string ends inside an open tag (last `<` is later than last `>`)."""
    last_open = s.rfind("<")
    if last_open == -1:
        return False
    return s.rfind(">") < last_open


def has_open_openui_fence_at_tail(s: str) -> bool:
    """True when the buffer contains a ':::openui' that has no closing ':::' after it."""
    return OPEN_OPENUI_FENCE_TAIL_RE.search(s) is not None


def extract_meta_data(md: str | None) -> tuple[str | None, str | None]:
    """Extract agentToken and conversationId from participant metadata JSON."""
    if not md:
        return None, None
    try:
        obj = json.loads(md)
        token = obj.get("agentToken")
        conv_id = obj.get("conversationId")
        token = token if isinstance(token, str) and token else None
        conv_id = conv_id if isinstance(conv_id, str) and conv_id else None
        return token, conv_id
    except (json.JSONDecodeError, AttributeError, TypeError) as e:
        logger.debug("Unparseable participant metadata", error=str(e), metadata=md[:200])
        return None, None


def _extract_text_from_content(content: list) -> str:  # type: ignore[type-arg]
    """Extract plain text from a LiveKit ChatContext content list."""
    parts = []
    for c in content:
        if hasattr(c, "model_dump"):
            d = c.model_dump()
            if isinstance(d, dict):
                parts.append(d.get("text", ""))
        else:
            parts.append(str(c))
    return " ".join(p for p in parts if p)


def extract_latest_user_text(chat_ctx: ChatContext) -> str:
    """Best-effort extraction of the latest user text string from ChatContext."""
    for item in reversed(chat_ctx.items):
        role = getattr(item, "role", item.__class__.__name__.lower())
        if role == "user":
            content = getattr(item, "content", [getattr(item, "output", "")])
            out = _extract_text_from_content(content)
            if out:
                return out
    return ""


def build_messages_from_ctx(chat_ctx: ChatContext) -> list[dict[str, str]]:
    """Build a [{role, content}] list from LiveKit's ChatContext for backend API."""
    messages = []
    for item in chat_ctx.items:
        role = getattr(item, "role", item.__class__.__name__.lower())
        if role not in ("user", "assistant"):
            continue
        content = getattr(item, "content", [getattr(item, "output", "")])
        text = _extract_text_from_content(content)
        if text:
            messages.append({"role": role, "content": text})
    return messages


def now_ts() -> str:
    """Current wall-clock time as HH:MM:SS.mmm for human-readable debug logs."""
    now = datetime.now()
    return now.strftime("%H:%M:%S.") + f"{now.microsecond // 1000:03d}"


def ms_since(t0: float) -> float:
    """Return milliseconds elapsed since t0 (from time.monotonic())."""
    return (time.monotonic() - t0) * 1000


__all__ = [
    "sanitize_for_tts",
    "has_open_tag_at_tail",
    "has_open_openui_fence_at_tail",
    "extract_meta_data",
    "extract_latest_user_text",
    "build_messages_from_ctx",
    "now_ts",
    "ms_since",
]
