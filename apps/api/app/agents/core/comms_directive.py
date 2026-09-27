"""Parse comms' narration output into a turn outcome: reply, silence, or reaction.

A turn not worth a full message is a single control tag instead of prose:

    <SILENCE>reason</SILENCE>  → deliver nothing (the reason is logged, not shown)
    <EMOJI>👍</EMOJI>          → deliver a one-emoji acknowledgment

A directive is a whole bubble, so prose that merely mentions a tag never
triggers one. A directive bubble is never shown to a user as text: beside
other bubbles it is dropped, and visible_comms_text applies the same rule to
a message still streaming.
"""

import re

from app.constants.comms import (
    EMOJI_TAG,
    LEGACY_REACT_KEYWORD,
    SILENCE_TAG,
    CommsDirectiveKind,
)
from app.constants.log_tags import LogTag
from app.models.agent_models import CommsDirective
from app.utils.message_breaks import (
    MESSAGE_BREAK_SENTINEL_RE,
    PARTIAL_MESSAGE_BREAK_RE,
    split_message_bubbles,
    strip_partial_message_break,
)
from shared.py.wide_events import log

# One line, no DOTALL: a directive never spans lines, so a multi-line reply can
# never be mis-silenced. The closing tag must name the opening one.
_TAG_RE = re.compile(rf"^<({SILENCE_TAG}|{EMOJI_TAG})>([^\n]*?)</\1>$", re.IGNORECASE)
_LEGACY_LINE_RE = re.compile(rf"^({SILENCE_TAG}|{LEGACY_REACT_KEYWORD}):([^\n]*)$", re.IGNORECASE)
# How each form above begins: a bubble that does not start like one is text.
_DIRECTIVE_OPENINGS = (
    f"<{SILENCE_TAG}>",
    f"<{EMOJI_TAG}>",
    f"{SILENCE_TAG}:",
    f"{LEGACY_REACT_KEYWORD}:",
)
# A streamed tail that may still turn into a bubble break, down to a lone "<".
_BREAK_TAIL_RE = re.compile(rf"{PARTIAL_MESSAGE_BREAK_RE.pattern}|[<\[]\s*/?\s*$", re.IGNORECASE)


def _bubble_directive(bubble: str) -> CommsDirective | None:
    """Return the directive a stripped bubble is, or None when it is text."""
    match = _TAG_RE.match(bubble) or _LEGACY_LINE_RE.match(bubble)
    if match is None:
        return None
    keyword, payload = match.group(1).upper(), match.group(2).strip()
    if keyword == SILENCE_TAG:
        return CommsDirective(CommsDirectiveKind.SILENCE, payload)
    # A reaction with no emoji is meaningless: the bubble stays text.
    return CommsDirective(CommsDirectiveKind.REACT, payload) if payload else None


def _could_become_directive(bubble: str) -> bool:
    """Whether a bubble still being written can end as a directive."""
    candidate = bubble.lstrip()
    if not any(
        opening.startswith(candidate[: len(opening)].upper()) for opening in _DIRECTIVE_OPENINGS
    ):
        return False
    # Past a newline only trailing whitespace may follow, so the bubble is decided.
    return "\n" not in candidate or _bubble_directive(candidate.strip()) is not None


def _bubbles_with_breaks(text: str) -> list[tuple[str, str]]:
    """Split text into (the break before it, bubble) pairs, raw; the first break is ""."""
    pieces: list[tuple[str, str]] = []
    separator, start = "", 0
    for match in MESSAGE_BREAK_SENTINEL_RE.finditer(text):
        pieces.append((separator, text[start : match.start()]))
        separator, start = match.group(0), match.end()
    pieces.append((separator, text[start:]))
    return pieces


def visible_comms_text(text: str, *, complete: bool) -> str:
    """Return what a user may see of one comms message: never a directive bubble.

    While the message streams (complete=False) the last bubble is withheld as
    long as it could still become a directive, and so is a half-written break.
    Each result extends the one before, so a client can append the difference.
    """
    *closed, (last_separator, last) = _bubbles_with_breaks(text)
    if complete:
        closed.append((last_separator, strip_partial_message_break(last)))
    visible = ""
    for separator, bubble in closed:
        if bubble.strip() and _bubble_directive(bubble.strip()) is None:
            visible += (separator if visible else "") + bubble
    if not complete:
        tail = _BREAK_TAIL_RE.search(last)
        shown = last[: tail.start()] if tail else last
        if shown.strip() and not _could_become_directive(shown):
            visible += (last_separator if visible else "") + shown
    return visible


def interpret_comms_output(text: str) -> CommsDirective:
    """Classify comms' final narration text as a reply, a silence, or a reaction.

    Only directive bubbles make the first directive the outcome; beside text
    they are dropped from the reply, and logged as the model's confusion.
    """
    directives: list[CommsDirective] = []
    has_text = False
    for bubble in split_message_bubbles(text):
        directive = _bubble_directive(bubble)
        if directive is None:
            has_text = True
        else:
            directives.append(directive)
    if not directives:
        return CommsDirective(CommsDirectiveKind.REPLY, text)
    if not has_text:
        return directives[0]
    log.warning(
        f"{LogTag.AGENT} comms wrote a directive beside its reply; the directive was dropped",
        dropped_directives=[
            {"kind": directive.kind.value, "payload": directive.payload} for directive in directives
        ],
    )
    return CommsDirective(CommsDirectiveKind.REPLY, visible_comms_text(text, complete=True))
