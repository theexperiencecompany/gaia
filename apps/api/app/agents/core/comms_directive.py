"""Parse comms' narration output into a turn outcome: reply, silence, or reaction.

A turn not worth a full message is a single control tag instead of prose:

    <SILENCE>reason</SILENCE>  → deliver nothing (the reason is logged, not shown)
    <EMOJI>👍</EMOJI>          → deliver a one-emoji acknowledgment

A directive is a whole bubble, so prose that merely mentions a tag never
triggers one. A directive bubble is never shown to a user as text: beside
other bubbles it is dropped, and visible_comms_text_so_far applies the same
rule to a message still streaming.
"""

import re

from pydantic import TypeAdapter, ValidationError

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
from shared.py.analytics.catalog.properties import Emoji
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
_EMOJI = TypeAdapter(Emoji)


def _is_emoji(payload: str) -> bool:
    try:
        _EMOJI.validate_python(payload)
    except ValidationError:
        return False
    return True


def _bubble_directive(bubble: str) -> CommsDirective | None:
    """Return the directive a stripped bubble is, or None when it is text."""
    match = _TAG_RE.match(bubble) or _LEGACY_LINE_RE.match(bubble)
    if match is None:
        return None
    keyword, payload = match.group(1).upper(), match.group(2).strip()
    if keyword == SILENCE_TAG:
        return CommsDirective(CommsDirectiveKind.SILENCE, payload)
    # A reaction that is not one emoji (empty, or a word) is meaningless: the bubble stays text.
    return CommsDirective(CommsDirectiveKind.REACT, payload) if _is_emoji(payload) else None


def _could_become_directive(bubble: str) -> bool:
    """Whether a bubble still being written can end as a directive."""
    candidate = bubble.lstrip()
    if not any(
        opening.startswith(candidate[: len(opening)].upper()) for opening in _DIRECTIVE_OPENINGS
    ):
        return False
    # Past a newline only trailing whitespace may follow, so the bubble is decided.
    return "\n" not in candidate or _bubble_directive(candidate.strip()) is not None


def _text_bubble(bubble: str) -> str | None:
    """Return a finished bubble a user may see, or None for a blank or directive bubble."""
    return bubble if bubble.strip() and _bubble_directive(bubble.strip()) is None else None


def _joined(bubbles: list[str | None], separators: list[str]) -> str:
    """Join the bubbles left visible (None is hidden), each after the break written before it."""
    shown = [(index, bubble) for index, bubble in enumerate(bubbles) if bubble is not None]
    if not shown:
        return ""
    (_, first), *rest = shown
    return first + "".join(separators[index - 1] + bubble for index, bubble in rest)


def visible_comms_text(text: str) -> str:
    """Return what a user may see of a finished comms message: never a directive bubble."""
    *bubbles, last = MESSAGE_BREAK_SENTINEL_RE.split(text)
    bubbles.append(strip_partial_message_break(last))
    return _joined(
        [_text_bubble(bubble) for bubble in bubbles], MESSAGE_BREAK_SENTINEL_RE.findall(text)
    )


def visible_comms_text_so_far(text: str) -> str:
    """Return what a user may see of a comms message still streaming.

    The last bubble stays hidden while it could still become a directive, and
    so does a half-written break. Each result extends the one before, so a
    client can append the difference.
    """
    *bubbles, last = MESSAGE_BREAK_SENTINEL_RE.split(text)
    tail = _BREAK_TAIL_RE.search(last)
    shown = last[: tail.start()] if tail else last
    writing = shown if shown.strip() and not _could_become_directive(shown) else None
    return _joined(
        [*(_text_bubble(bubble) for bubble in bubbles), writing],
        MESSAGE_BREAK_SENTINEL_RE.findall(text),
    )


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
    return CommsDirective(CommsDirectiveKind.REPLY, visible_comms_text(text))
