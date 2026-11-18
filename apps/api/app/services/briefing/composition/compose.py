"""Compose a brief over its fact pool in one structured call, held to the pool.

A composition that breaks its contract, or heads a group with words untrue of its items,
is sent back once with every problem named; past the last attempt code salvages what holds
of it (the checked-call policy, briefing.checked_call).
"""

from dataclasses import dataclass

from app.agents.prompts.brief_composition_prompts import COMPOSITION_RETRY_NOTE
from app.constants.briefing import BRIEF_COMPOSITION_LABEL, MAX_COMPOSITION_ATTEMPTS
from app.models.brief_composition_models import (
    BriefComposition,
    ComposedBlock,
    ComposedItem,
    ComposedItems,
    ComposedLead,
)
from app.services.briefing.checked_call import CheckedCall, Rejected, checked_structured_call
from app.services.briefing.clock import due_on
from app.services.briefing.composition.checks import WRITTEN_FIELDS, composition_problems
from app.services.briefing.composition.headings import heading_problems
from app.services.briefing.composition.prompt import composition_prompt
from app.services.briefing.composition.repair import repaired, salvaged
from app.services.briefing.fact_pool.pool import FactPool
from app.services.briefing.fact_pool.render import pool_block
from app.services.briefing.kinds import BriefKindSpec
from app.services.briefing.slots import BriefFact, SlotValues, render_slots, series_figures


@dataclass(frozen=True)
class Composed:
    """The checked composition as written, the same with every slot filled, and what its slots render."""

    written: BriefComposition
    rendered: BriefComposition
    values: SlotValues


def pool_values(pool: FactPool) -> SlotValues:
    """Return what a composition's slots render: each item's title and due date, each series' figures."""
    clock = pool.context.clock
    return SlotValues(
        facts={
            i: BriefFact(
                title=c.title,
                time=c.time or (due_on(c.due_at, clock) if c.due_at is not None else None),
                count=c.count,
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


#: A digest that places nothing recaps nothing; a daily may leave its whole pool out as noise.
_EMPTY_DIGEST = (
    "a weekly digest recaps the week: place what its pool holds of it (what got done, "
    "its series, each goal's progress, even a stalled one) instead of nothing"
)


async def _problems(
    user_id: str, answer: BriefComposition, pool: FactPool, values: SlotValues, must_place: bool
) -> list[str]:
    """Return the contract's problems, else every heading untrue of its items."""
    if must_place and not answer.blocks:
        return [_EMPTY_DIGEST]
    return composition_problems(answer, pool, values) or list(
        (await heading_problems(user_id, rendered(answer, values), pool)).values()
    )


def _salvaged(
    answer: BriefComposition | None, pool: FactPool, values: SlotValues
) -> BriefComposition:
    """Keep what holds of the last answer, else build from the pool; every group heads by its state.

    A salvage asks no model, so no heading the check never passed is shown: each group takes
    the heading code derives from its state.
    """
    kept = salvaged(answer or BriefComposition(blocks=[]), pool, values)
    return BriefComposition(
        blocks=[
            b.model_copy(update={"heading": b.state.fallback_heading})
            if isinstance(b, ComposedItems)
            else b
            for b in kept.blocks
        ]
    )


def _unreadable_note(problems: list[str], _reply: str) -> str:
    return COMPOSITION_RETRY_NOTE.format(
        problems=f"the answer was not a whole BriefComposition tool call ({'; '.join(problems)})",
        last="(no whole composition)",
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
        kept = repaired(answer, pool)
        problems = await _problems(user_id, kept, pool, values, spec.must_place)
        if not problems:
            return done(kept)
        note = COMPOSITION_RETRY_NOTE.format(
            problems="; ".join(problems), last=kept.model_dump_json()
        )
        return Rejected(problems, note, kept)

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
            salvage=lambda last: done(_salvaged(last, pool, values)),
        ),
    )
