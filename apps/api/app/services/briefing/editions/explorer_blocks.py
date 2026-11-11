"""A brief's drawn blocks -> the ed.blocks every edition template renders in its own idiom.

Code says every fact a block prints: an item's verb or outcome and its app's mark, a
chart's points, labels, range and legend, a goal's counts. The templates only draw them.
The day's calendar is the edition's own block, placed after the first group of items.
"""

from datetime import date, datetime
from typing import Literal, TypedDict

from app.constants.briefing import EDITION_ROWS_SHOWN
from app.constants.integrations import GOOGLE_CALENDAR_INTEGRATION_ID
from app.models.brief_composition_models import (
    BriefBlock,
    ChartBlock,
    NoteBlock,
    ProgressBlock,
    QuoteBlock,
    SectionBlock,
)
from app.models.brief_pool_models import DataSeries, SeriesShape
from app.models.briefing_models import BriefingEvent, BriefingItem, BriefingSection
from app.services.briefing.editions.edition_logos import logo_key

# A week or less of days is named by weekday; a longer run by its date.
_WEEKDAY_SPAN = 7


class ExplorerItem(TypedDict):
    """One placed item: its verb (it asks) or its outcome (it is done), never both."""

    verb: str | None
    outcome: str | None
    title: str
    detail: str | None
    #: The registered mark of the app it came from; None for GAIA's own work.
    logo: str | None
    app: str | None


class ExplorerEvent(TypedDict):
    """One calendar row; an all-day event has no time, a later day's event names its day."""

    t12: str | None
    t24: str | None
    day: str | None
    title: str
    detail: str | None
    logo: str


class ExplorerLead(TypedDict):
    kind: Literal["lead"]
    item: ExplorerItem
    offer: str | None


class ExplorerItems(TypedDict):
    kind: Literal["items"]
    numeral: str
    heading: str
    items: list[ExplorerItem]
    #: Items the group holds beyond those shown, for "+N more in the full brief".
    more: int


class ExplorerCalendar(TypedDict):
    kind: Literal["calendar"]
    events: list[ExplorerEvent]
    more: int
    #: The day's first and last timed starts ("09:30"), shown or not; None with none timed.
    first: str | None
    last: str | None


class ExplorerSeries(TypedDict):
    name: str
    app: str
    logo: str | None
    unit: str
    values: list[float]
    #: Each value as printed: whole numbers bare, the rest to one decimal.
    shown: list[str]
    total: str


class ExplorerChart(TypedDict):
    kind: Literal["chart"]
    chart: str
    title: str
    takeaway: str
    #: The unit every series counts, or None when they differ.
    unit: str | None
    #: The days the chart spans ("Mon 3 – Sun 9 Nov"); None for categories.
    range: str | None
    #: One short label per point ("Mon", "27 Oct", a category).
    x: list[str]
    series: list[ExplorerSeries]


class ExplorerQuote(TypedDict):
    kind: Literal["quote"]
    text: str
    author: str
    app: str
    logo: str | None


class ExplorerProgress(TypedDict):
    kind: Literal["progress"]
    statement: str
    done: int
    total: int


class ExplorerNote(TypedDict):
    kind: Literal["note"]
    text: str


ExplorerBlock = (
    ExplorerLead
    | ExplorerItems
    | ExplorerCalendar
    | ExplorerChart
    | ExplorerQuote
    | ExplorerProgress
    | ExplorerNote
)


def _item(item: BriefingItem) -> ExplorerItem:
    return {
        "verb": item.action.value.capitalize() if item.action is not None else None,
        "outcome": item.outcome.value.capitalize() if item.outcome is not None else None,
        "title": item.text,
        "detail": item.detail,
        "logo": logo_key(item.source),
        "app": item.app,
    }


def _event(event: BriefingEvent, today: str) -> ExplorerEvent:
    start = datetime.strptime(event.start, "%H:%M") if event.start else None
    return {
        "t12": start.strftime("%-I:%M %p") if start else None,
        "t24": event.start or None,
        "day": None if event.date == today else date.fromisoformat(event.date).strftime("%a"),
        "title": event.title,
        "detail": event.location or None,
        "logo": GOOGLE_CALENDAR_INTEGRATION_ID,
    }


def _number(value: float) -> str:
    return f"{value:.0f}" if value == int(value) else f"{value:.1f}"


def _days(series: DataSeries) -> list[date]:
    return [date.fromisoformat(p.x) for p in series.points]


def _x_labels(series: DataSeries) -> list[str]:
    if series.shape is SeriesShape.CATEGORICAL:
        return [p.x for p in series.points]
    days = _days(series)
    if len(days) <= _WEEKDAY_SPAN:
        return [d.strftime("%a") for d in days]
    return [f"{d.day} {d:%b}" for d in days]


