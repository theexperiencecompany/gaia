"""Pure utility functions for the voice agent — sanitization, metadata extraction, timing."""

import json
import time
from typing import NamedTuple

from shared.py.analytics import UserId
from shared.py.wide_events import log
from src.constants import (
    DIRECTIVE_PREFIX_RE,
    MARKDOWN_RE,
    OPEN_OPENUI_FENCE_TAIL_RE,
    OPENUI_FENCE_RE,
    SENTINEL_RE,
    TAG_RE,
    WHITESPACE_RE,
    LogTag,
)


def sanitize_for_tts(piece: str) -> str:
    """Strip OpenUI fences, directive prefixes, tags, sentinels, and markdown from a chunk."""
    piece = OPENUI_FENCE_RE.sub(" ", piece)
    piece = DIRECTIVE_PREFIX_RE.sub(" ", piece)
    piece = TAG_RE.sub(" ", piece)
    piece = SENTINEL_RE.sub(" ", piece)
    piece = MARKDOWN_RE.sub(" ", piece)
    return WHITESPACE_RE.sub(" ", piece).strip()


def has_open_tag_at_tail(s: str) -> bool:
    """Return True when the string ends inside an open tag (last < is later than last >)."""
    last_open = s.rfind("<")
    if last_open == -1:
        return False
    return s.rfind(">") < last_open


def has_open_openui_fence_at_tail(s: str) -> bool:
    """Return True when the buffer has an open ':::openui' fence with no closing ':::'."""
    return OPEN_OPENUI_FENCE_TAIL_RE.search(s) is not None


class ParticipantMeta(NamedTuple):
    """Session credentials carried in the LiveKit participant metadata."""

    agent_token: str | None = None
    conversation_id: str | None = None
    voice_id: str | None = None
    backend_url: str | None = None


def _clean_str(value: object) -> str | None:
    """Return the value when it is a non-empty string, else None."""
    return value if isinstance(value, str) and value else None


def extract_meta_data(md: str | None) -> ParticipantMeta:
    """Extract session credentials from participant metadata JSON.

    backendUrl lets one shared agent serve many backends (staging
    previews): the /token endpoint embeds the URL of the API that minted
    the session.
    """
    if not md:
        return ParticipantMeta()
    try:
        obj = json.loads(md)
        return ParticipantMeta(
            agent_token=_clean_str(obj.get("agentToken")),
            conversation_id=_clean_str(obj.get("conversationId")),
            voice_id=_clean_str(obj.get("voiceId")),
            backend_url=_clean_str(obj.get("backendUrl")),
        )
    except (json.JSONDecodeError, AttributeError, TypeError) as e:
        log.debug(
            f"{LogTag.VOICE} Unparseable participant metadata", error=str(e), metadata=md[:200]
        )
        return ParticipantMeta()


def user_id_from_room(room_name: str) -> UserId:
    """Recover the user from a voice room name; ValueError for a room /token did not mint.

    Rooms are named voice_session_{user_id}_{uuid_hex} by the /token endpoint.
    """
    prefix = "voice_session_"
    user_id, _, suffix = room_name.removeprefix(prefix).rpartition("_")
    if not room_name.startswith(prefix) or not suffix:
        raise ValueError(f"Room {room_name!r} is not a voice_session_{{user_id}}_{{uuid}} room")
    return UserId(user_id)


def ms_since(t0: float) -> float:
    """Return milliseconds elapsed since t0 (from time.monotonic())."""
    return (time.monotonic() - t0) * 1000


__all__ = [
    "sanitize_for_tts",
    "has_open_tag_at_tail",
    "has_open_openui_fence_at_tail",
    "extract_meta_data",
    "ParticipantMeta",
    "ms_since",
    "user_id_from_room",
]
