"""The date and time layouts a tool argument is written in, told apart by example.

A playbook's time placeholders render to ISO 8601. Tools do not all take ISO
8601: the reminder tool wants ``YYYY-MM-DD HH:MM:SS`` and says so only in
prose. The authoring run already sent each tool the value it accepted, so the
layout of that value is the specification, and a placeholder standing in for
it renders in the same layout at replay (``TimeSlot.format``).
"""

from __future__ import annotations

from datetime import datetime

#: Layouts recognised in a recorded argument, most specific first. A value is
#: matched against these with ``strptime``; the first that parses is its layout.
KNOWN_TIME_LAYOUTS: tuple[str, ...] = (
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%dT%H:%M:%S.%f%z",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S%z",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%m/%d/%Y",
)

#: What a time placeholder renders as when no layout is recorded: the two ISO
#: forms the evaluator has always produced.
ISO_DATE_LAYOUT = "%Y-%m-%d"
ISO_DATETIME_LAYOUT = "%Y-%m-%dT%H:%M:%S%z"


def detect_layout(value: object) -> str | None:
    """The layout a recorded string argument is written in, or ``None``."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
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
