"""Parse comms' narration output into a turn outcome: reply, silence, or reaction.

A turn not worth a full message is a single control tag instead of prose:

    <SILENCE>reason</SILENCE>  → deliver nothing (the reason is logged, not shown)
    <EMOJI>👍</EMOJI>          → deliver a one-emoji acknowledgment

Anything else is an ordinary reply. Parsing is strict — the whole turn, bubble
breaks aside, must be one tag — so prose that merely mentions one never triggers
it, and the safe failure is a stray tag shown as text, never a dropped message.
could_become_comms_directive asks the same of a turn still streaming.
"""

import re

from app.constants.comms import (
    EMOJI_TAG,
    LEGACY_REACT_KEYWORD,
    SILENCE_TAG,
    CommsDirectiveKind,
)
from app.models.agent_models import CommsDirective
from app.utils.message_breaks import MESSAGE_BREAK_SENTINEL_RE, split_message_bubbles

# One line, no DOTALL: a directive never spans lines, so a multi-line reply can
# never be mis-silenced. The closing tag must name the opening one.
_TAG_RE = re.compile(rf"^<({SILENCE_TAG}|{EMOJI_TAG})>([^\n]*?)</\1>$", re.IGNORECASE)
_LEGACY_LINE_RE = re.compile(rf"^({SILENCE_TAG}|{LEGACY_REACT_KEYWORD}):([^\n]*)$", re.IGNORECASE)
# How each form above begins: a turn that does not start like one is a reply.
_DIRECTIVE_OPENINGS = (
    f"<{SILENCE_TAG}>",
    f"<{EMOJI_TAG}>",
    f"{SILENCE_TAG}:",
    f"{LEGACY_REACT_KEYWORD}:",
)


def interpret_comms_output(text: str) -> CommsDirective:
    """Classify comms' final narration text as a reply, a silence, or a reaction."""
    bubbles = split_message_bubbles(text)
    if len(bubbles) == 1:
        match = _TAG_RE.match(bubbles[0]) or _LEGACY_LINE_RE.match(bubbles[0])
        if match:
            keyword, payload = match.group(1).upper(), match.group(2).strip()
            if keyword == SILENCE_TAG:
                return CommsDirective(CommsDirectiveKind.SILENCE, payload)
            # A reaction with no emoji is meaningless: fall back to REPLY.
            if payload:
                return CommsDirective(CommsDirectiveKind.REACT, payload)
    return CommsDirective(CommsDirectiveKind.REPLY, text)


def could_become_comms_directive(text: str) -> bool:
    """Whether a turn streamed so far can still end as a directive, so no client may see it yet."""
    candidate = text.lstrip()
    if not any(
        opening.startswith(candidate[: len(opening)].upper()) for opening in _DIRECTIVE_OPENINGS
    ):
        return False
    if "\n" not in candidate and not MESSAGE_BREAK_SENTINEL_RE.search(candidate):
        return True
    # Past a line or bubble break only trailing breaks may follow, so the turn is decided.
    return interpret_comms_output(candidate).kind is not CommsDirectiveKind.REPLY
