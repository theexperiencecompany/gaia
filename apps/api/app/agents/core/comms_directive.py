"""Parse comms' narration output into a turn outcome: reply, silence, or reaction.

A turn not worth a full message is a single control tag instead of prose:

    <SILENCE>reason</SILENCE>  → deliver nothing (the reason is logged, not shown)
    <EMOJI>👍</EMOJI>          → deliver a one-emoji acknowledgment

Only a turn made of directives alone becomes one, so prose never triggers a
directive. A directive tag is never shown to a user as text: written beside a
reply, as its own bubble or inside one, it is dropped and the reply goes out,
and visible_comms_text_so_far applies the same rule to a message still streaming.
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

# A tag name with any spaces gpt-6-luna puts in it: "< SILENCE >", even "< S I L E N C E >".
_TAG_NAME = r"[A-Za-z](?:[ \t]*[A-Za-z])*"
# One line, no DOTALL: a directive never spans lines, so a multi-line reply can
# never be mis-silenced. The closing tag must name the opening one.
_TAG_RE = re.compile(rf"^<\s*({_TAG_NAME})\s*>([^\n]*?)<\s*/\s*({_TAG_NAME})\s*>$")
# A whole tag inside a bubble, with the spaces after it; the newline after it is
# group 1, so a tag alone on its line takes the line with it.
_INLINE_TAG_RE = re.compile(
    rf"<[ \t]*{_TAG_NAME}[ \t]*>[^\n<]*<[ \t]*/[ \t]*{_TAG_NAME}[ \t]*>[ \t]*(\n?)"
)
# A silence whose closing never came: its reason runs to the end of the line,
# and is no more the user's to read than a closed one's.
_SPACED_SILENCE = r"[ \t]*".join(SILENCE_TAG)
_UNCLOSED_SILENCE_RE = re.compile(rf"<[ \t]*{_SPACED_SILENCE}[ \t]*>([^\n]*)(\n?)", re.IGNORECASE)
# A tag still being written at the end of a bubble: its opening, or an opening and
# a payload whose closing has not arrived. Only a directive name is held back.
_OPENING_TAIL_RE = re.compile(r"<[ \t]*([A-Za-z \t]*)\Z")
_UNCLOSED_TAG_TAIL_RE = re.compile(rf"<[ \t]*({_TAG_NAME})[ \t]*>[^\n]*\Z")
_DIRECTIVE_TAGS = frozenset({SILENCE_TAG, EMOJI_TAG})
_SPACES_RE = re.compile(r"[ \t]")
# The opening of a tag still being written, its spaces dropped.
_SPACED_OPENING_RE = re.compile(r"^<[ \t]*([A-Za-z \t]*)")
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


def _compact_name(name: str) -> str:
    return _SPACES_RE.sub("", name).upper()


def _bubble_directive(bubble: str) -> CommsDirective | None:
    """Return the directive a stripped bubble is, or None when it is text."""
    tag = _TAG_RE.match(bubble)
    if tag is not None:
        keyword, closing = (_compact_name(tag.group(i)) for i in (1, 3))
        if keyword != closing or keyword not in _DIRECTIVE_TAGS:
            return None
        payload = tag.group(2).strip()
    else:
        legacy = _LEGACY_LINE_RE.match(bubble)
        if legacy is None:
            return None
        keyword, payload = legacy.group(1).upper(), legacy.group(2).strip()
    if keyword == SILENCE_TAG:
        return CommsDirective(CommsDirectiveKind.SILENCE, payload)
    # A reaction that is not one emoji (empty, or a word) is meaningless: the bubble stays text.
    return CommsDirective(CommsDirectiveKind.REACT, payload) if _is_emoji(payload) else None


def _could_become_directive(bubble: str) -> bool:
    """Whether a bubble still being written can end as a directive."""
    candidate = bubble.lstrip()
    compact = _SPACED_OPENING_RE.sub(lambda m: "<" + _SPACES_RE.sub("", m.group(1)), candidate)
    if not any(
        opening.startswith(compact[: len(opening)].upper()) for opening in _DIRECTIVE_OPENINGS
    ):
        return False
    # Past a newline only trailing whitespace may follow, so the bubble is decided.
    return "\n" not in candidate or _bubble_directive(candidate.strip()) is not None


def _split_directives(bubble: str) -> tuple[str, list[CommsDirective]]:
    """Return a bubble's text with every directive in it removed, and those directives."""
    whole = _bubble_directive(bubble.strip())
    if whole is not None:
        return "", [whole]
    found: list[CommsDirective] = []

    def removed(tag: re.Match[str], line_end: str) -> str:
        text = tag.string
        alone_on_its_line = tag.start() == 0 or text[tag.start() - 1] == "\n"
        return "" if alone_on_its_line else line_end

    def drop_closed(tag: re.Match[str]) -> str:
        directive = _bubble_directive(tag.group(0).strip())
        if directive is None:
            return tag.group(0)
        found.append(directive)
        return removed(tag, tag.group(1))

    def drop_unclosed(tag: re.Match[str]) -> str:
        found.append(CommsDirective(CommsDirectiveKind.SILENCE, tag.group(1).strip()))
        return removed(tag, tag.group(2))

    text = _INLINE_TAG_RE.sub(drop_closed, bubble)
    return _UNCLOSED_SILENCE_RE.sub(drop_unclosed, text), found


