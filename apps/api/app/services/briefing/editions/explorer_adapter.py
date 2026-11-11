"""BriefingPayload -> the vendored explorer templates' ed shape.

ed carries the edition's furniture (date, recipient, figures, codes, a stamp or a painting)
and the brief's drawn blocks (explorer_blocks.py), which every family renders in its own
idiom. Unknown or zero figures are None so the template renders nothing for them.

ed values are passed through unescaped: every vendored template HTML-escapes its own
text, so pre-escaping here would double-encode entities.
"""

from datetime import date
import re
from typing import TypedDict

from app.constants.briefing import POSTAL_FAMILY, WEEKLY_FAMILY
from app.models.briefing_models import BriefingEvent, BriefingPayload, BriefingTallies
from app.services.briefing.editions.codes import CodeGeometry, Symbology, family_codes
from app.services.briefing.editions.explorer_blocks import ExplorerBlock, awaiting, build_blocks
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

_GENERATED_TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})\s*([AaPp][Mm])$")


class ExplorerStats(TypedDict):
    """Each figure is None when unknown or zero; the templates guard on it."""

    done: int | None
    you: int | None
    gaia: int | None
    mail: int | None
    focus: str | None


class ExplorerArt(TypedDict):
    """The painting a framed family hangs (editions/artworks.py), its image a hosted URL."""

    src: str
    title: str
    artist: str
    year: str
    medium: str


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
    #: The brief's drawn blocks in reading order, the calendar among them.
    blocks: list[ExplorerBlock]
    #: Todos waiting on the reader (a grouped ask counts each); None when nothing waits.
    awaiting: int | None
    stats: ExplorerStats | None
    stamp: Stamp | None
    #: None for a family that hangs no painting.
    art: ExplorerArt | None
    assets: dict[str, str]
    #: The codes the family prints (none for most), each encoding the brief's link.
    codes: dict[Symbology, CodeGeometry]


def build_ed(
    payload: BriefingPayload,
    *,
    edition_no: int,
    generated_local: str,
    assets: dict[str, str],
    art: ExplorerArt | None,
    family: str,
) -> ExplorerEdition:
    """Build the vendored templates' ed object from a briefing payload.

    generated_local (e.g. "6:02 AM"); empty uses the payload's generated_at. assets maps
    asset key to image URL. family decides whether the calendar is the week ahead, and the stamp.
    """
    date_parts = _date_parts(payload.date)
    calendar = edition_calendar(payload, family)
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
        "blocks": build_blocks(payload.blocks, payload.sections, calendar, payload.date),
        "awaiting": awaiting(payload.blocks, payload.sections),
        "stats": _build_stats(payload.tallies),
        "stamp": _build_stamp(payload.stamp_city) if family == POSTAL_FAMILY else None,
        "art": art,
        "assets": assets,
        "codes": family_codes(family, payload.link),
    }


def edition_calendar(payload: BriefingPayload, family: str) -> list[BriefingEvent]:
    """Return the events the family's calendar lists: the weekly's week ahead, else today's."""
    return payload.week.ahead if family == WEEKLY_FAMILY and payload.week else payload.calendar


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


def _positive(value: int) -> int | None:
    return value if value > 0 else None


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


def _build_stamp(slug: str | None) -> Stamp | None:
    """Return the drawn city's stamp skin.

    Legacy payloads without one keep the template's own city axis.
    """
    return stamp_for(slug) if slug else None
