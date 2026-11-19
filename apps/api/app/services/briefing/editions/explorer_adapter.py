"""BriefingPayload -> the vendored explorer templates' ed shape.

The templates in editions/explorer/js/ expect four buckets (today, overnight for
what finished, running for what GAIA is still doing, decisions) plus a stats tuple; this module maps our looser payload by meaning, never by position.
Every item lives in exactly one bucket. Stats come from the payload's tallies, with
unknown or zero figures as None so the template renders nothing for them.

ed values are passed through unescaped: every vendored template HTML-escapes its own
text, so pre-escaping here would double-encode entities.
"""

from datetime import date, datetime
import re
from typing import NamedTuple, TypedDict

from app.constants.briefing import POSTAL_FAMILY, WEEKLY_FAMILY
from app.models.briefing_models import (
    BriefingEvent,
    BriefingItem,
    BriefingItemKind,
    BriefingPayload,
    BriefingSection,
    BriefingTallies,
    BriefingWeek,
)
from app.services.briefing.editions.stamps import Stamp, stamp_for

_WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
_MONTHS = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]

# A leading "1:30 PM — " clock prefix on item text, if the payload ever
# carries one (today's real briefing prompt never does — see module note
# below — but a future payload variant might).
_ITEM_TIME_PREFIX_RE = re.compile(r"^(\d{1,2}:\d{2}\s*[AaPp][Mm])\s*[-–—]\s*(.+)$")
_GENERATED_TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})\s*([AaPp][Mm])$")

# GAIA-side state of an overnight row, as the short caps tag the templates set
# beside it (the contract's sample data used "REVIEW", "SHIP", "DONE").
_OVERNIGHT_TAGS: dict[BriefingItemKind, str] = {"gaia": "IN PROGRESS", "lookback": "DONE"}
# Work GAIA is still doing: never filed under a "done while you slept" heading.
_RUNNING_KINDS: frozenset[BriefingItemKind] = frozenset({"gaia"})
# What waits on the reader: their own asks and work that failed (offered as a retry).
_DECISION_KINDS: frozenset[BriefingItemKind] = frozenset({"you", "failed"})
_RETRY_VERB = "Retry"

_IMPERATIVE_VERBS = {
    "approve",
    "decide",
    "confirm",
    "choose",
    "sign",
    "reject",
    "accept",
    "send",
    "pick",
    "cancel",
    "review",
    "authorize",
    "renew",
    "respond",
}


class ExplorerTodayItem(TypedDict):
    """One content.today row, keyed exactly as the vendored JS reads it."""

    time: str | None
    t24: str | None
    label: str
    note: str | None
    tag: str


class ExplorerOvernightItem(TypedDict):
    t24: str | None
    label: str
    note: str | None
    tag: str


class ExplorerDecisionItem(TypedDict):
    verb: str
    label: str
    note: str | None


class ExplorerStats(TypedDict):
    """Each figure is None when unknown or zero; the templates guard on it."""

    done: int | None
    you: int | None
    gaia: int | None
    mail: int | None
    focus: str | None


class ExplorerContent(TypedDict):
    today: list[ExplorerTodayItem]
    overnight: list[ExplorerOvernightItem]
    running: list[ExplorerOvernightItem]
    decisions: list[ExplorerDecisionItem]
    #: Todos waiting on the reader (a grouped ask counts each); None when nothing waits.
    awaiting: int | None
    stats: ExplorerStats | None


class ExplorerArt(TypedDict):
    """The painting the edition hangs (editions/artworks.py), its image a data URI."""

    src: str
    title: str
    artist: str
    year: str
    medium: str


class ExplorerAheadItem(TypedDict):
    day: str
    label: str


class ExplorerWeekDay(TypedDict):
    you: int
    gaia: int


class ExplorerWeek(TypedDict):
    """ed.week: the real week the weekly family draws."""

    days: list[ExplorerWeekDay]
    shipped: list[str]
    handled: list[str]
    ahead: list[ExplorerAheadItem]


