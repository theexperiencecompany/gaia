"""The date and time layouts a tool argument is written in, told apart by example.

A playbook's time placeholders render to ISO 8601. Tools do not all take ISO
8601: the reminder tool wants YYYY-MM-DD HH:MM:SS and says so only in
prose. The authoring run already sent each tool the value it accepted, so the
layout of that value is the specification, and a placeholder standing in for
it renders in the same layout at replay (TimeSlot.format).
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
#: forms the evaluator has always produced (isoformat writes the offset with a colon).
ISO_DATE_LAYOUT = "%Y-%m-%d"
ISO_DATETIME_LAYOUT = "%Y-%m-%dT%H:%M:%S%:z"

#: strptime reads +05:30 and +0530 with %z alike, but strftime writes %z without
#: the colon, so an offset written with one is kept as %:z.
_COLON_OFFSET = re.compile(r"[+-]\d{2}:\d{2}$")
#: A trailing literal Z (not the %Z directive) says the value is in UTC.
_UTC_DESIGNATOR = re.compile(r"(?<!%)Z$")


def detect_layout(value: object) -> str | None:
    """Return the strftime layout a recorded string argument is written in, or None.

    Text around the date is part of the layout: "Plan for September 5, 2026"
    is "Plan for %B %d, %Y", so a slot written from it renders the same
    words again. Seen live (D4): the bare-date hint had the model drop the
    words, and the replay made a todo titled by the date alone.
    """
    found = _dated(value)
    if found is None:
        return None
    prefix, layout, suffix = found
    return prefix.replace("%", "%%") + layout + suffix.replace("%", "%%")


def _dated(value: object) -> tuple[str, str, str] | None:
    """Return the text before the date, the date's own layout, and the text after it."""
    if not isinstance(value, str) or not value.strip():
        return None
    words = list(_WORD.finditer(value))
    for length in range(min(_MAX_DATE_WORDS, len(words)), 0, -1):
        for start in range(len(words) - length + 1):
            begin, end = words[start].start(), words[start + length - 1].end()
            layout = _layout_of(value[begin:end])
            if layout is not None:
                return value[:begin].lstrip(), layout, value[end:].rstrip()
    return None


def _iso_layout(placeholder: re.Match[str]) -> str:
    """Return the layout a bare time placeholder renders as."""
    date_only = placeholder.group("root") == "today" and placeholder.group("clock") is None
    return ISO_DATE_LAYOUT if date_only else ISO_DATETIME_LAYOUT


def _is_iso_layout(layout: str, placeholder: re.Match[str]) -> bool:
    """Whether layout is the placeholder's ISO rendering; a trailing Z is the +00:00 offset."""
    return _UTC_DESIGNATOR.sub("%:z", layout) == _iso_layout(placeholder)


def renders_inside(placeholder: re.Match[str], example: object) -> bool:
    """Whether a time placeholder written inside text renders like the date that text held.

    It renders as ISO 8601 there, so "Run at $today" holds for "Run at 2026-01-01";
    text with no date at all has no layout to break.
    """
    found = _dated(example)
    return found is None or _is_iso_layout(found[1], placeholder)


def renders_whole(placeholder: re.Match[str], example: object) -> bool:
    """Whether a whole time placeholder, rendered as ISO 8601, is in example's layout or it has none."""
    layout = detect_layout(example)
    return layout is None or _is_iso_layout(layout, placeholder)


def time_slot_layout(placeholder: re.Match[str], example: object) -> str | None:
    """Return the layout a whole time placeholder must carry to render like example.

    None when there is no layout to follow, or when the placeholder's own ISO
    rendering already is that layout.
    """
    layout = detect_layout(example)
    if layout is None:
        return None
    return None if layout == _iso_layout(placeholder) else layout


def slot_layout(value: object, named: str | None) -> str | None:
    """Return the layout a time slot over a recorded value renders in, or None when it has none.

    The author's layout when it is the recorded one or writes the value back
    (03/11/2026 reads as March or November); otherwise the recorded value's own.
    The builder and the validator both answer with this, so they cannot disagree.
    """
    detected = detect_layout(value)
    if named is not None and (
        named == detected or (isinstance(value, str) and _renders_back(value, named))
    ):
        return named
    return detected


def _renders_back(value: str, layout: str) -> bool:
    """Whether layout reads value and writes it again unchanged; %z reads a Z but writes +0000."""
    text = value.strip()
    try:
        moment = datetime.strptime(text, layout.replace("%:z", "%z"))
    except ValueError:
        return False
    return moment.strftime(layout) == text


def renders_in_utc(layout: str) -> bool:
    """Whether a layout writes UTC: one ending in a literal Z, as a recorded ...Z value was."""
    return _UTC_DESIGNATOR.search(layout) is not None


def _layout_of(text: str) -> str | None:
    for layout in KNOWN_TIME_LAYOUTS:
        try:
            datetime.strptime(text, layout)
        except ValueError:
            continue
        if layout.endswith("%z") and _COLON_OFFSET.search(text):
            return layout.removesuffix("%z") + "%:z"
        return layout
    return None


def render_iso(moment: datetime, *, date_only: bool) -> str:
    """Return the evaluator's default rendering: a date, or a datetime to the second."""
    return moment.date().isoformat() if date_only else moment.isoformat(timespec="seconds")
