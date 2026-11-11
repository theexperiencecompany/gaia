"""Compose a brief over its fact pool in one structured call, held to the pool and to the truth.

A composition that breaks its contract, or whose words claim what the pool does not hold,
is sent back once with every problem named; a second failure fails the run loud, before
anything is stored or sent.
"""

from collections.abc import Iterator
from dataclasses import dataclass

from app.agents.llm.client import ainvoke_structured, metered_config
from app.agents.llm.exceptions import MalformedStructuredOutputError
from app.agents.prompts.brief_composition_prompts import COMPOSITION_RETRY_NOTE
from app.constants.briefing import BRIEF_COMPOSITION_LABEL, MAX_COMPOSITION_ATTEMPTS
from app.models.brief_composition_models import BriefComposition, ComposedBlock, ComposedItem
from app.models.briefing_models import BriefingKind
from app.services.briefing.composition.checks import (
    ITEM_BLOCKS,
    WRITTEN_FIELDS,
    composition_problems,
)
from app.services.briefing.composition.prompt import composition_prompt
from app.services.briefing.fact_pool.pool import FactPool
from app.services.briefing.fact_pool.render import context_block, pool_block
from app.services.briefing.faithfulness import CheckedProse, unsupported_claims
from app.services.briefing.slots import BriefFact, SlotValues, render_slots, series_figures
from app.utils.errors import AppError
from shared.py.wide_events import log

# What GAIA offers to do claims nothing about the facts, so the truth check never reads it.
_PROPOSALS = frozenset({"offer"})


@dataclass(frozen=True)
class Composed:
    """The checked composition as written, the same with every slot filled, and what its slots render."""

    written: BriefComposition
    rendered: BriefComposition
    values: SlotValues


def pool_values(pool: FactPool) -> SlotValues:
    """Return what a composition's slots render: each item's title and due date, each series' figures."""
    return SlotValues(
        facts={
            i: BriefFact(
                title=c.title,
                time=c.time or (c.due_at.strftime("%a %b %-d") if c.due_at is not None else None),
                count=c.count,
            )
            for i, c in pool.items.items()
        },
        counts={},
        series={s.id: series_figures(s) for s in pool.series},
    )


def _filled_item(item: ComposedItem, values: SlotValues, *, mark: bool) -> ComposedItem:
    return item.model_copy(
        update={
            name: render_slots(text, values, {}, mark_filled=mark)
            for name in ("title", "detail")
            if (text := getattr(item, name))
        }
    )


def _filled(block: ComposedBlock, values: SlotValues, *, mark: bool) -> ComposedBlock:
    return block.model_copy(
        update={
            **{
                name: render_slots(text, values, {}, mark_filled=mark)
                for name in WRITTEN_FIELDS[block.kind]
                if (text := getattr(block, name))
            },
            "items": [_filled_item(item, values, mark=mark) for item in block.items],
        }
    )


def rendered(
    composition: BriefComposition, values: SlotValues, *, mark: bool = False
) -> BriefComposition:
    """Fill every slot the composition wrote; mark brackets each filled value for the check."""
    return BriefComposition(blocks=[_filled(b, values, mark=mark) for b in composition.blocks])


def _written_text(composition: BriefComposition) -> Iterator[tuple[str, str]]:
    """Yield every string the composition wrote, named by its block, in reading order."""
    for index, block in enumerate(composition.blocks):
        where = f"block {index + 1} ({block.kind})"
        for name in WRITTEN_FIELDS[block.kind]:
            if name not in _PROPOSALS and (text := getattr(block, name)):
                yield f"{where} {name}", text
        for item in block.items if block.kind in ITEM_BLOCKS else []:
            if item.title:
                yield f"{where} item {item.id} title", item.title
            if item.detail:
                yield f"{where} item {item.id} detail", item.detail


async def _problems(
    user_id: str, answer: BriefComposition, pool: FactPool, facts: str, values: SlotValues
) -> list[str]:
    """Return the contract's problems, else every claim the composition's words make that the pool does not hold."""
    problems = composition_problems(answer, pool, values)
    if problems:
        return problems
    checked = CheckedProse(fields=tuple(_written_text(rendered(answer, values, mark=True))))
    if not checked.fields:
        return []
    return [claim.problem() for claim in await unsupported_claims(user_id, facts, checked)]


async def compose_brief(user_id: str, pool: FactPool, kind: BriefingKind) -> Composed:
    """Compose the brief over the pool; a pool with nothing but the calendar needs no call."""
    values = pool_values(pool)
    if not pool.composable:
        empty = BriefComposition()
        return Composed(written=empty, rendered=empty, values=values)
    facts = pool_block(pool)
    prompt = composition_prompt(pool, kind, facts)
    checked_against = f"{context_block(pool.context)}\n\n{facts}"

    async def attempt(note: str) -> tuple[BriefComposition | None, list[str]]:
        try:
            answer = await ainvoke_structured(
                BriefComposition,
                f"{prompt}\n\n{note}" if note else prompt,
                label=BRIEF_COMPOSITION_LABEL,
                config=metered_config(user_id),
            )
        except MalformedStructuredOutputError as exc:
            # A reply that is no whole composition is a broken answer like any other: named, asked again.
            return None, [f"the answer was not a whole BriefComposition tool call ({exc})"]
        return answer, await _problems(user_id, answer, pool, checked_against, values)

    answer, problems = await attempt("")
    for _ in range(MAX_COMPOSITION_ATTEMPTS - 1):
        if not problems:
            break
        log.warning("briefing.composition_rejected", problems=problems)
        answer, problems = await attempt(
            COMPOSITION_RETRY_NOTE.format(problems="; ".join(problems))
        )
    if problems or answer is None:
        raise AppError(
            message="the brief's composition broke its contract",
            why="; ".join(problems),
            fix=(
                "the composition was asked again once with the problems named; "
                "the next scheduled brief retries"
            ),
            meta={"answer": answer.model_dump() if answer is not None else None},
        )
    return Composed(written=answer, rendered=rendered(answer, values), values=values)