def _range(series: DataSeries) -> str | None:
    """Say the days a time series spans: "Mon 3 – Sun 9 Nov", or "27 Oct – 9 Nov" past a week."""
    if series.shape is SeriesShape.CATEGORICAL:
        return None
    first, last = _days(series)[0], _days(series)[-1]
    first_month = "" if first.month == last.month else f" {first:%b}"
    if len(series.points) <= _WEEKDAY_SPAN:
        return f"{first:%a} {first.day}{first_month} – {last:%a} {last.day} {last:%b}"
    return f"{first.day}{first_month} – {last.day} {last:%b}"


def _series(series: DataSeries) -> ExplorerSeries:
    values = [p.y for p in series.points]
    return {
        "name": series.label,
        "app": series.app,
        "logo": logo_key(series.source),
        "unit": series.unit,
        "values": values,
        "shown": [_number(v) for v in values],
        "total": _number(sum(values)),
    }


def _chart(block: ChartBlock) -> ExplorerChart:
    units = {s.unit for s in block.series}
    return {
        "kind": "chart",
        "chart": block.chart.value,
        "title": block.title,
        "takeaway": block.takeaway,
        "unit": units.pop() if len(units) == 1 else None,
        "range": _range(block.series[0]),
        "x": _x_labels(block.series[0]),
        "series": [_series(s) for s in block.series],
    }


def _section_block(block: SectionBlock, section: BriefingSection) -> ExplorerLead | ExplorerItems:
    items = [_item(i) for i in section.items]
    if block.kind == "lead":
        return {"kind": "lead", "item": items[0], "offer": section.items[0].offer}
    return {
        "kind": "items",
        "numeral": section.numeral,
        "heading": section.title,
        "items": items[:EDITION_ROWS_SHOWN],
        "more": max(len(items) - EDITION_ROWS_SHOWN, 0),
    }


def _data_block(block: BriefBlock) -> ExplorerBlock:
    if isinstance(block, ChartBlock):
        return _chart(block)
    if isinstance(block, QuoteBlock):
        quote = block.quote
        return {
            "kind": "quote",
            "text": quote.text,
            "author": quote.author,
            "app": quote.app,
            "logo": logo_key(quote.source),
        }
    if isinstance(block, ProgressBlock):
        goal = block.goal
        return {
            "kind": "progress",
            "statement": goal.statement,
            "done": goal.done,
            "total": goal.done + goal.open,
        }
    if isinstance(block, NoteBlock):
        return {"kind": "note", "text": block.text}
    raise ValueError(f"a {block.kind} block is drawn from its section")


def _calendar(events: list[BriefingEvent], today: str) -> ExplorerCalendar:
    starts = sorted(e.start for e in events if e.start)
    return {
        "kind": "calendar",
        "events": [_event(e, today) for e in events[:EDITION_ROWS_SHOWN]],
        "more": max(len(events) - EDITION_ROWS_SHOWN, 0),
        "first": starts[0] if starts else None,
        "last": starts[-1] if starts else None,
    }


def build_blocks(
    blocks: list[BriefBlock],
    sections: list[BriefingSection],
    calendar: list[BriefingEvent],
    today: str,
) -> list[ExplorerBlock]:
    """Return the edition's blocks in reading order, the calendar after the first group of items."""
    drawn: list[ExplorerBlock] = [
        _section_block(b, sections[b.section]) if isinstance(b, SectionBlock) else _data_block(b)
        for b in blocks
    ]
    if not calendar:
        return drawn
    groups = [i for i, b in enumerate(blocks) if isinstance(b, SectionBlock) and b.kind == "items"]
    leads = bool(blocks) and isinstance(blocks[0], SectionBlock) and blocks[0].kind == "lead"
    after = groups[0] + 1 if groups else int(leads)
    return [*drawn[:after], _calendar(calendar, today), *drawn[after:]]


def printed_logos(
    blocks: list[BriefBlock], sections: list[BriefingSection], calendar: list[BriefingEvent]
) -> set[str]:
    """Return every app mark the drawn blocks and the calendar print."""
    sources: list[str | None] = [GOOGLE_CALENDAR_INTEGRATION_ID] if calendar else []
    for block in blocks:
        if isinstance(block, SectionBlock):
            sources += [item.source for item in sections[block.section].items]
        elif isinstance(block, QuoteBlock):
            sources.append(block.quote.source)
        elif isinstance(block, ChartBlock):
            sources += [series.source for series in block.series]
    return {key for source in sources if (key := logo_key(source)) is not None}


def awaiting(blocks: list[BriefBlock], sections: list[BriefingSection]) -> int | None:
    """Count the todos the drawn items wait on the reader for (a grouped ask counts each); None for none."""
    waiting = sum(
        item.count
        for b in blocks
        if isinstance(b, SectionBlock)
        for item in sections[b.section].items
        if item.action is not None
    )
    return waiting or None
