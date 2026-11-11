"""Judge each group heading against the items under it: every item must satisfy its heading.

One structured call reads every group's heading beside each item's title, state and action
or outcome; tone and register never count. A heading untrue of any item is sent back to the
composition named, like any other broken part of it.
"""

from pydantic import BaseModel, Field

from app.agents.llm.client import StructuredCallOptions, ainvoke_structured, metered_config
from app.agents.prompts.brief_heading_prompts import BRIEF_HEADING_PROMPT
from app.constants.briefing import BRIEF_HEADING_CHECK_LABEL, BRIEF_HEADING_CHECK_TEMPERATURE
from app.models.brief_composition_models import BriefComposition, ComposedItems
from app.models.briefing_models import BRIEFING_ITEM_STATES
from app.services.briefing.fact_pool.pool import FactPool
from app.utils.errors import AppError

_JUDGING = StructuredCallOptions(temperature=BRIEF_HEADING_CHECK_TEMPERATURE, schema_held=True)


class HeadingVerdict(BaseModel):
    """Whether one group's heading is true of every item under it."""

    block: int = Field(description="The group's block number, as listed")
    fits: bool
    misfits: list[int] = Field(description="The ids of the items the heading is not true of")
    why: str = Field(description="Why, in a few words")


class HeadingVerdicts(BaseModel):
    """The check's answer: one verdict per group."""

    verdicts: list[HeadingVerdict]


def _groups(composition: BriefComposition) -> dict[int, ComposedItems]:
    return {
        index + 1: block
        for index, block in enumerate(composition.blocks)
        if isinstance(block, ComposedItems)
    }


def _group_lines(number: int, group: ComposedItems, pool: FactPool) -> str:
    lines = [f'block {number}, heading "{group.heading}", state {group.state.value}:']
    for item in group.items:
        state = BRIEFING_ITEM_STATES[pool.items[item.id].state].lower()
        said = item.action or item.outcome
        side = f"{'action' if item.action else 'outcome'} {said.value}" if said else "neither"
        lines.append(f"- item {item.id}: {item.title} | {state} | {side}")
    return "\n".join(lines)


async def heading_problems(
    user_id: str, composition: BriefComposition, pool: FactPool
) -> list[str]:
    """Name each heading of the rendered composition that is untrue of an item under it.

    Raises AppError when the check leaves a group unjudged: a heading nobody read is not shown.
    """
    groups = _groups(composition)
    if not groups:
        return []
    answer = await ainvoke_structured(
        HeadingVerdicts,
        BRIEF_HEADING_PROMPT.format(
            groups="\n\n".join(_group_lines(n, g, pool) for n, g in groups.items())
        ),
        label=BRIEF_HEADING_CHECK_LABEL,
        config=metered_config(user_id),
        options=_JUDGING,
    )
    verdicts = {v.block: v for v in answer.verdicts if v.block in groups}
    unjudged = sorted(set(groups) - set(verdicts))
    if unjudged:
        raise AppError(
            message="the brief's heading check left a group unjudged",
            why=f"no verdict for block(s) {unjudged}",
            fix="the next scheduled brief retries; a heading nobody checked is never shown",
            meta={"answer": answer.model_dump()},
        )
    return [
        f'block {n} heading "{groups[n].heading}" is not true of '
        f"{_misfits(groups[n], v.misfits, pool) or 'its items'}: {v.why}; move "
        "them under a heading true of what they are, or rename this group"
        for n, v in sorted(verdicts.items())
        if not v.fits
    ]


def _misfits(group: ComposedItems, ids: list[int], pool: FactPool) -> str:
    """Name each misfit item with what it is, so the retry knows where it belongs."""
    named = []
    for item in group.items:
        if item.id in ids:
            state = BRIEFING_ITEM_STATES[pool.items[item.id].state].lower()
            said = item.action or item.outcome
            named.append(f"item {item.id} ({state}{f', {said.value}' if said else ''})")
    return ", ".join(named)
