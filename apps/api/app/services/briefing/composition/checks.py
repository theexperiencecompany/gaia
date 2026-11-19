"""Hold a composition to its contract: ids only, each once, charts that fit their series, the page budget.

Every rule returns the problems it found in words the composition's retry can act on;
an empty list is a composition the brief can be built from.
"""

from collections import Counter
from collections.abc import Callable, Iterator

from app.agents.prompts import brief_check_prompts as says
from app.constants.briefing import (
    BRIEF_CHART_TITLE_MAX_CHARS,
    BRIEF_HEADING_MAX_CHARS,
    BRIEF_ITEM_DETAIL_MAX_CHARS,
    BRIEF_ITEM_TITLE_MAX_CHARS,
    BRIEF_NOTE_MAX_CHARS,
    BRIEF_TAKEAWAY_MAX_CHARS,
    MAX_BAR_CATEGORIES,
    MAX_BRIEF_CHARTS,
    MAX_BRIEF_ITEMS,
    MAX_LINE_SERIES,
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
    placed_items,
)
from app.models.brief_item_models import GroupState
from app.models.brief_pool_models import DataSeries, SeriesShape
from app.services.briefing.fact_pool.pool import FactPool
from app.services.briefing.slots import SlotError, SlotValues, render_slots, slot_problems

#: The strings each kind of block writes.
WRITTEN_FIELDS: dict[BriefBlockKind, tuple[str, ...]] = {
    "lead": (),
    "items": ("heading",),
    "chart": ("title", "takeaway"),
    "quote": (),
    "progress": (),
    "note": ("text",),
}


def _where(index: int, block: ComposedBlock) -> str:
    return says.BLOCK_AT.format(number=index + 1, kind=block.kind)


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
        return [says.NO_TEXT.format(where=where, name=name)]
    if len(stripped) > limit:
        return [
            says.TEXT_TOO_LONG.format(where=where, name=name, length=len(stripped), limit=limit)
        ]
    return []


def _item_problems(
    where: str, item: ComposedItem, pool: FactPool, values: SlotValues, *, leads: bool
) -> list[str]:
    at = says.ITEM_AT.format(where=where, id=item.id)
    candidate = pool.items.get(item.id)
    if candidate is None:
        return [says.NO_POOL_ITEM.format(at=at, id=item.id)]
    problems = _text_problems(at, "title", item.title, BRIEF_ITEM_TITLE_MAX_CHARS, values)
    if len(_shown(item.detail or "", values).strip()) > BRIEF_ITEM_DETAIL_MAX_CHARS:
        problems.append(says.DETAIL_TOO_LONG.format(at=at, limit=BRIEF_ITEM_DETAIL_MAX_CHARS))
    if (item.action is None) == (item.outcome is None):
        problems.append(says.ACTION_OR_OUTCOME.format(at=at))
    if candidate.outcome is not None and item.outcome is None:
        problems.append(says.LINE_GIVES_OUTCOME.format(at=at, outcome=candidate.outcome.value))
    if candidate.action is not None and item.action is None:
        problems.append(says.LINE_GIVES_ACTION.format(at=at, action=candidate.action.value))
    if candidate.is_event and not leads:
        problems.append(says.EVENT_ONLY_LEADS.format(at=at))
    return problems


def _shared_x(series: list[DataSeries]) -> bool:
    return len({tuple(p.x for p in s.points) for s in series}) == 1


def _trend_misfit(chart: ChartKind, series: list[DataSeries]) -> str | None:
    """Name why a line or spark cannot draw the series: too few days, too many lines, unshared days."""
    timed = all(s.shape is SeriesShape.TIME_SERIES for s in series)
    if not timed or min(len(s.points) for s in series) < MIN_TREND_POINTS:
        return says.TREND_TOO_SHORT.format(chart=chart, days=MIN_TREND_POINTS)
    if chart is ChartKind.SPARK and len(series) > 1:
        return says.SPARK_ONE_SERIES
    if len(series) > MAX_LINE_SERIES:
        return says.LINE_TOO_MANY_SERIES.format(limit=MAX_LINE_SERIES)
    if not _shared_x(series):
        return says.LINE_UNSHARED_DAYS
    return _single_unit_misfit(says.LINE_ONE_UNIT, series)


def _single_unit_misfit(subject: str, series: list[DataSeries]) -> str | None:
    """Name the units a chart would put on one scale; None when they are one."""
    units = {s.unit for s in series}
    if len(units) == 1:
        return None
    named = ", ".join(sorted(unit or says.NO_UNIT for unit in units))
    return says.MIXED_UNITS.format(subject=subject, units=named)


def _bar_misfit(chart: ChartKind, series: list[DataSeries]) -> str | None:
    """Name why a bar or a stack cannot draw the series: too many bars, or series that do not stack."""
    longest = max(len(s.points) for s in series)
    if longest > MAX_BAR_CATEGORIES:
        return says.TOO_MANY_BARS.format(chart=chart, limit=MAX_BAR_CATEGORIES, bars=longest)
    if chart is ChartKind.BAR:
        return None if len(series) == 1 else says.BAR_ONE_SERIES
    if len(series) < 2 or not _shared_x(series):
        return says.STACK_NEEDS_SHARED_SERIES
    return _single_unit_misfit(says.STACK_ONE_UNIT, series)


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
        problems.append(says.NO_POOL_SERIES.format(where=where, ids=", ".join(unknown)))
    if not block.series_ids:
        problems.append(says.NO_SERIES_IDS.format(where=where))
    elif not unknown:
        misfit = _CHART_MISFITS[block.chart](block.chart, [by_id[i] for i in block.series_ids])
        problems += [says.CHART_MISFIT.format(where=where, misfit=misfit)] if misfit else []
    return problems


