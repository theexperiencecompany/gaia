"""Hold a composition to what code can enforce, and salvage a correct brief when the model never does.

Code fixes what it can decide alone (an id twice or unknown, a second item titled as an earlier
one, two groups of one state under one heading, a producer's action or outcome, the page budget
by the composition's own order); a block that still breaks its contract after the
retry is dropped, a misfit heading gives way to one code derives from what the group's items share, and a
composition with nothing left is built from the pool. The user always gets a correct brief.
"""

from collections.abc import Callable, Collection

from app.constants.briefing import (
    ACTION_HEADINGS,
    BACKLOG_HEADING,
    BRIEF_HEADING_MAX_CHARS,
    BRIEF_ITEM_TITLE_MAX_CHARS,
    GAIA_APP_NAME,
    MAX_BRIEF_CHARTS,
    MAX_BRIEF_ITEMS,
    MAX_ITEMS_PER_BLOCK,
    BriefAction,
    BriefOutcome,
)
from app.models.brief_candidate_models import BriefCandidate, CandidateOrigin
from app.models.brief_composition_models import (
    BriefComposition,
    ComposedBlock,
    ComposedItem,
    ComposedItems,
    ComposedLead,
)
from app.models.brief_item_models import GroupState
from app.services.briefing.candidates.subjects import same_text_key
from app.services.briefing.composition.checks import block_problems
from app.services.briefing.fact_pool.pool import FactPool
from app.services.briefing.slots import SlotValues

_ELLIPSIS = "…"


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


def _owed(pool: FactPool) -> list[int]:
    """Return the pending approvals no brief has shown, in pool order, as many as a brief holds."""
    return [
        item_id
        for item_id, candidate in pool.items.items()
        if candidate.origin is CandidateOrigin.APPROVAL and candidate.is_news
    ][:MAX_BRIEF_ITEMS]


def derived_heading(group: ComposedItems, pool: FactPool) -> str:
    """Head a group by what its items share: the user's own list, one act, one app, else its state.

    One item shares only its act: an app heading over a lone item says nothing its row does not.
    """
    candidates = [pool.items[item.id] for item in group.items if item.id in pool.items]
    if candidates and all(c.backlog for c in candidates):
        return BACKLOG_HEADING
    actions = {item.action for item in group.items}
    if len(actions) == 1 and (action := actions.pop()) is not None:
        return ACTION_HEADINGS[action]
    apps = {c.app for c in candidates}
    # GAIA's own items are its todos and work, which no app name tells apart.
    if len(apps) != 1 or len(candidates) < 2 or GAIA_APP_NAME in apps:
        return group.state.fallback_heading
    in_app = f"{group.state.fallback_heading} in {apps.pop()}"
    return in_app if len(in_app) <= BRIEF_HEADING_MAX_CHARS else group.state.fallback_heading


def headed(
    composition: BriefComposition, pool: FactPool, misfits: Collection[int]
) -> BriefComposition:
    """Give each misfit group, by block number from 1, the heading derived from its items."""
    return BriefComposition(
        blocks=[
            b.model_copy(update={"heading": derived_heading(b, pool)})
            if isinstance(b, ComposedItems) and n in misfits
            else b
            for n, b in enumerate(composition.blocks, start=1)
        ]
    )


def _derived(group: ComposedItems, pool: FactPool) -> ComposedItems:
    return group.model_copy(update={"heading": derived_heading(group, pool)})


def _with_owed(
    blocks: list[ComposedBlock], owed: list[ComposedItem], pool: FactPool
) -> list[ComposedBlock]:
    """Place the owed approvals in groups of their own, right after what already asks the user."""
    asks = [
        i
        for i, b in enumerate(blocks)
        if isinstance(b, ComposedLead)
        or (isinstance(b, ComposedItems) and b.state is GroupState.NEEDS_YOU)
    ]
    at = asks[-1] + 1 if asks else 0
    groups: list[ComposedBlock] = [
        _derived(
            ComposedItems(
                kind="items",
                state=GroupState.NEEDS_YOU,
                heading=GroupState.NEEDS_YOU.fallback_heading,
                items=owed[start : start + MAX_ITEMS_PER_BLOCK],
            ),
            pool,
        )
        for start in range(0, len(owed), MAX_ITEMS_PER_BLOCK)
    ]
    return blocks[:at] + groups + blocks[at:]


