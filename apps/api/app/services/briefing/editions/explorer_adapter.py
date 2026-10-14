"""BriefingPayload -> the vendored explorer templates' ed shape.

The templates in editions/explorer/js/ expect three buckets (today/overnight/decisions)
plus a stats tuple; this module maps our looser payload by meaning, never by position.
Every item lives in exactly one bucket. Stats come from the payload's tallies, with
unknown or zero figures as None so the template renders nothing for them.

ed values are passed through unescaped: every vendored template HTML-escapes its own
text, so pre-escaping here would double-encode entities.
"""

from datetime import date, datetime
import re
from typing import TypedDict

from app.constants.briefing import POSTAL_FAMILY, WEEKLY_FAMILY
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
_OVERNIGHT_TAGS: dict[str, str] = {"gaia": "IN PROGRESS", "lookback": "DONE"}
_DECISION_KINDS = frozenset({"you", "needs_you", "proposal"})
_OVERNIGHT_KINDS = frozenset({"gaia", "lookback"})
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

# Families that read ``ed.headline`` in their own title slot (see
# explorer/README.md, "Brief fields the fixture lacked"); every other family
# has one text slot, the deck, and it carries the headline.
_TITLE_SLOT_FAMILIES = frozenset({"memo", "postal", "broadsheet"})

_PLACEHOLDER_TODAY: "ExplorerTodayItem" = {
    "time": None,
    "t24": None,
    "label": "Nothing on the calendar today",
    "note": None,
    "tag": "",
}
_PLACEHOLDER_OVERNIGHT: "ExplorerOvernightItem" = {
    "t24": None,
    "label": "Nothing to report from overnight",
    "note": None,
    "tag": "",
}
_PLACEHOLDER_DECISION: "ExplorerDecisionItem" = {
    "verb": "Review",
    "label": "Nothing pending your review",
    "note": None,
}

# An unused fixed slot: the em dash is the vendored set's own mark for a missing
# value (see explorer/README.md, "Null guards").
_EMPTY_SLOT_LABEL = "—"

