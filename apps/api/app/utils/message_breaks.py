"""Bubble-break sentinel handling for outbound assistant text.

The model is told to emit <NEW_MESSAGE_BREAK> between bubbles, but it emits
near-misses constantly: <NEW_LINE_BREAK>, [NEW_MESSAGE_BREAK],
</NEW_MESSAGE_BREAK>, <NEW MESSAGE BREAK> — and, when a chunk boundary
lands mid-token, a truncated <NEW_MESSAGE_B. Every one of those used to ship
to the user as literal text. This module is the single place that knows what a
sentinel looks like; every outbound path splits through
:func:split_message_bubbles rather than matching the literal token itself.

The TypeScript half is libs/shared/ts/src/utils/messageBreakUtils.ts — the
two must accept the same spellings.
"""

import re

from app.constants.general import NEW_MESSAGE_BREAKER

#: Words of each accepted spelling, in order. Separators between them are
#: matched leniently (``_``, ``-``, space, or nothing at all).
_SENTINEL_WORD_SEQUENCES: tuple[tuple[str, ...], ...] = (
    ("NEW", "MESSAGE", "BREAK"),
    ("NEW", "LINE", "BREAK"),
)

_SEPARATOR = r"[\s_-]*"
_OPEN = r"[<\[]\s*/?\s*"
_CLOSE = r"\s*/?\s*[>\]]"

MESSAGE_BREAK_SENTINEL_RE = re.compile(
    _OPEN
    + "(?:"
    + "|".join(_SEPARATOR.join(words) for words in _SENTINEL_WORD_SEQUENCES)
    + ")"
    + _CLOSE,
    re.IGNORECASE,
)


def _word_prefixes(word: str) -> str:
    """Regex matching any non-empty prefix of word (N, NE, NEW)."""
    pattern = ""
    for char in reversed(word):
        pattern = f"{char}(?:{pattern})?" if pattern else char
    return pattern


def _partial_sequence(words: tuple[str, ...]) -> str:
    """Regex matching any non-empty prefix of one whole spelling.

    Built inside-out so NEW, NEW_MESS and NEW_MESSAGE_BRE all match
    while a complete, closed sentinel does not (there is no closing bracket).
    """
    pattern = ""
    for word in reversed(words[1:]):
        inner = f"(?:{pattern})?" if pattern else ""
        pattern = f"{_SEPARATOR}(?:{_word_prefixes(word)}{inner})?"
    return f"{_word_prefixes(words[0])}(?:{pattern})?"


#: A sentinel truncated by a chunk boundary, anchored to the end of the text.
#: At least one character is required: a bare trailing ``<`` is ordinary text
#: far more often than a half-received sentinel.
PARTIAL_MESSAGE_BREAK_RE = re.compile(
    _OPEN + "(?:" + "|".join(_partial_sequence(w) for w in _SENTINEL_WORD_SEQUENCES) + ")$",
    re.IGNORECASE,
)


#: A streamed tail that may still turn into a bubble break, down to a lone ``<``.
STREAMING_BREAK_TAIL_RE = re.compile(
    rf"{PARTIAL_MESSAGE_BREAK_RE.pattern}|[<\[]\s*/?\s*$", re.IGNORECASE
)

_EDGE_BREAKS_RE = re.compile(
    rf"^(?:\s*{MESSAGE_BREAK_SENTINEL_RE.pattern})+\s*|(?:\s*{MESSAGE_BREAK_SENTINEL_RE.pattern})+\s*$",
    re.IGNORECASE,
)


def is_only_message_breaks(text: str) -> bool:
    """Return whether text, possibly still streaming, holds nothing yet but breaks and whitespace."""
    return not STREAMING_BREAK_TAIL_RE.sub("", MESSAGE_BREAK_SENTINEL_RE.sub("", text)).strip()


def count_message_breaks(text: str) -> int:
    """Return how many complete sentinels text contains."""
    return len(MESSAGE_BREAK_SENTINEL_RE.findall(text))


def strip_edge_message_breaks(text: str) -> str:
    """Drop the run of sentinels a text opens or closes with, keeping the ones between bubbles."""
    return _EDGE_BREAKS_RE.sub("", text)


def strip_partial_message_break(text: str) -> str:
    """Drop a sentinel that a chunk boundary cut in half at the end of text."""
    return PARTIAL_MESSAGE_BREAK_RE.sub("", text)


def append_message_bubble(message: str, bubble: str) -> str:
    """Append one finished bubble, sentinel-separated from what came before.

    Two assistant messages in one turn are two bubbles. Concatenating their text
    directly is what turned "fixing it." and "fixing it now" into the single
    sentence "fixing it.fixing it now" in a persisted reply.
    """
    return f"{message}{NEW_MESSAGE_BREAKER}{bubble}" if message else bubble


def split_message_bubbles(text: str) -> list[str]:
    """Split assistant text into the bubbles the model asked for.

    Splits on every sentinel spelling, drops a truncated trailing one, trims each
    bubble and discards the empties a doubled sentinel leaves behind.
    """
    if not text:
        return []
    bubbles = (
        strip_partial_message_break(part).strip() for part in MESSAGE_BREAK_SENTINEL_RE.split(text)
    )
    return [bubble for bubble in bubbles if bubble]


def normalize_message_breaks(text: str) -> str:
    """Rewrite text as its bubbles joined by exactly one canonical sentinel."""
    return NEW_MESSAGE_BREAKER.join(split_message_bubbles(text))
