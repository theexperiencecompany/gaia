"""Hold a composition to what code can enforce, and salvage a correct brief when the model never does.

Code fixes what it can decide alone (an id twice or unknown, a producer's action or outcome, the
page budget by the composition's own order); a block that still breaks its contract after the
retry is dropped, a misfit heading gives way to one code derives from the group's state, and a
composition with nothing left is built from the pool. The user always gets a correct brief.
"""

from app.constants.briefing import (
    BRIEF_ITEM_TITLE_MAX_CHARS,
    MAX_BRIEF_CHARTS,
    MAX_BRIEF_ITEMS,
    MAX_ITEMS_PER_BLOCK,
    BriefAction,
    BriefOutcome,
)
from app.models.brief_candidate_models import BriefCandidate
from app.models.brief_composition_models import (
    BriefComposition,
    ComposedBlock,
    ComposedItem,
    ComposedItems,
    ComposedLead,
    GroupState,
)
from app.models.briefing_models import BriefingItemKind
from app.services.briefing.composition.checks import block_problems
from app.services.briefing.fact_pool.pool import FactPool
from app.services.briefing.slots import SlotValues

#: The heading a group falls back to when the model's is untrue of its items.
FALLBACK_HEADINGS: dict[GroupState, str] = {
    GroupState.NEEDS_YOU: "Needs you",
    GroupState.DONE: "Done",
    GroupState.IN_PROGRESS: "Still in progress",
}
_ELLIPSIS = "…"
#: The outcome an item gets when its producer named none: done work finished, the rest changed.
_UNSAID_OUTCOMES: dict[BriefingItemKind, BriefOutcome] = {
    "lookback": BriefOutcome.FINISHED,
    "gaia": BriefOutcome.STARTED,
    "note": BriefOutcome.CHANGED,
    "you": BriefOutcome.CHANGED,
    "failed": BriefOutcome.CHANGED,
}


def _sided(item: ComposedItem, candidate: BriefCandidate) -> ComposedItem:
    """Give the item its producer's action or outcome, when the producer named one."""
    if candidate.action is not None:
        return item.model_copy(update={"action": candidate.action, "outcome": None})
    if candidate.outcome is not None:
        return item.model_copy(update={"action": None, "outcome": candidate.outcome})
    return item


def _shared_state(items: list[ComposedItem]) -> GroupState | None:
    """Return the one state every item's action or outcome puts it in; None when they differ."""
    states = {
        GroupState.NEEDS_YOU
        if i.action is not None
        else GroupState.IN_PROGRESS
        if i.outcome is BriefOutcome.STARTED
        else GroupState.DONE
        for i in items
    }
    return states.pop() if len(states) == 1 else None


def repaired(composition: BriefComposition, pool: FactPool) -> BriefComposition:
    """Enforce what code decides alone: known ids once each, producers' sides, one lead, the budget."""
    seen: set[int] = set()
    left = MAX_BRIEF_ITEMS
    charts = 0
    blocks: list[ComposedBlock] = []
    for block in composition.blocks:
        if isinstance(block, ComposedLead):
            candidate = pool.items.get(block.item.id)
            if blocks or candidate is None:
                continue
            seen.add(block.item.id)
            left -= 1
            blocks.append(block.model_copy(update={"item": _sided(block.item, candidate)}))
        elif isinstance(block, ComposedItems):
            items: list[ComposedItem] = []
            for item in block.items:
                candidate = pool.items.get(item.id)
                if candidate is None or item.id in seen or len(items) >= left:
                    continue
                seen.add(item.id)
                items.append(_sided(item, candidate))
            if not items:
                continue
            left -= len(items)
            state = _shared_state(items) or block.state
            blocks.append(block.model_copy(update={"items": items, "state": state}))
        elif block.kind == "chart":
            charts += 1
            if charts <= MAX_BRIEF_CHARTS:
                blocks.append(block)
        else:
            blocks.append(block)
    return BriefComposition(blocks=blocks)


def _as_group(lead: ComposedLead) -> ComposedItems:
    """Turn a lead that cannot stand into a one-item group: the item still matters."""
    return ComposedItems(
        kind="items",
        state=GroupState.NEEDS_YOU,
        heading=FALLBACK_HEADINGS[GroupState.NEEDS_YOU],
        items=[lead.item],
    )


def _sound(
    index: int, block: ComposedBlock, pool: FactPool, values: SlotValues
) -> ComposedBlock | None:
    """Return the block once it holds its contract, its heading or its lead given way if need be; else None."""
    if not block_problems(index, block, pool, values):
        return block
    if isinstance(block, ComposedLead):
        block = _as_group(block)
    if isinstance(block, ComposedItems):
        block = block.model_copy(update={"heading": FALLBACK_HEADINGS[block.state]})
        items = [
            item
            for item in block.items
            if not block_problems(index, block.model_copy(update={"items": [item]}), pool, values)
        ]
        if items:
            fixed = block.model_copy(update={"items": items})
            if not block_problems(index, fixed, pool, values):
                return fixed
    return None


def salvaged(composition: BriefComposition, pool: FactPool, values: SlotValues) -> BriefComposition:
    """Keep every block of the composition that holds its contract; build from the pool if none does."""
    kept: list[ComposedBlock] = []
    for block in repaired(composition, pool).blocks:
        if (sound := _sound(len(kept), block, pool, values)) is not None:
            kept.append(sound)
    if kept:
        return BriefComposition(blocks=kept)
    return pool_composition(pool, values)


def _short(title: str) -> str:
    if len(title) <= BRIEF_ITEM_TITLE_MAX_CHARS:
        return title
    cut = title[: BRIEF_ITEM_TITLE_MAX_CHARS - len(_ELLIPSIS)].rsplit(" ", 1)[0]
    return f"{cut}{_ELLIPSIS}"


def _placed(item_id: int, candidate: BriefCandidate) -> ComposedItem:
    asks = candidate.state in ("you", "failed")
    return ComposedItem(
        id=item_id,
        action=(candidate.action or BriefAction.REVIEW) if asks else None,
        outcome=None if asks else (candidate.outcome or _UNSAID_OUTCOMES[candidate.state]),
        title=_short(candidate.title),
        detail=None,
    )


def pool_composition(pool: FactPool, values: SlotValues) -> BriefComposition:
    """Build a plain brief from the pool's news, one group per state, each in pool order."""
    by_state: dict[GroupState, list[ComposedItem]] = {state: [] for state in GroupState}
    for item_id, candidate in pool.items.items():
        if candidate.is_news:
            placed = _placed(item_id, candidate)
            by_state[_shared_state([placed]) or GroupState.DONE].append(placed)
    groups: list[ComposedBlock] = [
        ComposedItems(
            kind="items",
            state=state,
            heading=FALLBACK_HEADINGS[state],
            items=items[:MAX_ITEMS_PER_BLOCK],
        )
        for state, items in by_state.items()
        if items
    ]
    composed = repaired(BriefComposition(blocks=groups), pool)
    return BriefComposition(
        blocks=[b for i, b in enumerate(composed.blocks) if not block_problems(i, b, pool, values)]
    )