# Families that read fixed (today, overnight, decisions) item slots; handed fewer, the
# page script throws and the raster is blank, so build_ed pads these buckets.
# tests/integration/test_edition_families_render.py fails if this table falls behind.
_FIXED_SLOTS: dict[str, tuple[int, int, int]] = {
    "boardingpass": (3, 3, 2),
    "metromap": (3, 3, 2),
    "menu": (3, 3, 0),
    "invoice": (3, 3, 0),
    "almanac": (2, 0, 0),
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
    decisions: list[ExplorerDecisionItem]
    stats: ExplorerStats


class ExplorerArt(TypedDict):
    src: str
    title: str
    artist: str
    year: int
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
    headline: str
    deck: str
    content: ExplorerContent
    week: ExplorerWeek | None
    stamp: Stamp | None
    art: ExplorerArt
    assets: dict[str, str]


def build_ed(
    payload: dict,
    *,
    edition_no: int,
    generated_local: str,
    assets: dict[str, str],
    art_credit: str,
    family: str = "",
) -> ExplorerEdition:
    """Build the vendored templates' ed object from a briefing payload dict.

    generated_local (e.g. "6:02 AM"); empty uses the payload's generated_at. assets maps
    asset key to data URI. family picks the headline slot and pads fixed-slot families.
    """
    date_parts = _date_parts(str(payload.get("date", "")))
    sections = payload.get("sections") or []
    today, overnight, decisions = _build_buckets(sections, payload.get("calendar") or [])
    min_today, min_overnight, min_decisions = _FIXED_SLOTS.get(family, (0, 0, 0))
    today += [{**_PLACEHOLDER_TODAY, "label": _EMPTY_SLOT_LABEL}] * (min_today - len(today))
    overnight += [{**_PLACEHOLDER_OVERNIGHT, "label": _EMPTY_SLOT_LABEL}] * (
        min_overnight - len(overnight)
    )
    decisions += [{**_PLACEHOLDER_DECISION, "label": _EMPTY_SLOT_LABEL}] * (
        min_decisions - len(decisions)
    )
    art_title, art_artist = _split_credit(art_credit)
    headline = str(payload.get("headline", ""))
    lede = str(payload.get("lede", ""))
    generated = generated_local or str(payload.get("generated_at") or "")

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
        "headline": headline,
        "deck": lede if family in _TITLE_SLOT_FAMILIES else headline,
        "content": {
            "today": today,
            "overnight": overnight,
            "decisions": decisions,
            "stats": _build_stats(payload.get("tallies")),
        },
        "week": _build_week(payload.get("week")) if family == WEEKLY_FAMILY else None,
        "stamp": _build_stamp(payload.get("stamp_city")) if family == POSTAL_FAMILY else None,
        "art": {
            "src": assets.get("ART1", ""),
            "title": art_title,
            "artist": art_artist,
            "year": 1889,
            "medium": "oil on canvas",
        },
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


def _split_time_prefix(text: str) -> tuple[str | None, str | None, str]:
    """Split item text into (time, t24, label).

    time/t24 are None when the text carries no leading clock prefix (the common case for
    our payload's item text).
    """
    match = _ITEM_TIME_PREFIX_RE.match(text.strip())
    if not match:
        return None, None, text
    time_str, label = match.group(1), match.group(2)
    return time_str, _time24(time_str), label


def _split_credit(credit: str) -> tuple[str, str]:
    """Split "Title — Artist" into (title, artist)."""
    parts = credit.split("—", 1)
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()
    return credit.strip(), ""


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


def _items(sections: list[dict]) -> list[dict]:
    return [item for section in sections for item in section.get("items") or []]


def _clock12(t24: str) -> str:
    """24h "13:05" -> "1:05 PM"."""
    return datetime.strptime(t24, "%H:%M").strftime("%-I:%M %p")


def _event_row(event: dict) -> ExplorerTodayItem:
    start = event.get("start")
    return {
        "time": _clock12(start) if start else None,
        "t24": start or None,
        "label": str(event.get("title", "")),
        "note": event.get("location") or None,
        "tag": "",
    }


def _overnight_row(item: dict) -> ExplorerOvernightItem:
    _, t24, label = _split_time_prefix(str(item.get("text", "")))
    return {
        "t24": t24,
        "label": label,
        "note": None,
        "tag": _OVERNIGHT_TAGS.get(str(item.get("kind")), ""),
    }


def _decision_row(item: dict) -> ExplorerDecisionItem:
    text = str(item.get("text", ""))
    if item.get("kind") == "failed":
        return {"verb": _RETRY_VERB, "label": text, "note": None}
    verb, label = _decision_verb(text)
    return {"verb": verb, "label": label, "note": None}


def _build_buckets(
    sections: list[dict], calendar: list[dict]
) -> tuple[list[ExplorerTodayItem], list[ExplorerOvernightItem], list[ExplorerDecisionItem]]:
    """Map items by meaning (see the module docstring).

    A bucket left empty gets one honest placeholder rather than an array a template might
    index into unconditionally.
    """
    items = _items(sections)
    decision_items = [
        i for i in items if i.get("kind") in _DECISION_KINDS or i.get("kind") == "failed"
    ]
    overnight_items = [
        i for i in items if i.get("kind") not in _DECISION_KINDS and i.get("kind") != "failed"
    ]

    today = [_event_row(e) for e in calendar]
    return (
        today or [_PLACEHOLDER_TODAY],
        [_overnight_row(i) for i in overnight_items] or [_PLACEHOLDER_OVERNIGHT],
        [_decision_row(i) for i in decision_items] or [_PLACEHOLDER_DECISION],
    )


def _positive(value: int) -> int | None:
    return value if value > 0 else None


def _build_stats(tallies: dict | None) -> ExplorerStats:
    """Build the figures from the payload's tallies.

    Mail handled and focus time have no source yet, so they are always None and their
    slots render nothing.
    """
    you = int((tallies or {}).get("done_by_you") or 0)
    gaia = int((tallies or {}).get("done_by_gaia") or 0)
    return {
        "done": _positive(you + gaia),
        "you": _positive(you),
        "gaia": _positive(gaia),
        "mail": None,
        "focus": None,
    }


def _build_week(week: dict | None) -> ExplorerWeek | None:
    if not week:
        return None
    return {
        "days": [{"you": int(d["you"]), "gaia": int(d["gaia"])} for d in week["days"]],
        "shipped": list(week.get("shipped") or []),
        "handled": list(week.get("handled") or []),
        "ahead": [
            {"day": date.fromisoformat(e["date"]).strftime("%a"), "label": str(e["title"])}
            for e in week.get("ahead") or []
        ],
    }


def _build_stamp(slug: str | None) -> Stamp | None:
    """Return the drawn city's stamp skin.

    Legacy payloads without one keep the template's own city axis.
    """
    return stamp_for(slug) if slug else None
