"""Hold a composition to its contract: ids only, each once, charts that fit their series, the page budget.

Every rule returns the problems it found in words the composition's retry can act on;
an empty list is a composition the brief can be built from.
"""

from collections import Counter
from collections.abc import Callable, Iterator

from app.constants.briefing import (
    BRIEF_CHART_TITLE_MAX_CHARS,
    BRIEF_HEADING_MAX_CHARS,
    BRIEF_ITEM_DETAIL_MAX_CHARS,
    BRIEF_ITEM_TITLE_MAX_CHARS,
    BRIEF_NOTE_MAX_CHARS,
    BRIEF_OFFER_MAX_CHARS,
    BRIEF_TAKEAWAY_MAX_CHARS,
    MAX_BAR_CATEGORIES,
    MAX_BRIEF_BLOCKS,
    MAX_BRIEF_CHARTS,
    MAX_BRIEF_ITEMS,
    MAX_ITEMS_PER_BLOCK,
    MIN_TREND_POINTS,
)
from app.models.brief_composition_models import (
    BriefBlockKind,
    BriefComposition,
    ChartKind,
    ComposedBlock,
    ComposedItem,
)
from app.models.brief_pool_models import DataSeries, SeriesShape
from app.services.briefing.fact_pool.pool import FactPool
from app.services.briefing.slots import SlotError, SlotValues, render_slots, slot_problems

# The strings each kind of block writes; a field a kind does not own is never read, rendered or shown.
WRITTEN_FIELDS: dict[BriefBlockKind, tuple[str, ...]] = {
    "lead": ("offer",),
    "items": ("heading",),
    "chart": ("title", "takeaway"),
    "quote": (),
    "progress": (),
    "note": ("text",),
}
#: The kinds of block that place pool items.
ITEM_BLOCKS: frozenset[BriefBlockKind] = frozenset({"lead", "items"})


def _where(index: int, block: ComposedBlock) -> str:
    return f"block {index + 1} ({block.kind})"


def _shown(text: str, values: SlotValues) -> str:
    """Return the text as the brief shows it, its slots filled; a slot that cannot fill is named elsewhere."""
    try:
        return render_slots(text, values, {})
    except SlotError:
        return text


def _text_problems(
    where: str, name: str, text: str | None, limit: int, values: SlotValues
) -> list[str]:
    stripped = _shown(text or "", values).strip()
    if not stripped:
        return [f"{where}: no {name}"]
    if len(stripped) > limit:
        return [f"{where}: a {name} of {len(stripped)} characters, over {limit}"]
    return []


def _item_problems(
    where: str, item: ComposedItem, pool: FactPool, values: SlotValues, *, leads: bool
) -> list[str]:
    at = f"{where}, item {item.id}"
    candidate = pool.items.get(item.id)
    if candidate is None:
        return [f"{at}: no item {item.id} in the pool"]
    problems = _text_problems(at, "title", item.title, BRIEF_ITEM_TITLE_MAX_CHARS, values)
    if len(_shown(item.detail or "", values).strip()) > BRIEF_ITEM_DETAIL_MAX_CHARS:
        problems.append(f"{at}: a detail over {BRIEF_ITEM_DETAIL_MAX_CHARS} characters")
    if (item.action is None) == (item.outcome is None):
        problems.append(
            f"{at}: give exactly one of action (it needs the user) or outcome (it got somewhere)"
        )
    if candidate.is_event and not leads:
        problems.append(
            f"{at}: a calendar event can only lead; the edition draws the day's calendar"
        )
    return problems


def _shared_x(series: list[DataSeries]) -> bool:
    return len({tuple(p.x for p in s.points) for s in series}) == 1


def _trend_misfit(chart: ChartKind, series: list[DataSeries]) -> str | None:
    """Name why a line or spark cannot draw the series: too few days, too many lines, unshared days."""
    timed = all(s.shape is SeriesShape.TIME_SERIES for s in series)
    if not timed or min(len(s.points) for s in series) < MIN_TREND_POINTS:
        return f"a {chart} needs a time series of at least {MIN_TREND_POINTS} days"
    if chart is ChartKind.SPARK and len(series) > 1:
        return "a spark draws one series"
    return (
        None if _shared_x(series) else "a line over several series needs them to share their days"
    )


def _bar_misfit(chart: ChartKind, series: list[DataSeries]) -> str | None:
    """Name why a bar or a stack cannot draw the series: too many bars, or series that do not stack."""
    longest = max(len(s.points) for s in series)
    if longest > MAX_BAR_CATEGORIES:
        return f"a {chart} draws at most {MAX_BAR_CATEGORIES} bars, not {longest}"
    if chart is ChartKind.BAR:
        return None if len(series) == 1 else "a bar draws one series; stack several"
    if len(series) < 2 or not _shared_x(series):
        return "a stacked_bar needs two or more series sharing their days or categories"
    units = sorted({s.unit for s in series})
    return None if len(units) == 1 else f"a stacked_bar stacks one unit, not {', '.join(units)}"


_CHART_MISFITS: dict[ChartKind, Callable[[ChartKind, list[DataSeries]], str | None]] = {
    ChartKind.LINE: _trend_misfit,
    ChartKind.SPARK: _trend_misfit,
    ChartKind.BAR: _bar_misfit,
    ChartKind.STACKED_BAR: _bar_misfit,
}


