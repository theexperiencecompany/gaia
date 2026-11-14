"""Bubble-break sentinel handling for outbound assistant text.

The model is told to emit <NEW_MESSAGE_BREAK> between bubbles, but it emits
near-misses constantly: <NEW_LINE_BREAK>, [NEW_MESSAGE_BREAK],
</NEW_MESSAGE_BREAK>, <NEW MESSAGE BREAK> — and, when a chunk boundary
lands mid-token, a truncated <NEW_MESSAGE_B. Every one of those used to ship
to the user as literal text. This module is the single place that knows what a
sentinel looks like; every outbound path splits through
:func:split_message_bubbles rather than matching the literal token itself.

It is the only splitter: the server sends every client a reply's bubbles, live and
settled, so no client parses the sentinel. A break inside a code block or a :::openui
block would bisect it, so it reads as a newline there instead.
"""

import re

from shared.py.conversation_wire import NEW_MESSAGE_BREAKER

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


_CODE_FENCE = "```"
_OPENUI_OPEN = ":::openui"
_OPENUI_CLOSE = "\n:::"


def _code_fence_ranges(text: str) -> list[tuple[int, int]]:
    """Return the [start, end) of every code block; an unclosed one runs to the end."""
    ranges: list[tuple[int, int]] = []
    start = text.find(_CODE_FENCE)
    while start != -1:
        close = text.find(_CODE_FENCE, start + len(_CODE_FENCE))
        if close == -1:
            ranges.append((start, len(text)))
            break
        # No break or fence overlaps a closing fence, so its end can't move one in or out.
        end = close + len(_CODE_FENCE)  # pragma: no mutate
        ranges.append((start, end))
        start = text.find(_CODE_FENCE, end)
    return ranges


def _openui_close(text: str, start: int) -> int:
    """Return where the block opened before start closes; a ::: that reopens openui nests."""
    while (close := text.find(_OPENUI_CLOSE, start)) != -1:
        after = close + len(_OPENUI_CLOSE)
        if not text.startswith("openui", after):
            return close
        start = after
    return -1


def _openui_ranges(text: str) -> list[tuple[int, int]]:
    """Return the [start, end) of every :::openui block; an unclosed one runs to the end."""
    ranges: list[tuple[int, int]] = []
    start = text.find(_OPENUI_OPEN)
    while start != -1:
        close = _openui_close(text, start + len(_OPENUI_OPEN))
        if close == -1:
            ranges.append((start, len(text)))
            break
        # No break or opener overlaps a close, so its end can't move one in or out.
        end = close + len(_OPENUI_CLOSE)  # pragma: no mutate
        ranges.append((start, end))
        start = text.find(_OPENUI_OPEN, end)
    return ranges


def split_message_bubbles(text: str) -> list[str]:
    """Split assistant text into the bubbles the model asked for.

    Splits on every sentinel spelling outside a code or :::openui block, drops a truncated
    trailing one, trims each bubble and discards the empties a doubled sentinel leaves.
    """
    if not text:
        return []
    fenced = [*_code_fence_ranges(text), *_openui_ranges(text)]
    pieces: list[str] = []
    piece = ""
    cursor = 0  # pragma: no mutate — text[None:] is text[0:]
    for found in MESSAGE_BREAK_SENTINEL_RE.finditer(text):
        piece += text[cursor : found.start()]
        cursor = found.end()
        # A block opens with its marker, so no break starts exactly where one does.
        if any(start <= found.start() < end for start, end in fenced):  # pragma: no mutate
            piece += "\n"
        else:
            pieces.append(piece)
            piece = ""
    pieces.append(piece + text[cursor:])
    bubbles = (strip_partial_message_break(part).strip() for part in pieces)
    return [bubble for bubble in bubbles if bubble]


def normalize_message_breaks(text: str) -> str:
    """Rewrite text as its bubbles joined by exactly one canonical sentinel."""
    return NEW_MESSAGE_BREAKER.join(split_message_bubbles(text))
