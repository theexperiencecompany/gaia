"""Compose a brief over its fact pool in one structured call, held to the pool.

A composition that breaks its contract, or heads a group with words untrue of its items,
is sent back once with every problem named; past the last attempt code salvages what holds
of it (the checked-call policy, briefing.checked_call).
"""

from collections.abc import Collection
from dataclasses import dataclass

from app.agents.prompts.brief_composition_prompts import COMPOSITION_RETRY_NOTE
from app.agents.prompts.brief_fact_prompts import (
    EMPTY_DIGEST,
    NO_WHOLE_COMPOSITION,
    UNREADABLE_COMPOSITION,
)
from app.constants.briefing import BRIEF_COMPOSITION_LABEL, MAX_COMPOSITION_ATTEMPTS
from app.models.brief_composition_models import (
    BriefComposition,
    ComposedBlock,
    ComposedItem,
    ComposedItems,
    ComposedLead,
)
from app.services.briefing.checked_call import CheckedCall, Rejected, checked_structured_call
from app.services.briefing.composition.checks import WRITTEN_FIELDS, composition_problems
from app.services.briefing.composition.headings import heading_problems
from app.services.briefing.composition.prompt import composition_prompt
from app.services.briefing.composition.repair import headed, repaired, salvaged
from app.services.briefing.fact_pool.pool import FactPool
from app.services.briefing.fact_pool.render import pool_block
from app.services.briefing.kinds import BriefKindSpec
from app.services.briefing.slots import (
    SlotValues,
    candidate_fact,
    render_slots,
    series_figures,
)


@dataclass(frozen=True)
class Composed:
    """The checked composition as written, the same with every slot filled, and what its slots render."""

    written: BriefComposition
    rendered: BriefComposition
    values: SlotValues


def pool_values(pool: FactPool) -> SlotValues:
    """Return what a composition's slots render and its claims are held to: each item's line, each series' figures."""
    clock = pool.context.clock
    linked = {title for goal in pool.goals for title in goal.linked}
    return SlotValues(
        facts={
            i: candidate_fact(
                c,
                clock,
                words=" ".join(w for w in (c.standing, c.detail) if w) or None,
                goal_work=c.todo_id is not None and c.title in linked,
            )
            for i, c in pool.items.items()
        },
        counts={},
        series={s.id: series_figures(s) for s in pool.series},
    )


def _filled_item(item: ComposedItem, values: SlotValues) -> ComposedItem:
    return item.model_copy(
        update={
            name: render_slots(text, values, {})
            for name in ("title", "detail")
            if (text := getattr(item, name))
        }
    )


def _filled(block: ComposedBlock, values: SlotValues) -> ComposedBlock:
    update: dict[str, object] = {
        name: render_slots(text, values, {})
        for name in WRITTEN_FIELDS[block.kind]
        if (text := getattr(block, name))
    }
    if isinstance(block, ComposedLead):
        update["item"] = _filled_item(block.item, values)
    if isinstance(block, ComposedItems):
        update["items"] = [_filled_item(item, values) for item in block.items]
    return block.model_copy(update=update)


def rendered(composition: BriefComposition, values: SlotValues) -> BriefComposition:
    """Fill every slot the composition wrote."""
    return BriefComposition(blocks=[_filled(b, values) for b in composition.blocks])


def _contract_problems(
    answer: BriefComposition, pool: FactPool, values: SlotValues, must_place: bool
) -> list[str]:
    if must_place and not answer.blocks:
        return [EMPTY_DIGEST]
    return composition_problems(answer, pool, values)


def _groups(composition: BriefComposition) -> list[int]:
    """Return the block number, from 1, of every group in the composition."""
    return [n for n, b in enumerate(composition.blocks, start=1) if isinstance(b, ComposedItems)]


def _unreadable_note(problems: list[str], _reply: str) -> str:
    return COMPOSITION_RETRY_NOTE.format(
        problems=UNREADABLE_COMPOSITION.format(problems="; ".join(problems)),
        last=NO_WHOLE_COMPOSITION,
    )


async def compose_brief(user_id: str, pool: FactPool, spec: BriefKindSpec) -> Composed:
    """Compose the brief over the pool; a pool with nothing but the calendar needs no call."""
    values = pool_values(pool)
    if not pool.composable:
        empty = BriefComposition(blocks=[])
        return Composed(written=empty, rendered=empty, values=values)

    def done(answer: BriefComposition) -> Composed:
        return Composed(written=answer, rendered=rendered(answer, values), values=values)

    async def held(answer: BriefComposition) -> Composed | Rejected[BriefComposition]:
        """Check the contract, then every heading; what a salvage keeps shows only headings that passed."""
        kept = repaired(answer, pool)
        problems = _contract_problems(kept, pool, values, spec.must_place)
        # A contract break leaves every heading unjudged, so each gives way to its derived one.
        misfits: Collection[int] = _groups(kept)
        if not problems:
            untrue = await heading_problems(user_id, rendered(kept, values), pool)
            if not untrue:
                return done(kept)
            problems, misfits = list(untrue.values()), untrue.keys()
        note = COMPOSITION_RETRY_NOTE.format(
            problems="; ".join(problems), last=kept.model_dump_json()
        )
        return Rejected(problems, note, headed(kept, pool, misfits))

    return await checked_structured_call(
        user_id,
        composition_prompt(pool, spec.frame, pool_block(pool)),
        CheckedCall(
            name="composition",
            schema=BriefComposition,
            label=BRIEF_COMPOSITION_LABEL,
            attempts=MAX_COMPOSITION_ATTEMPTS,
            check=held,
            unreadable=_unreadable_note,
            salvage=lambda last: done(salvaged(last or BriefComposition(blocks=[]), pool, values)),
        ),
    )