def _kept(
    items: list[ComposedItem],
    pool: FactPool,
    said: tuple[set[int], set[str]],
    fits: Callable[[int], bool],
) -> list[ComposedItem]:
    """Keep a group's items not yet said by id or title that fit the page; said grows with them.

    An item dropped for its title counts as said, so an owed approval among them is not owed again.
    """
    seen, titles = said
    kept: list[ComposedItem] = []
    for item in items:
        candidate = pool.items.get(item.id)
        title = same_text_key(item.title)
        if title in titles:
            seen.add(item.id)
            continue
        if candidate is None or item.id in seen or not fits(item.id):
            continue
        seen.add(item.id)
        titles.add(title)
        kept.append(_sided(item, candidate))
    return kept


def _merged_into_earlier(blocks: list[ComposedBlock], group: ComposedItems) -> bool:
    """Fold the group into an earlier one of its state under its heading, room allowing; False if none."""
    heading = same_text_key(group.heading)
    for at, block in enumerate(blocks):
        if (
            isinstance(block, ComposedItems)
            and block.state is group.state
            and same_text_key(block.heading) == heading
            and len(block.items) + len(group.items) <= MAX_ITEMS_PER_BLOCK
        ):
            blocks[at] = block.model_copy(update={"items": [*block.items, *group.items]})
            return True
    return False


def repaired(composition: BriefComposition, pool: FactPool) -> BriefComposition:
    """Enforce what code decides alone: known ids and titles once each, one group per heading, producers' sides, one lead, the budget.

    A pending approval no brief has shown always has its place: the composer's choice is
    what else fills the page.
    """
    seen: set[int] = set()
    # Two items the composer titles alike are one subject to the reader, even from two todos.
    titles: set[str] = set()
    owed = _owed(pool)
    left = MAX_BRIEF_ITEMS - len(owed)
    charts = 0
    blocks: list[ComposedBlock] = []

    def fits(item_id: int) -> bool:
        nonlocal left
        if item_id in owed:
            return True
        left -= 1
        return left >= 0

    for block in composition.blocks:
        if isinstance(block, ComposedLead):
            candidate = pool.items.get(block.item.id)
            if blocks or candidate is None or not fits(block.item.id):
                continue
            seen.add(block.item.id)
            titles.add(same_text_key(block.item.title))
            blocks.append(block.model_copy(update={"item": _sided(block.item, candidate)}))
        elif isinstance(block, ComposedItems):
            items = _kept(block.items, pool, (seen, titles), fits)
            if not items:
                continue
            state = _shared_state(items) or block.state
            group = block.model_copy(update={"items": items, "state": state})
            if not _merged_into_earlier(blocks, group):
                blocks.append(group)
        elif block.kind == "chart":
            charts += 1
            if charts <= MAX_BRIEF_CHARTS:
                blocks.append(block)
        else:
            blocks.append(block)
    missing = [_placed(i, pool.items[i]) for i in owed if i not in seen]
    return BriefComposition(blocks=_with_owed(blocks, missing, pool) if missing else blocks)


def _as_group(lead: ComposedLead) -> ComposedItems:
    """Turn a lead that cannot stand into a one-item group: the item still matters."""
    return ComposedItems(
        kind="items",
        state=GroupState.NEEDS_YOU,
        heading=GroupState.NEEDS_YOU.fallback_heading,
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
        block = block.model_copy(update={"heading": block.state.fallback_heading})
        items = [
            item
            for item in block.items
            if not block_problems(index, block.model_copy(update={"items": [item]}), pool, values)
        ]
        if items:
            fixed = _derived(block.model_copy(update={"items": items}), pool)
            if not block_problems(index, fixed, pool, values):
                return fixed
    return None


def salvaged(composition: BriefComposition, pool: FactPool, values: SlotValues) -> BriefComposition:
    """Keep every block of the composition that holds its contract; build from the pool if none does."""
    kept: list[ComposedBlock] = []
    for block in repaired(composition, pool).blocks:
        sound = _sound(len(kept), block, pool, values)
        if isinstance(sound, ComposedItems) and _merged_into_earlier(kept, sound):
            continue
        if sound is not None:
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
    asks = candidate.state.needs_you
    return ComposedItem(
        id=item_id,
        action=(candidate.action or BriefAction.REVIEW) if asks else None,
        outcome=None if asks else (candidate.outcome or candidate.state.unsaid_outcome),
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
        _derived(
            ComposedItems(
                kind="items",
                state=state,
                heading=state.fallback_heading,
                items=items[:MAX_ITEMS_PER_BLOCK],
            ),
            pool,
        )
        for state, items in by_state.items()
        if items
    ]
    composed = repaired(BriefComposition(blocks=groups), pool)
    return BriefComposition(
        blocks=[b for i, b in enumerate(composed.blocks) if not block_problems(i, b, pool, values)]
    )