class ExplorerRecipient(TypedDict):
    """Who the edition is addressed to: the full name and the first name."""

    name: str
    first: str


class ExplorerEdition(TypedDict):
    """The exact ed shape the templates render against.

    Field names match the vendored JS verbatim (dateLong, editionNo, monthShort).
    """

    n: int
    weekday: str
    day: int
    month: str
    monthShort: str
    year: int
    dateLong: str
    editionNo: int
    time: str
    time24: str
    #: The brief's headline: every family's one display line.
    deck: str
    #: None when the payload carries no name; the templates then address "you".
    recipient: ExplorerRecipient | None
    content: ExplorerContent
    week: ExplorerWeek | None
    stamp: Stamp | None
    art: ExplorerArt
    assets: dict[str, str]


def build_ed(
    payload: BriefingPayload,
    *,
    edition_no: int,
    generated_local: str,
    assets: dict[str, str],
    art: ExplorerArt,
    family: str,
) -> ExplorerEdition:
    """Build the vendored templates' ed object from a briefing payload.

    generated_local (e.g. "6:02 AM"); empty uses the payload's generated_at. assets maps
    asset key to image URL. family decides whether ed carries the week or a stamp.
    """
    date_parts = _date_parts(payload.date)
    buckets = _build_buckets(payload.sections, payload.calendar)
    generated = generated_local or payload.generated_at or ""

    return {
        "n": edition_no,
        "weekday": date_parts[0],
        "day": date_parts[1],
        "month": date_parts[2],
        "monthShort": date_parts[3],
        "year": date_parts[4],
        "dateLong": date_parts[5],
        "editionNo": edition_no,
        "time": generated,
        "time24": _time24(generated),
        "deck": payload.headline,
        "recipient": _build_recipient(payload.recipient_name),
        "content": {
            "today": buckets.today,
            "overnight": buckets.overnight,
            "running": buckets.running,
            "decisions": buckets.decisions,
            "awaiting": _awaiting(payload.sections),
            "stats": _build_stats(payload.tallies),
        },
        "week": _build_week(payload.week) if family == WEEKLY_FAMILY else None,
        "stamp": _build_stamp(payload.stamp_city) if family == POSTAL_FAMILY else None,
        "art": art,
        "assets": assets,
    }


def _date_parts(iso_date: str) -> tuple[str, int, str, str, int, str]:
    """Split an ISO date into (weekday, day, month, monthShort, year, dateLong).

    An unparseable or empty date degrades to blanks rather than raising; dateLong falls
    back to the raw string so the date is never silently dropped.
    """
    try:
        parsed = date.fromisoformat(iso_date)
    except ValueError:
        return "", 0, "", "", 0, iso_date
    weekday = _WEEKDAYS[parsed.weekday()]
    month = _MONTHS[parsed.month - 1]
    return (
        weekday,
        parsed.day,
        month,
        month[:3],
        parsed.year,
        f"{weekday}, {parsed.day} {month} {parsed.year}",
    )


def _time24(generated_local: str) -> str:
    """Convert 12h "6:02 AM" to 24h "06:02".

    Returns the input unchanged if it doesn't match that shape (empty string, or a format
    that changes later).
    """
    match = _GENERATED_TIME_RE.match(generated_local.strip())
    if not match:
        return generated_local
    hour, minute, ampm = int(match.group(1)), match.group(2), match.group(3).upper()
    if ampm == "AM":
        hour = 0 if hour == 12 else hour
    elif hour != 12:
        hour += 12
    return f"{hour:02d}:{minute}"


def _split_time_prefix(text: str) -> tuple[str | None, str]:
    """Split item text into (t24, label).

    t24 is None when the text carries no leading clock prefix (the common case for our
    payload's item text).
    """
    match = _ITEM_TIME_PREFIX_RE.match(text.strip())
    if not match:
        return None, text
    return _time24(match.group(1)), match.group(2)


