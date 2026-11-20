"""Unit tests for context-assembly latency spans."""

import asyncio
from unittest.mock import patch

from prometheus_client import REGISTRY
import pytest

from app.agents.context import assemble
from app.agents.context.section_context import SectionContext
from app.agents.context.sections import Section, SectionId
from app.agents.context.slots import PromptSlot
from app.agents.context.tiers import AgentTier
from app.services.turn_timings import TurnPhase, TurnStep, begin_turn_timings
from tests.helpers import captured_wide_event


def _count(stage: str) -> float:
    return REGISTRY.get_sample_value("context_assemble_seconds_count", {"stage": stage}) or 0.0


def _sum(stage: str) -> float:
    return REGISTRY.get_sample_value("context_assemble_seconds_sum", {"stage": stage}) or 0.0


def _stub_section(
    section_id: SectionId, delay: float, slot: PromptSlot = PromptSlot.DYNAMIC_STABLE
) -> Section:
    async def _fetch(ctx: SectionContext) -> str:
        await asyncio.sleep(delay)
        return f"text-{section_id}"

    return Section(section_id, slot, frozenset({AgentTier.COMMS}), 10, _fetch)


def _budget_trips(section_id: SectionId) -> float:
    return (
        REGISTRY.get_sample_value(
            "context_section_budget_exceeded_total", {"section": section_id.value}
        )
        or 0.0
    )


def _ctx() -> SectionContext:
    return SectionContext(tier=AgentTier.COMMS, user_id="u")


async def test_render_section_emits_per_section_span() -> None:
    before = _count("section:user_identity")
    section_id, text = await assemble._render_section(
        _stub_section(SectionId.USER_IDENTITY, 0.01), _ctx()
    )
    assert (section_id, text) == (SectionId.USER_IDENTITY, "text-user_identity")
    assert _count("section:user_identity") == before + 1
    assert _sum("section:user_identity") > 0.0


async def test_gather_total_covers_slowest_section() -> None:
    slow = _stub_section(SectionId.MEMORY_RECALL, 0.05, PromptSlot.MEMORY_RECALL)
    fast = _stub_section(SectionId.USER_PREFS, 0.01, PromptSlot.DYNAMIC_STABLE)
    total_before = _count("total")
    total_sum_before = _sum("total")
    slow_before = _sum("section:memory_recall")

    def _fake_sections_for(tier: AgentTier, slot: PromptSlot) -> list[Section]:
        return [fast] if slot == PromptSlot.DYNAMIC_STABLE else [slow]

    with patch.object(assemble, "sections_for", side_effect=_fake_sections_for):
        result = await assemble._gather_sections(_ctx())

    assert _count("total") == total_before + 1
    assert "text-memory_recall" in (result.volatile.content if result.volatile else "")
    assert "text-user_prefs" in result.stable.content
    # Total wall time covers the slowest concurrent child.
    total_delta = _sum("total") - total_sum_before
    slow_delta = _sum("section:memory_recall") - slow_before
    assert total_delta >= slow_delta - 0.005


async def test_a_section_over_its_budget_renders_empty_while_the_others_render() -> None:
    never = asyncio.Event()

    async def _hung(ctx: SectionContext) -> str:
        await never.wait()
        return "never rendered"

    hung = Section(
        SectionId.GAIA_KNOWLEDGE,
        PromptSlot.MEMORY_RECALL,
        frozenset({AgentTier.COMMS}),
        30,
        _hung,
        budget_seconds=0.001,
    )
    fast = _stub_section(SectionId.USER_PREFS, 0.0, PromptSlot.DYNAMIC_STABLE)
    before = _budget_trips(SectionId.GAIA_KNOWLEDGE)

    def _fake_sections_for(tier: AgentTier, slot: PromptSlot) -> list[Section]:
        return [fast] if slot == PromptSlot.DYNAMIC_STABLE else [hung]

    with patch.object(assemble, "sections_for", side_effect=_fake_sections_for):
        async with captured_wide_event() as event:
            result = await assemble._gather_sections(_ctx())

    assert result.volatile is None
    assert "text-user_prefs" in result.stable.content
    assert _budget_trips(SectionId.GAIA_KNOWLEDGE) == before + 1
    assert event["warnings"] == [
        {
            "msg": "[AGENT] Context section exceeded its budget",
            "section": SectionId.GAIA_KNOWLEDGE.value,
            "tier": AgentTier.COMMS.value,
            "budget_ms": 1.0,
            "user_id": "u",
            "error_type": "TimeoutError",
            "error": "",
        }
    ]


async def test_a_timeout_the_section_raised_itself_is_not_mistaken_for_its_budget() -> None:
    async def _raises(ctx: SectionContext) -> str:
        raise TimeoutError("an inner deadline")

    section = Section(
        SectionId.USER_PREFS, PromptSlot.DYNAMIC_STABLE, frozenset({AgentTier.COMMS}), 10, _raises
    )
    before = _budget_trips(SectionId.USER_PREFS)

    with pytest.raises(TimeoutError, match="an inner deadline"):
        await assemble._render_section(section, _ctx())

    assert _budget_trips(SectionId.USER_PREFS) == before


@pytest.mark.parametrize("memory_section", [SectionId.MEMORY_RECALL, SectionId.FAST_MEMORY_RECALL])
async def test_either_memory_section_marks_the_turn_as_having_memories(
    memory_section: SectionId,
) -> None:
    rendered = _stub_section(memory_section, 0.0, PromptSlot.MEMORY_RECALL)

    def _fake_sections_for(tier: AgentTier, slot: PromptSlot) -> list[Section]:
        return [rendered] if slot == PromptSlot.MEMORY_RECALL else []

    with patch.object(assemble, "sections_for", side_effect=_fake_sections_for):
        async with captured_wide_event() as event:
            await assemble._gather_sections(_ctx())

    assert event["dynamic_context"]["has_memories"] is True


async def test_assembly_is_timed_as_the_turns_context_step() -> None:
    fast = _stub_section(SectionId.USER_PREFS, 0.0, PromptSlot.DYNAMIC_STABLE)
    timings = begin_turn_timings()

    def _fake_sections_for(tier: AgentTier, slot: PromptSlot) -> list[Section]:
        return [fast] if slot == PromptSlot.DYNAMIC_STABLE else []

    with patch.object(assemble, "sections_for", side_effect=_fake_sections_for):
        await assemble._gather_sections(_ctx())

    assert list(timings.steps) == [(TurnPhase.INGRESS, TurnStep.CONTEXT)]