def _unfinished_tag_start(text: str) -> int | None:
    """Where a directive tag still being written begins in a streaming bubble, if one is."""
    for index in (i for i, char in enumerate(text) if char == "<"):
        tail = text[index:]
        if _INLINE_TAG_RE.match(tail):
            continue
        opening = _OPENING_TAIL_RE.match(tail)
        if opening is not None and any(
            name.startswith(_compact_name(opening.group(1))) for name in _DIRECTIVE_TAGS
        ):
            return index
        unclosed = _UNCLOSED_TAG_TAIL_RE.match(tail)
        if unclosed is not None and _compact_name(unclosed.group(1)) in _DIRECTIVE_TAGS:
            return index
    return None


def _text_bubble(bubble: str) -> str | None:
    """Return what a user may see of a bubble, or None when no text is left of it."""
    text, _ = _split_directives(bubble)
    return text if text.strip() else None


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
    so do a directive tag being written inside it and a half-written break.
    Each result extends the one before, so a client can append the difference.
    """
    *bubbles, last = MESSAGE_BREAK_SENTINEL_RE.split(text)
    tail = _BREAK_TAIL_RE.search(last)
    shown = last[: tail.start()] if tail else last
    writing = None
    if shown.strip() and not _could_become_directive(shown):
        writing = _text_bubble(shown[: _unfinished_tag_start(shown)])
    return _joined(
        [*(_text_bubble(bubble) for bubble in bubbles), writing],
        MESSAGE_BREAK_SENTINEL_RE.findall(text),
    )


def interpret_comms_output(text: str) -> CommsDirective:
    """Classify comms' final narration text as a reply, a silence, or a reaction.

    Only directives make the first directive the outcome; beside text, as a
    bubble or inside one, they are dropped from the reply, and logged as the
    model's confusion. A reply is what a user may see of it, so bare breaks
    reply with nothing.
    """
    directives: list[CommsDirective] = []
    has_text = False
    for bubble in split_message_bubbles(text):
        bubble_text, found = _split_directives(bubble)
        directives.extend(found)
        has_text = has_text or bool(bubble_text.strip())
    if not directives:
        return CommsDirective(CommsDirectiveKind.REPLY, visible_comms_text(text))
    if not has_text:
        return directives[0]
    log.warning(
        f"{LogTag.AGENT} comms wrote a directive beside its reply; the directive was dropped",
        dropped_directives=[
            {"kind": directive.kind.value, "payload": directive.payload} for directive in directives
        ],
    )
    return CommsDirective(CommsDirectiveKind.REPLY, visible_comms_text(text))
