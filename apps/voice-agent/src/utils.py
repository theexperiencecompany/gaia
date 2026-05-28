"""Pure utility functions for the voice agent — sanitization, metadata extraction, timing."""

import json
import time
from datetime import datetime
from typing import Optional

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


def split_response_for_ui_and_tts(piece: str) -> tuple[str, str]:
    """Split a backend `response` fragment into (ui_only, tts_text).

    `ui_only` is the concatenation, in source order, of every substring that
    the TTS sanitiser would strip from the spoken stream: OpenUI fences,
    directive prefixes, HTML-style tags, and sentinel tokens. These are the
    fragments the frontend needs immediately so OpenUI cards and structured
    markup render in the bot bubble without waiting on TTS alignment.

    Overlapping matches are deduplicated by keeping the earliest start and
    the longest reach (so an `:::openui ... :::` fence subsumes the inner
    `:::openui` directive-prefix match).

    `tts_text` is the spoken slice — what `sanitize_for_tts` produces.
    """
    if not piece:
        return "", ""
    spans: list[tuple[int, int]] = []
    for pattern in (OPENUI_FENCE_RE, DIRECTIVE_PREFIX_RE, TAG_RE, SENTINEL_RE):
        for m in pattern.finditer(piece):
            spans.append((m.start(), m.end()))
    spans.sort()
    merged: list[tuple[int, int]] = []
    for start, end in spans:
        if merged and start < merged[-1][1]:
            prev_start, prev_end = merged[-1]
            merged[-1] = (prev_start, max(prev_end, end))
        else:
            merged.append((start, end))
    ui_only = "".join(piece[s:e] for s, e in merged)
    tts_text = sanitize_for_tts(piece)
    return ui_only, tts_text


def has_open_tag_at_tail(s: str) -> bool:
    """True when the string ends inside an open tag (last `<` is later than last `>`)."""
    last_open = s.rfind("<")
    if last_open == -1:
        return False
    return s.rfind(">") < last_open


def has_open_openui_fence_at_tail(s: str) -> bool:
    """True when the buffer contains a ':::openui' that has no closing ':::' after it."""
    return OPEN_OPENUI_FENCE_TAIL_RE.search(s) is not None


def extract_meta_data(md: Optional[str]) -> tuple[Optional[str], Optional[str]]:
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
    except Exception:
        return None, None


def extract_latest_user_text(chat_ctx: ChatContext) -> str:
    """Best-effort extraction of the latest user text string from ChatContext."""
    for item in reversed(chat_ctx.items):
        role = getattr(item, "role", item.__class__.__name__.lower())
        if role == "user":
            content = getattr(item, "content", [getattr(item, "output", "")])
            parts = []
            for c in content:
                if hasattr(c, "model_dump"):
                    d = c.model_dump()
                    if isinstance(d, dict):
                        parts.append(d.get("text", ""))
                else:
                    parts.append(str(c))
            out = " ".join(p for p in parts if p)
            if out:
                return out
    return ""


def now_ts() -> str:
    """Current wall-clock time as HH:MM:SS.mmm for human-readable debug logs."""
    now = datetime.now()
    return now.strftime("%H:%M:%S.") + f"{now.microsecond // 1000:03d}"


def ms_since(t0: float) -> float:
    """Return milliseconds elapsed since t0 (from time.monotonic())."""
    return (time.monotonic() - t0) * 1000


__all__ = [
    "sanitize_for_tts",
    "split_response_for_ui_and_tts",
    "has_open_tag_at_tail",
    "has_open_openui_fence_at_tail",
    "extract_meta_data",
    "extract_latest_user_text",
    "now_ts",
    "ms_since",
]