def _lead_problems(where: str, index: int, block: ComposedLead, pool: FactPool) -> list[str]:
    problems = [] if index == 0 else [says.LEAD_NOT_FIRST.format(where=where)]
    if block.item.action is None:
        problems.append(says.LEAD_WITHOUT_ACTION.format(where=where))
    candidate = pool.items.get(block.item.id)
    if candidate is not None and not candidate.gaia_acts:
        problems.append(
            says.LEAD_GAIA_CANNOT_ACT.format(where=where, app=candidate.app, id=block.item.id)
        )
    if candidate is not None and candidate.backlog:
        problems.append(says.LEAD_IS_BACKLOG.format(where=where, id=block.item.id))
    return problems


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
        said = says.ITEM_SIDE.format(side="action" if item.action else "outcome", value=side.value)
        home = (
            says.MOVE_TO_GROUP.format(group=_a_group(belongs))
            if belongs is not None
            else says.FAILED_NEEDS_RETRY
        )
        problems.append(
            says.ITEM_IN_WRONG_GROUP.format(
                at=says.ITEM_AT.format(where=where, id=item.id),
                said=said,
                group=_a_group(block.state),
                home=home,
            )
        )
    return problems


def _a_group(state: GroupState) -> str:
    """Name a group state with its article, as a problem says it."""
    named = says.AN_STATE if state is GroupState.IN_PROGRESS else says.A_STATE
    return named.format(state=state.value)


def _own_problems(
    index: int, block: ComposedBlock, pool: FactPool, values: SlotValues
) -> list[str]:
    """Name what breaks the block's own kind of contract, its items aside."""
    where = _where(index, block)
    if isinstance(block, ComposedLead):
        return _lead_problems(where, index, block, pool)
    if isinstance(block, ComposedItems):
        heading = _text_problems(where, "heading", block.heading, BRIEF_HEADING_MAX_CHARS, values)
        return heading + _state_problems(where, block)
    if isinstance(block, ComposedChart):
        return _chart_problems(where, block, pool, values)
    if isinstance(block, ComposedQuote):
        known = block.quote_id in pool.quotes_by_id
        return [] if known else [says.NO_POOL_QUOTE.format(where=where, id=block.quote_id)]
    if isinstance(block, ComposedProgress):
        known = block.goal_id in pool.goals_by_id
        return [] if known else [says.NO_POOL_GOAL.format(where=where, id=block.goal_id)]
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


def block_problems(
    index: int, block: ComposedBlock, pool: FactPool, values: SlotValues
) -> list[str]:
    """Return what breaks one block's contract on its own: its kind's rules, its items' and its slots'."""
    alone = BriefComposition(blocks=[block])
    return _block_problems(index, block, pool, values) + _slot_problems(alone, values)


def _placed_ids(composition: BriefComposition) -> Iterator[str]:
    """Yield every id a block places, named by its kind, so a repeat is caught across kinds of block."""
    for block in composition.blocks:
        yield from (says.PLACED_ITEM.format(id=item.id) for item in placed_items(block))
        if isinstance(block, ComposedChart):
            yield from (says.PLACED_SERIES.format(id=s) for s in block.series_ids)
        if isinstance(block, ComposedQuote):
            yield says.PLACED_QUOTE.format(id=block.quote_id)
        if isinstance(block, ComposedProgress):
            yield says.PLACED_GOAL.format(id=block.goal_id)


def _budget_problems(composition: BriefComposition) -> list[str]:
    blocks = composition.blocks
    problems: list[str] = []
    items = sum(len(placed_items(b)) for b in blocks)
    if items > MAX_BRIEF_ITEMS:
        problems.append(says.TOO_MANY_ITEMS.format(count=items, limit=MAX_BRIEF_ITEMS))
    charts = sum(1 for b in blocks if b.kind == "chart")
    if charts > MAX_BRIEF_CHARTS:
        problems.append(says.TOO_MANY_CHARTS.format(count=charts, limit=MAX_BRIEF_CHARTS))
    leads = sum(1 for b in blocks if b.kind == "lead")
    if leads > 1:
        problems.append(says.TOO_MANY_LEADS.format(count=leads))
    return problems


def _slot_problems(composition: BriefComposition, values: SlotValues) -> list[str]:
    problems: list[str] = []
    for index, block in enumerate(composition.blocks):
        where = _where(index, block)
        for name in WRITTEN_FIELDS[block.kind]:
            text = getattr(block, name)
            if text:
                problems += slot_problems(
                    says.BLOCK_FIELD.format(where=where, name=name), text, values
                )
        for item in placed_items(block):
            for name, text in (("title", item.title), ("detail", item.detail)):
                if text:
                    problems += slot_problems(
                        says.ITEM_FIELD.format(where=where, id=item.id, name=name),
                        text,
                        values,
                        may_quote_figures=True,
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
        problems.append(says.PLACED_TWICE.format(ids=", ".join(repeated)))
    return problems + _budget_problems(composition) + _slot_problems(composition, values)