def _chart_problems(
    where: str, block: ComposedBlock, pool: FactPool, values: SlotValues
) -> list[str]:
    problems = _text_problems(where, "title", block.title, BRIEF_CHART_TITLE_MAX_CHARS, values)
    problems += _text_problems(where, "takeaway", block.takeaway, BRIEF_TAKEAWAY_MAX_CHARS, values)
    by_id = pool.series_by_id
    unknown = [i for i in block.series_ids if i not in by_id]
    if unknown:
        problems.append(f"{where}: no series {', '.join(unknown)} in the pool")
    if block.chart is None:
        problems.append(f"{where}: no chart kind ({', '.join(ChartKind)})")
    if not block.series_ids:
        problems.append(f"{where}: no series_ids")
    elif block.chart is not None and not unknown:
        misfit = _CHART_MISFITS[block.chart](block.chart, [by_id[i] for i in block.series_ids])
        problems += [f"{where}: {misfit}"] if misfit else []
    return problems


def _block_problems(
    index: int, block: ComposedBlock, pool: FactPool, values: SlotValues
) -> list[str]:
    where = _where(index, block)
    problems: list[str] = []
    if block.kind == "lead":
        if index != 0:
            problems.append(f"{where}: a lead opens the brief, so it is block 1")
        if len(block.items) != 1:
            problems.append(f"{where}: a lead holds exactly one item, not {len(block.items)}")
        if any(item.action is None for item in block.items):
            problems.append(f"{where}: a lead is something to act on, so its item has an action")
        problems += _text_problems(where, "offer", block.offer, BRIEF_OFFER_MAX_CHARS, values)
    elif block.kind == "items":
        problems += _text_problems(where, "heading", block.heading, BRIEF_HEADING_MAX_CHARS, values)
        if not 1 <= len(block.items) <= MAX_ITEMS_PER_BLOCK:
            problems.append(
                f"{where}: {len(block.items)} items; a group holds 1 to {MAX_ITEMS_PER_BLOCK}"
            )
    elif block.kind == "chart":
        problems += _chart_problems(where, block, pool, values)
    elif block.kind == "quote" and block.quote_id not in pool.quotes_by_id:
        problems.append(f"{where}: no quote {block.quote_id} in the pool")
    elif block.kind == "progress" and block.goal_id not in pool.goals_by_id:
        problems.append(f"{where}: no goal {block.goal_id} in the pool")
    elif block.kind == "note":
        problems += _text_problems(where, "text", block.text, BRIEF_NOTE_MAX_CHARS, values)
    if block.kind not in ITEM_BLOCKS:
        return problems
    leads = block.kind == "lead"
    return problems + [
        p for item in block.items for p in _item_problems(where, item, pool, values, leads=leads)
    ]


def _placed_ids(composition: BriefComposition) -> Iterator[str]:
    """Yield every id a block places, named by its kind, so a repeat is caught across kinds of block."""
    for block in composition.blocks:
        if block.kind in ITEM_BLOCKS:
            yield from (f"item {item.id}" for item in block.items)
        if block.kind == "chart":
            yield from (f"series {s}" for s in block.series_ids)
        if block.kind == "quote" and block.quote_id:
            yield f"quote {block.quote_id}"
        if block.kind == "progress" and block.goal_id:
            yield f"goal {block.goal_id}"


def _budget_problems(composition: BriefComposition) -> list[str]:
    blocks = composition.blocks
    problems: list[str] = []
    if len(blocks) > MAX_BRIEF_BLOCKS:
        problems.append(f"{len(blocks)} blocks; a brief holds at most {MAX_BRIEF_BLOCKS}")
    items = sum(len(b.items) for b in blocks)
    if items > MAX_BRIEF_ITEMS:
        problems.append(f"{items} items in all; a brief holds at most {MAX_BRIEF_ITEMS}")
    charts = sum(1 for b in blocks if b.kind == "chart")
    if charts > MAX_BRIEF_CHARTS:
        problems.append(f"{charts} charts; a brief holds at most {MAX_BRIEF_CHARTS}")
    leads = sum(1 for b in blocks if b.kind == "lead")
    if leads > 1:
        problems.append(f"{leads} leads; a brief has at most one")
    return problems


def _slot_problems(composition: BriefComposition, values: SlotValues) -> list[str]:
    problems: list[str] = []
    for index, block in enumerate(composition.blocks):
        where = _where(index, block)
        for name in WRITTEN_FIELDS[block.kind]:
            text = getattr(block, name)
            if text:
                problems += slot_problems(f"{where} {name}", text, values)
        for item in block.items if block.kind in ITEM_BLOCKS else []:
            for name, text in (("title", item.title), ("detail", item.detail)):
                if text:
                    problems += slot_problems(
                        f"{where} item {item.id} {name}", text, values, figures_are_slots=False
                    )
    return problems


def composition_problems(
    composition: BriefComposition, pool: FactPool, values: SlotValues
) -> list[str]:
    """Return every way the composition breaks its contract with the pool; empty when it holds."""
    problems = [
        p
        for index, block in enumerate(composition.blocks)
        for p in _block_problems(index, block, pool, values)
    ]
    repeated = sorted(i for i, n in Counter(_placed_ids(composition)).items() if n > 1)
    if repeated:
        problems.append(f"placed more than once: {', '.join(repeated)}")
    return problems + _budget_problems(composition) + _slot_problems(composition, values)
