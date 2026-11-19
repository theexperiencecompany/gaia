"""Lay a checked composition out as the brief's sections and blocks, and read back what it placed."""

from collections.abc import Mapping
from dataclasses import dataclass

from app.constants.briefing import GAIA_SOURCE, LEAD_HEADING, SECTION_NUMERALS
from app.models.brief_candidate_models import BriefCandidate
from app.models.brief_composition_models import (
    BriefBlock,
    BriefComposition,
    ChartBlock,
    ComposedBlock,
    ComposedChart,
    ComposedItem,
    ComposedItems,
    ComposedLead,
    ComposedNote,
    ComposedProgress,
    ComposedQuote,
    NoteBlock,
    ProgressBlock,
    QuoteBlock,
    SectionBlock,
    placed_items,
)
from app.models.briefing_models import (
    NEEDS_YOU_ITEM_KINDS,
    BriefingItem,
    BriefingItemKind,
    BriefingSection,
    BriefPoolItem,
)
from app.models.scout_models import RememberedSignal
from app.services.briefing.fact_pool.pool import FactPool
from shared.py.wide_events import log


@dataclass(frozen=True)
class Chosen:
    """The brief's sections, each item beside the pool id and candidate it came from, in order."""

    sections: list[BriefingSection]
    picked: list[list[tuple[int, BriefCandidate]]]


@dataclass(frozen=True)
class Laid:
    """The composition laid out: its sections, its blocks in reading order, and what it left out."""

    chosen: Chosen
    blocks: list[BriefBlock]
    uncomposed: list[BriefPoolItem]


def _item_kind(asks: bool, candidate: BriefCandidate) -> BriefingItemKind:
    """How a placed item reads: its own state, unless placing it says it waits on the user or not."""
    if asks and candidate.state not in NEEDS_YOU_ITEM_KINDS:
        return "you"
    if not asks and candidate.state in NEEDS_YOU_ITEM_KINDS:
        return "note"
    return candidate.state


def _item(placed: ComposedItem, candidate: BriefCandidate, offer: str | None) -> BriefingItem:
    """Word a placed item; what its producer knows beats the composition's word on the same side."""
    asks = placed.action is not None
    return BriefingItem(
        text=placed.title.strip(),
        detail=(placed.detail or "").strip() or None,
        action=(candidate.action or placed.action) if asks else None,
        outcome=None if asks else (candidate.outcome or placed.outcome),
        todo_id=candidate.todo_id,
        kind=_item_kind(asks, candidate),
        count=candidate.count,
        app=candidate.app,
        source=candidate.source,
        url=candidate.url,
        people=list(candidate.people),
        offer=offer,
    )


def _section(block: ComposedLead | ComposedItems, pool: FactPool, numeral: str) -> BriefingSection:
    if isinstance(block, ComposedLead):
        offer = block.offer.strip() or None
        return BriefingSection(
            numeral=numeral,
            title=LEAD_HEADING,
            items=[_item(block.item, pool.items[block.item.id], offer)],
        )
    return BriefingSection(
        numeral=numeral,
        title=block.heading.strip(),
        items=[_item(placed, pool.items[placed.id], None) for placed in block.items],
    )


def _data_block(block: ComposedBlock, pool: FactPool) -> BriefBlock:
    """Resolve a chart, quote, progress or note block's ids into the data the pool holds."""
    if isinstance(block, ComposedChart):
        by_id = pool.series_by_id
        return ChartBlock(
            chart=block.chart,
            title=block.title.strip(),
            takeaway=block.takeaway.strip(),
            series=[by_id[i] for i in block.series_ids],
        )
    if isinstance(block, ComposedQuote):
        return QuoteBlock(quote=pool.quotes_by_id[block.quote_id])
    if isinstance(block, ComposedProgress):
        return ProgressBlock(goal=pool.goals_by_id[block.goal_id])
    if isinstance(block, ComposedNote):
        return NoteBlock(text=block.text.strip())
    raise ValueError(f"a {block.kind} block is laid out as a section, not as data")


def _uncomposed(candidate: BriefCandidate) -> BriefPoolItem:
    signal = candidate.signal
    detail = (signal.why or signal.state) if signal is not None else candidate.detail
    return BriefPoolItem(
        title=candidate.title,
        detail=detail,
        kind=candidate.state,
        app=candidate.app,
        url=candidate.url,
        todo_id=candidate.todo_id,
    )


def lay_out(composition: BriefComposition, pool: FactPool) -> Laid:
    """Lay the rendered composition out: lead and items blocks as numbered sections, the rest as data."""
    sections: list[BriefingSection] = []
    picked: list[list[tuple[int, BriefCandidate]]] = []
    blocks: list[BriefBlock] = []
    for block in composition.blocks:
        if isinstance(block, ComposedLead | ComposedItems):
            blocks.append(SectionBlock(kind=block.kind, section=len(sections)))
            sections.append(_section(block, pool, SECTION_NUMERALS[len(sections)]))
            picked.append([(p.id, pool.items[p.id]) for p in placed_items(block)])
        else:
            blocks.append(_data_block(block, pool))
    placed = {i for ids in picked for i, _ in ids}
    return Laid(
        chosen=Chosen(sections=sections, picked=picked),
        blocks=blocks,
        uncomposed=[
            _uncomposed(c) for i, c in pool.items.items() if i not in placed and not c.is_event
        ],
    )


def _block_sources(block: BriefBlock) -> list[tuple[str, str]]:
    """Return the (source, app) of every series a chart draws and of a quote."""
    if isinstance(block, ChartBlock):
        return [(series.source, series.app) for series in block.series]
    if isinstance(block, QuoteBlock):
        return [(block.quote.source, block.quote.app)]
    return []


def sources_shown(laid: Laid, items: Mapping[int, BriefCandidate]) -> list[str]:
    """Name the apps the brief shows something from: an item, a calendar event, a series or a quote."""
    picked = {i for group in laid.chosen.picked for i, _ in group}
    shown = [(c.source, c.app) for i, c in items.items() if i in picked or c.is_event]
    shown += [pair for block in laid.blocks for pair in _block_sources(block)]
    return list(dict.fromkeys(app for source, app in shown if source != GAIA_SOURCE))


def carried_ids(items: Mapping[int, BriefCandidate], duplicates: list[str]) -> list[str]:
    """Return every held result the brief accounts for: each is on its page, composed or not."""
    return [held for c in items.values() if (held := c.held_id) is not None] + duplicates


def chosen_signals(
    chosen: Chosen, remembered: list[RememberedSignal]
) -> list[tuple[int, RememberedSignal]]:
    """Return the app signals the composition placed, by fact id, with their memory for the apps block."""
    by_key = {(r.signal.integration_id, r.signal.external_id): r for r in remembered}
    return [
        (fact_id, by_key[(c.signal.integration_id, c.signal.external_id)])
        for picked in chosen.picked
        for fact_id, c in picked
        if c.signal is not None
    ]


def log_composition(pool: FactPool, laid: Laid) -> None:
    log.set_ns(
        "brief_composition",
        pool_items=len(pool.items),
        series=len(pool.series),
        quotes=len(pool.quotes),
        goals=len(pool.goals),
        blocks=[b.kind for b in laid.blocks],
        items=sum(len(s.items) for s in laid.chosen.sections),
        uncomposed=len(laid.uncomposed),
    )


def event_ids(pool: Mapping[int, BriefCandidate]) -> list[int]:
    """Return the pool id of each calendar event, in calendar order."""
    return [i for i, c in pool.items() if c.is_event]
