"""``BriefingPayload`` -> the vendored explorer templates' ``ed`` shape.

The 20 templates in ``editions/explorer/js/`` were designed against a fixed
data shape (see ``explorer-contract.md``'s ``editionData()`` and its Node
verification snippet): three buckets (today/overnight/decisions) plus a
stats tuple. Our payload (``app/models/briefing_models.py``) is looser — a
variable number of sections, free-form item text, no per-item time field.
This module bridges the two by each item's ``kind``, never by which section
it sat in, so any section layout renders rather than crashing the templates.

``ed`` values are passed through **unescaped** — every vendored template
HTML-escapes its own text via a local ``esc()`` helper, so pre-escaping here
would double-encode entities.
"""

from datetime import date
import re
from typing import TypedDict

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

# The item's state as the short caps tag the explorer templates expect (e.g.
# "REVIEW", "SHIP", "DONE" in the contract's sample data). The item text never
# repeats it: the payload carries the state in ``kind`` and the title in ``text``.
_KIND_TAGS: dict[str, str] = {
    "proposal": "APPROVAL",
    "you": "YOUR MOVE",
    "needs_you": "YOUR MOVE",
    "gaia": "IN PROGRESS",
    "lookback": "DONE",
    "failed": "FAILED",
    "note": "",
}

# Which bucket an item renders in, by kind: GAIA's work (finished or running)
# is the overnight column, anything waiting on the reader is a decision, and a
# failure or plain note is a today highlight. Unknown kinds read as notes.
_KIND_TO_BUCKET: dict[str, str] = {
    "gaia": "overnight",
    "lookback": "overnight",
    "you": "decisions",
    "needs_you": "decisions",
    "proposal": "decisions",
    "failed": "today",
    "note": "today",
}

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

# Families whose render reads fixed item slots — (today, overnight, decisions)
# item counts — because the founder fixture always held 3/3/2 items. Handed
# fewer, the page script throws and the raster comes out blank, so build_ed
# pads these buckets with empty slots. Read off the vendored js/ (which never
# changes in place); tests/integration/test_edition_families_render.py renders
# every family with a sparse brief and fails if this table falls behind.
_FIXED_SLOTS: dict[str, tuple[int, int, int]] = {
    "boardingpass": (3, 3, 2),
    "metromap": (3, 3, 2),
    "menu": (3, 3, 0),
    "invoice": (3, 3, 0),
    "almanac": (2, 0, 0),
    "weekly": (3, 0, 0),
}


class ExplorerTodayItem(TypedDict):
    """One ``content.today`` row — field names are camelCase-free but keyed
    exactly as the vendored JS templates read them (``t24``, not ``t_24``)."""

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
    done: int
    you: int
    gaia: int
    mail: int
    focus: str


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


