"""Unit tests for context-assembly latency spans."""

import asyncio
from unittest.mock import patch

from prometheus_client import REGISTRY

from app.agents.context import assemble
from app.agents.context.section_context import SectionContext
from app.agents.context.sections import Section, SectionId
from app.agents.context.slots import PromptSlot
from app.agents.context.tiers import AgentTier


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