def _decision_verb(text: str) -> tuple[str, str]:
    """Split text into a verb and a label.

    A leading imperative word ("Approve", "Decide", ...) becomes the verb and is stripped
    from the label; otherwise the verb defaults to "Review" and the label is the text
    verbatim.
    """
    words = text.strip().split(None, 1)
    if not words:
        return "Review", text
    first = words[0].strip(":,.-")
    if first.lower() in _IMPERATIVE_VERBS:
        rest = words[1] if len(words) > 1 else ""
        return first.capitalize(), rest.lstrip(": -–—")
    return "Review", text


def _clock12(t24: str) -> str:
    """24h "13:05" -> "1:05 PM"."""
    return datetime.strptime(t24, "%H:%M").strftime("%-I:%M %p")


def _event_row(event: BriefingEvent) -> ExplorerTodayItem:
    return {
        "time": _clock12(event.start) if event.start else None,
        "t24": event.start or None,
        "label": event.title,
        "note": event.location or None,
        "tag": "",
    }


def _overnight_row(item: BriefingItem) -> ExplorerOvernightItem:
    t24, label = _split_time_prefix(item.text)
    return {
        "t24": t24,
        "label": label,
        "note": None,
        "tag": _OVERNIGHT_TAGS.get(item.kind, ""),
    }


def _decision_row(item: BriefingItem) -> ExplorerDecisionItem:
    if item.kind == "failed":
        return {"verb": _RETRY_VERB, "label": item.text, "note": None}
    verb, label = _decision_verb(item.text)
    return {"verb": verb, "label": label, "note": None}


class _Buckets(NamedTuple):
    today: list[ExplorerTodayItem]
    overnight: list[ExplorerOvernightItem]
    running: list[ExplorerOvernightItem]
    decisions: list[ExplorerDecisionItem]


def _build_buckets(sections: list[BriefingSection], calendar: list[BriefingEvent]) -> _Buckets:
    """Map items by meaning (see the module docstring); an empty bucket stays empty."""
    items = [item for section in sections for item in section.items]
    finished = [i for i in items if i.kind not in _DECISION_KINDS | _RUNNING_KINDS]
    return _Buckets(
        today=[_event_row(e) for e in calendar],
        overnight=[_overnight_row(i) for i in finished],
        running=[_overnight_row(i) for i in items if i.kind in _RUNNING_KINDS],
        decisions=[_decision_row(i) for i in items if i.kind in _DECISION_KINDS],
    )


def _positive(value: int) -> int | None:
    return value if value > 0 else None


def _awaiting(sections: list[BriefingSection]) -> int | None:
    return _positive(
        sum(item.count for s in sections for item in s.items if item.kind in _DECISION_KINDS)
    )


def _build_stats(tallies: BriefingTallies | None) -> ExplorerStats | None:
    """Build the figures from the payload's tallies; None when no figure is known.

    Mail handled and focus time have no source yet, so they are always None and their
    slots render nothing. With no figure at all, a family drops its stats block.
    """
    you = tallies.done_by_you if tallies else 0
    gaia = tallies.done_by_gaia if tallies else 0
    if you + gaia <= 0:
        return None
    return {
        "done": _positive(you + gaia),
        "you": _positive(you),
        "gaia": _positive(gaia),
        "mail": None,
        "focus": None,
    }


def _build_recipient(name: str | None) -> ExplorerRecipient | None:
    full = " ".join((name or "").split())
    return {"name": full, "first": full.partition(" ")[0]} if full else None


def _build_week(week: BriefingWeek | None) -> ExplorerWeek | None:
    if not week:
        return None
    return {
        "days": [{"you": d.you, "gaia": d.gaia} for d in week.days],
        "shipped": list(week.shipped),
        "handled": list(week.handled),
        "ahead": [
            {"day": date.fromisoformat(e.date).strftime("%a"), "label": e.title} for e in week.ahead
        ],
    }


def _build_stamp(slug: str | None) -> Stamp | None:
    """Return the drawn city's stamp skin.

    Legacy payloads without one keep the template's own city axis.
    """
    return stamp_for(slug) if slug else None