class ExplorerEdition(TypedDict):
    """The exact ``ed`` shape ``explorer-contract.md``'s templates render
    against — field names match the vendored JS verbatim (``dateLong``,
    ``editionNo``, ``monthShort``), not Python naming convention."""

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
    deck: str
    content: ExplorerContent
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
    """Build the vendored templates' ``ed`` object from a
    ``BriefingPayload.model_dump()`` dict.

    Args:
        payload: A ``BriefingPayload.model_dump()`` dict.
        edition_no: Sequential edition number (``ed.n`` / ``ed.editionNo``).
        generated_local: Human generation time, e.g. ``"6:02 AM"`` — may be
            empty (not yet wired end to end); an unparseable value degrades
            to itself rather than raising.
        assets: Asset key -> data URI map (``ed.assets`` / ``ed.art.src``).
        art_credit: The vendored credits.json entry for ART1, e.g.
            ``"Wheat Field with Cypresses — Vincent van Gogh"``.
        family: The explorer family rendering this ``ed``; families that read
            fixed item slots get their short buckets padded (``_FIXED_SLOTS``).
    """
    date_parts = _date_parts(str(payload.get("date", "")))
    today, overnight, decisions = _bucket_sections(payload.get("sections") or [])
    min_today, min_overnight, min_decisions = _FIXED_SLOTS.get(family, (0, 0, 0))
    today += [{**_PLACEHOLDER_TODAY, "label": _EMPTY_SLOT_LABEL}] * (min_today - len(today))
    overnight += [{**_PLACEHOLDER_OVERNIGHT, "label": _EMPTY_SLOT_LABEL}] * (
        min_overnight - len(overnight)
    )
    decisions += [{**_PLACEHOLDER_DECISION, "label": _EMPTY_SLOT_LABEL}] * (
        min_decisions - len(decisions)
    )
    art_title, art_artist = _split_credit(art_credit)

    return {
        "n": edition_no,
        "weekday": date_parts[0],
        "day": date_parts[1],
        "month": date_parts[2],
        "monthShort": date_parts[3],
        "year": date_parts[4],
        "dateLong": date_parts[5],
        "editionNo": edition_no,
        "time": generated_local,
        "time24": _time24(generated_local),
        "deck": str(payload.get("lede", "")),
        "content": {
            "today": today,
            "overnight": overnight,
            "decisions": decisions,
            "stats": _build_stats(payload.get("stats") or []),
        },
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
    """(weekday, day, month, monthShort, year, dateLong) — an unparseable or
    empty date degrades to blanks rather than raising; ``dateLong`` falls
    back to the raw string so the date is never silently dropped."""
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
    """12h "6:02 AM" -> 24h "06:02". Returns the input unchanged if it
    doesn't match that shape (empty string, or a format that changes later)."""
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
    """(time, t24, label) — time/t24 are None when the text carries no
    leading clock prefix (the common case for our payload's item text)."""
    match = _ITEM_TIME_PREFIX_RE.match(text.strip())
    if not match:
        return None, None, text
    time_str, label = match.group(1), match.group(2)
    return time_str, _time24(time_str), label


def _split_credit(credit: str) -> tuple[str, str]:
    """ "Title — Artist" -> (title, artist)."""
    parts = credit.split("—", 1)
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()
    return credit.strip(), ""


def _decision_verb(text: str) -> tuple[str, str]:
    """A leading imperative word ("Approve", "Decide", ...) becomes the
    verb and is stripped from the label; otherwise the verb defaults to
    "Review" and the label is the text verbatim."""
    words = text.strip().split(None, 1)
    if not words:
        return "Review", text
    first = words[0].strip(":,.-")
    if first.lower() in _IMPERATIVE_VERBS:
        rest = words[1] if len(words) > 1 else ""
        return first.capitalize(), rest.lstrip(": -–—")
    return "Review", text


def _item_kind(item: dict) -> str:
    """An item's ``kind`` as a key for the two lookup tables below."""
    # No default on purpose: an absent kind stringifies to "None", which misses
    # both _KIND_TAGS and _KIND_TO_BUCKET and so lands on their "" / "today"
    # fallbacks - exactly where an explicit "note" default landed.
    return str(item.get("kind"))


def _map_today_item(item: dict) -> ExplorerTodayItem:
    text = str(item.get("text", ""))
    kind = _item_kind(item)
    time_str, t24, label = _split_time_prefix(text)
    return {
        "time": time_str,
        "t24": t24,
        "label": label,
        "note": None,
        "tag": _KIND_TAGS.get(kind, ""),
    }


def _map_overnight_item(item: dict) -> ExplorerOvernightItem:
    text = str(item.get("text", ""))
    kind = _item_kind(item)
    _, t24, label = _split_time_prefix(text)
    return {"t24": t24, "label": label, "note": None, "tag": _KIND_TAGS.get(kind, "")}


def _map_decision_item(item: dict) -> ExplorerDecisionItem:
    text = str(item.get("text", ""))
    verb, label = _decision_verb(text)
    return {"verb": verb, "label": label, "note": None}


def _bucket_sections(
    sections: list[dict],
) -> tuple[list[ExplorerTodayItem], list[ExplorerOvernightItem], list[ExplorerDecisionItem]]:
    """Every item goes to the bucket its ``kind`` names, in payload order. A
    bucket left genuinely empty gets one honest placeholder item rather than an
    array a template might index into unconditionally — so "Nothing pending
    your review" shows only when nothing is waiting on the reader."""
    raw: dict[str, list[dict]] = {"today": [], "overnight": [], "decisions": []}
    for section in sections:
        for item in section.get("items") or []:
            raw[_KIND_TO_BUCKET.get(_item_kind(item), "today")].append(item)

    today = [_map_today_item(i) for i in raw["today"]] or [_PLACEHOLDER_TODAY]
    overnight = [_map_overnight_item(i) for i in raw["overnight"]] or [_PLACEHOLDER_OVERNIGHT]
    decisions = [_map_decision_item(i) for i in raw["decisions"]] or [_PLACEHOLDER_DECISION]
    return today, overnight, decisions


def _match_stat(stats: list[dict], *keywords: str) -> object:
    for stat in stats:
        # No default on purpose: a label-less stat stringifies to "none", which
        # matches nothing so long as no keyword _build_stats passes is a
        # substring of "none" (today: done/you/gaia/mail/focus). Keep that true
        # when adding one, or give this a "" default back.
        label = str(stat.get("label")).lower()
        if any(keyword in label for keyword in keywords):
            return stat.get("value")
    return None


def _stat_int(stats: list[dict], *keywords: str) -> int:
    raw = _match_stat(stats, *keywords)
    if raw is None:
        return 0
    try:
        return int(str(raw).strip())
    except ValueError:
        return 0


def _build_stats(stats: list[dict]) -> ExplorerStats:
    focus_raw = _match_stat(stats, "focus")
    return {
        "done": _stat_int(stats, "done"),
        "you": _stat_int(stats, "you"),
        "gaia": _stat_int(stats, "gaia"),
        # "mail" already covers "email"/"e-mail" labels - it is a substring of both.
        "mail": _stat_int(stats, "mail"),
        "focus": str(focus_raw) if focus_raw is not None else "0h",
    }
