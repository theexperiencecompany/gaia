"""The date and time layouts a tool argument is written in, told apart by example.

A playbook's time placeholders render to ISO 8601. Tools do not all take ISO
8601: the reminder tool wants ``YYYY-MM-DD HH:MM:SS`` and says so only in
prose. The authoring run already sent each tool the value it accepted, so the
layout of that value is the specification, and a placeholder standing in for
it renders in the same layout at replay (``TimeSlot.format``).
"""

from __future__ import annotations

from datetime import datetime
import re

#: Layouts recognised in a recorded argument, most specific first. A value is
#: matched against these with ``strptime``; the first that parses is its layout.
KNOWN_TIME_LAYOUTS: tuple[str, ...] = (
    # The literal-Z form first: ``%z`` also accepts "Z", but renders "+0000",
    # and a tool that was sent "Z" is rendered "Z" again.
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%dT%H:%M:%S.%f%z",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S%z",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%m/%d/%Y",
    "%B %d, %Y",
    "%d %B %Y",
)

#: A recorded value is prose around a date at most this many words long.
_MAX_DATE_WORDS = 4
_WORD = re.compile(r"\S+")

#: What a time placeholder renders as when no layout is recorded: the two ISO
#: forms the evaluator has always produced.
ISO_DATE_LAYOUT = "%Y-%m-%d"
ISO_DATETIME_LAYOUT = "%Y-%m-%dT%H:%M:%S%z"


def detect_layout(value: object) -> str | None:
    """The strftime layout a recorded string argument is written in, or ``None``.

    Text around the date is part of the layout: ``"Plan for September 5, 2026"``
    is ``"Plan for %B %d, %Y"``, so a slot written from it renders the same
    words again. Seen live (D4): the bare-date hint had the model drop the
    words, and the replay made a todo titled by the date alone.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    words = list(_WORD.finditer(value))
    for length in range(min(_MAX_DATE_WORDS, len(words)), 0, -1):
        for start in range(len(words) - length + 1):
            begin, end = words[start].start(), words[start + length - 1].end()
            layout = _layout_of(value[begin:end])
            if layout is not None:
                prefix, suffix = value[:begin].lstrip(), value[end:].rstrip()
                return prefix.replace("%", "%%") + layout + suffix.replace("%", "%%")
    return None


def _layout_of(text: str) -> str | None:
    for layout in KNOWN_TIME_LAYOUTS:
        try:
            datetime.strptime(text, layout)
        except ValueError:
            continue
        return layout
    return None


def render_iso(moment: datetime, *, date_only: bool) -> str:
    """The evaluator's default rendering: a date, or a datetime to the second."""
    return moment.date().isoformat() if date_only else moment.isoformat(timespec="seconds")
