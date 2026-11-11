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
    MAX_BRIEF_CHARTS,
    MAX_BRIEF_ITEMS,
    MIN_TREND_POINTS,
    BriefOutcome,
)
from app.models.brief_composition_models import (
    BriefBlockKind,
    BriefComposition,
    ChartKind,
    ComposedBlock,
    ComposedChart,
    ComposedItem,
    ComposedItems,
    ComposedLead,
    ComposedProgress,
    ComposedQuote,
    GroupState,
    placed_items,
)
from app.models.brief_pool_models import DataSeries, SeriesShape
from app.services.briefing.fact_pool.pool import FactPool
from app.services.briefing.slots import SlotError, SlotValues, render_slots, slot_problems

#: The strings each kind of block writes.
WRITTEN_FIELDS: dict[BriefBlockKind, tuple[str, ...]] = {
    "lead": ("offer",),
    "items": ("heading",),
    "chart": ("title", "takeaway"),
    "quote": (),
    "progress": (),
    "note": ("text",),
}


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
    if candidate.outcome is not None and item.outcome is None:
        problems.append(
            f"{at}: its line gives outcome {candidate.outcome.value}, so it is placed as that outcome"
        )
    if candidate.action is not None and item.action is None:
        problems.append(
            f"{at}: its line gives action {candidate.action.value}, so it is placed as that action"
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
    units = {s.unit for s in series}
    named = ", ".join(sorted(unit or "no unit" for unit in units))
    return None if len(units) == 1 else f"a stacked_bar stacks one unit, not {named}"


_CHART_MISFITS: dict[ChartKind, Callable[[ChartKind, list[DataSeries]], str | None]] = {
    ChartKind.LINE: _trend_misfit,
    ChartKind.SPARK: _trend_misfit,
    ChartKind.BAR: _bar_misfit,
    ChartKind.STACKED_BAR: _bar_misfit,
}


def _chart_problems(
    where: str, block: ComposedChart, pool: FactPool, values: SlotValues
) -> list[str]:
    problems = _text_problems(where, "title", block.title, BRIEF_CHART_TITLE_MAX_CHARS, values)
    problems += _text_problems(where, "takeaway", block.takeaway, BRIEF_TAKEAWAY_MAX_CHARS, values)
    by_id = pool.series_by_id
    unknown = [i for i in block.series_ids if i not in by_id]
    if unknown:
        problems.append(f"{where}: no series {', '.join(unknown)} in the pool")
    if not block.series_ids:
        problems.append(f"{where}: no series_ids")
    elif not unknown:
        misfit = _CHART_MISFITS[block.chart](block.chart, [by_id[i] for i in block.series_ids])
        problems += [f"{where}: {misfit}"] if misfit else []
    return problems


def _lead_problems(where: str, index: int, block: ComposedLead, values: SlotValues) -> list[str]:
    problems = [] if index == 0 else [f"{where}: a lead opens the brief, so it is block 1"]
    if block.item.action is None:
        problems.append(f"{where}: a lead is something to act on, so its item has an action")
    return problems + _text_problems(where, "offer", block.offer, BRIEF_OFFER_MAX_CHARS, values)


# The outcomes each group state holds; a needs_you group holds actions instead.
_STATE_OUTCOMES: dict[GroupState, frozenset[BriefOutcome]] = {
    GroupState.DONE: frozenset(BriefOutcome) - {BriefOutcome.STARTED, BriefOutcome.FAILED},
    GroupState.IN_PROGRESS: frozenset({BriefOutcome.STARTED}),
}


def _state_of(item: ComposedItem) -> GroupState | None:
    """Return the group state an item's action or outcome belongs in; None when none holds it."""
    if item.action is not None:
        return GroupState.NEEDS_YOU
    return next((s for s, held in _STATE_OUTCOMES.items() if item.outcome in held), None)


def _state_problems(where: str, block: ComposedItems) -> list[str]:
    """Name each item the group's declared state does not hold, and the state that does."""
    problems: list[str] = []
    for item in block.items:
        side = item.action or item.outcome
        belongs = _state_of(item)
        if side is None or belongs is block.state:
            continue
        said = f"{'action' if item.action else 'outcome'} {side.value}"
        article = "an" if block.state is GroupState.IN_PROGRESS else "a"
        home = (
            f"move it to {'an' if belongs is GroupState.IN_PROGRESS else 'a'} {belongs.value} group"
            if belongs is not None
            else "a failed item needs the user: give it action retry in a needs_you group"
        )
        problems.append(
            f"{where}, item {item.id} has {said}, which {article} {block.state.value} group "
            f"does not hold; {home}"
        )
    return problems


def _own_problems(
    index: int, block: ComposedBlock, pool: FactPool, values: SlotValues
) -> list[str]:
    """Name what breaks the block's own kind of contract, its items aside."""
    where = _where(index, block)
    if isinstance(block, ComposedLead):
        return _lead_problems(where, index, block, values)
    if isinstance(block, ComposedItems):
        heading = _text_problems(where, "heading", block.heading, BRIEF_HEADING_MAX_CHARS, values)
        return heading + _state_problems(where, block)
    if isinstance(block, ComposedChart):
        return _chart_problems(where, block, pool, values)
    if isinstance(block, ComposedQuote):
        known = block.quote_id in pool.quotes_by_id
        return [] if known else [f"{where}: no quote {block.quote_id} in the pool"]
    if isinstance(block, ComposedProgress):
        known = block.goal_id in pool.goals_by_id
        return [] if known else [f"{where}: no goal {block.goal_id} in the pool"]
    return _text_problems(where, "text", block.text, BRIEF_NOTE_MAX_CHARS, values)


def _block_problems(
    index: int, block: ComposedBlock, pool: FactPool, values: SlotValues
) -> list[str]:
    where = _where(index, block)
    leads = isinstance(block, ComposedLead)
    return _own_problems(index, block, pool, values) + [
        p
        for item in placed_items(block)
        for p in _item_problems(where, item, pool, values, leads=leads)
    ]


def _placed_ids(composition: BriefComposition) -> Iterator[str]:
    """Yield every id a block places, named by its kind, so a repeat is caught across kinds of block."""
    for block in composition.blocks:
        yield from (f"item {item.id}" for item in placed_items(block))
        if isinstance(block, ComposedChart):
            yield from (f"series {s}" for s in block.series_ids)
        if isinstance(block, ComposedQuote):
            yield f"quote {block.quote_id}"
        if isinstance(block, ComposedProgress):
            yield f"goal {block.goal_id}"


def _budget_problems(composition: BriefComposition) -> list[str]:
    blocks = composition.blocks
    problems: list[str] = []
    items = sum(len(placed_items(b)) for b in blocks)
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
        for item in placed_items(block):
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
