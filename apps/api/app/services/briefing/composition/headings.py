"""Judge each group heading against the items under it: every item must satisfy its heading.

One structured call reads every group's heading beside each item's title, state and action
or outcome; tone and register never count. A heading untrue of any item, or one the check
never judged, is sent back to the composition named, like any other broken part of it.
"""

from datetime import datetime

from pydantic import BaseModel, Field

from app.agents.llm.client import StructuredCallOptions, ainvoke_structured, metered_config
from app.agents.prompts.brief_heading_prompts import BRIEF_HEADING_PROMPT, NOT_NEW
from app.agents.prompts.briefing_prompts import UNTRUSTED_DATA_NOTE
from app.constants.briefing import BRIEF_HEADING_CHECK_LABEL, BRIEF_HEADING_CHECK_TEMPERATURE
from app.models.brief_candidate_models import BriefCandidate
from app.models.brief_composition_models import BriefComposition, ComposedItems
from app.services.briefing.fact_pool.pool import FactPool
from app.services.hil.utils import untrusted_fence
from app.utils.timezone import as_utc
from shared.py.wide_events import log

_JUDGING = StructuredCallOptions(temperature=BRIEF_HEADING_CHECK_TEMPERATURE, schema_held=True)


class HeadingVerdict(BaseModel):
    """Whether one group's heading is true of every item under it."""

    # The verdict comes last so the model reasons before it commits (it once contradicted its why).
    block: int = Field(description="The group's block number, as listed")
    why: str = Field(description="Why, in a few words")
    misfits: list[int] = Field(description="The ids of the items the heading is not true of")
    fits: bool


class HeadingVerdicts(BaseModel):
    """The check's answer: one verdict per group."""

    verdicts: list[HeadingVerdict]


def _groups(composition: BriefComposition) -> dict[int, ComposedItems]:
    return {
        index + 1: block
        for index, block in enumerate(composition.blocks)
        if isinstance(block, ComposedItems)
    }


def _not_new(candidate: BriefCandidate, since: datetime) -> bool:
    """Whether an earlier brief saw it, or the app made it before the last brief: nothing new."""
    signal = candidate.signal
    created = as_utc(signal.created_at) if signal is not None else None
    return candidate.is_known or (created is not None and created < since)


def _group_lines(number: int, group: ComposedItems, pool: FactPool) -> str:
    lines = [f'block {number}, heading "{group.heading}", state {group.state.value}:']
    for item in group.items:
        candidate = pool.items[item.id]
        said = item.action or item.outcome
        side = f"{'action' if item.action else 'outcome'} {said.value}" if said else "neither"
        known = f" | {NOT_NEW}" if _not_new(candidate, pool.context.done_since) else ""
        lines.append(
            f"- item {item.id}: {item.title} | {candidate.state.label.lower()} | {side}{known}"
        )
    return "\n".join(lines)


async def _verdicts(
    user_id: str, groups: dict[int, ComposedItems], pool: FactPool
) -> dict[int, HeadingVerdict]:
    """Ask the model to judge these groups; return its verdict for each group it judged."""
    fence = untrusted_fence()
    answer = await ainvoke_structured(
        HeadingVerdicts,
        BRIEF_HEADING_PROMPT.format(
            untrusted=UNTRUSTED_DATA_NOTE.format(fence=fence),
            fence=fence,
            not_new=NOT_NEW,
            groups="\n\n".join(_group_lines(n, g, pool) for n, g in groups.items()),
        ),
        label=BRIEF_HEADING_CHECK_LABEL,
        config=metered_config(user_id),
        options=_JUDGING,
    )
    return {v.block: v for v in answer.verdicts if v.block in groups}


async def heading_problems(
    user_id: str, composition: BriefComposition, pool: FactPool
) -> dict[int, str]:
    """Name each heading of the rendered composition untrue of an item under it, by its block number from 1.

    A group the check leaves out is asked about once more alone; one still unjudged is named as
    unchecked, so it is rejected like an untrue one rather than shown unread.
    """
    groups = _groups(composition)
    if not groups:
        return {}
    verdicts = await _verdicts(user_id, groups, pool)
    unjudged = {n: g for n, g in groups.items() if n not in verdicts}
    if unjudged:
        verdicts |= await _verdicts(user_id, unjudged, pool)
        log.warning(
            "briefing.heading_check_unjudged",
            blocks=sorted(unjudged),
            still_unjudged=sorted(set(unjudged) - set(verdicts)),
        )
    return {
        n: _problem(n, group, verdict, pool)
        for n, group in groups.items()
        if (verdict := verdicts.get(n)) is None or not verdict.fits
    }


def _problem(n: int, group: ComposedItems, verdict: HeadingVerdict | None, pool: FactPool) -> str:
    """Say what is wrong with a group's heading: unchecked, or untrue of the items it names."""
    rename = f"every item's act ({_acts(group)})"
    if verdict is None:
        return (
            f'block {n} heading "{group.heading}" went unchecked against its items; head this '
            f"group with words true of {rename}"
        )
    return (
        f'block {n} heading "{group.heading}" is not true of '
        f"{_misfits(group, verdict.misfits, pool) or 'its items'}: {verdict.why}; move them "
        f"under a heading true of what they are, or rename this group to one true of {rename}"
    )


def _acts(group: ComposedItems) -> str:
    """Name each act or outcome the group's items carry, once, so a rename covers them all."""
    said = (item.action or item.outcome for item in group.items)
    return ", ".join(dict.fromkeys(s.value for s in said if s is not None)) or "none"


def _misfits(group: ComposedItems, ids: list[int], pool: FactPool) -> str:
    """Name each misfit item with what it is, so the retry knows where it belongs."""
    named = []
    for item in group.items:
        if item.id in ids:
            state = pool.items[item.id].state.label.lower()
            said = item.action or item.outcome
            named.append(f"item {item.id} ({state}{f', {said.value}' if said else ''})")
    return ", ".join(named)
