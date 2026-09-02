"""The prompt-cache guarantee the whole slot ordering exists to protect.

Every ordering decision in ``PromptSlot`` — the clock at the tail of contents,
volatile sections after stable ones, one message per slot — exists to keep the
request prefix byte-identical across turns so the provider's implicit cache can
match it. Nothing asserted that it actually did.

**The floor is the exact stable-block boundary, not a byte count or a ratio.**
Both of those were considered and both are insensitive here. The static prompt
is ~36 KB and a volatile block is a few hundred bytes, so folding the volatile
block back into the cacheable region — the precise defect this change fixed —
moves the shared prefix by well under 1%. A ratio high enough to catch it
(0.999+) is indistinguishable from noise under any prompt edit, and a fixed byte
count stops meaning anything the moment a prompt grows. The boundary itself has
neither problem: it says exactly what the design requires — *no byte at or
before the end of the stable block may move between turns* — and it stays true
through any prompt edit, at any size.
"""

import pytest
from tests._harness.context_chain import (
    FIXED_NOW,
    ContextSeed,
    HarnessUser,
    common_prefix_len,
    effective_context,
    request_bytes,
    text_of,
)
from tests._harness.context_sources import ContextSources, memory

from app.agents.context.slots import PromptSlot, slot_of
from app.agents.context.tiers import AgentTier

SOURCES = ContextSources(
    core_memory="- Prefers short answers.",
    memories=[memory("Ships on Fridays", mentioned="2026-02-01")],
    skills="## Available skills\n- inbox-triage",
    connected_integrations=[{"id": "gmail", "name": "Gmail"}],
    provider_metadata={"email": "ada@example.com"},
    custom_instructions="Always archive newsletters.",
    tracked_todos="Tracked: ship the context refactor",
    workflow_integrations_hint="# Connected integrations\nGmail (`gmail`)",
)


def stable_block_end(messages: list) -> int:
    """Byte offset just past the stable block — the floor the prefix must clear.

    Everything up to here (static prompt, then the stable identity block) is
    what a turn must leave untouched. Measured on the same rendering the prefix
    comparison uses, so the two numbers are directly comparable.
    """
    cutoff = 0
    for index, message in enumerate(messages):
        if slot_of(message) > PromptSlot.DYNAMIC_STABLE:
            break
        cutoff = index + 1
    return len(request_bytes(messages[:cutoff]))


@pytest.mark.unit
class TestPrefixSurvivesAClockTick:
    @pytest.mark.parametrize("tier", list(AgentTier))
    async def test_nothing_at_or_before_the_stable_block_moves(self, tier: AgentTier) -> None:
        user = HarnessUser()
        first = await effective_context(
            tier, ContextSeed(user=user, sources=SOURCES, now=FIXED_NOW)
        )
        later = await effective_context(
            tier, ContextSeed(user=user, sources=SOURCES, now=FIXED_NOW.replace(minute=45))
        )

        shared = common_prefix_len(request_bytes(first), request_bytes(later))
        floor = stable_block_end(first)

        assert shared >= floor, (
            f"{tier.value}: the shared prefix ends at byte {shared}, inside the "
            f"{floor}-byte cacheable block — a clock tick moved cacheable bytes"
        )

    @pytest.mark.parametrize("tier", list(AgentTier))
    async def test_only_the_clock_differs_across_a_tick(self, tier: AgentTier) -> None:
        """Stated separately from the floor: a prefix can clear the boundary
        while something else still moved behind it."""
        user = HarnessUser()
        first = await effective_context(
            tier, ContextSeed(user=user, sources=SOURCES, now=FIXED_NOW)
        )
        later = await effective_context(
            tier, ContextSeed(user=user, sources=SOURCES, now=FIXED_NOW.replace(minute=45))
        )

        differing = [(a, b) for a, b in zip(first, later, strict=True) if text_of(a) != text_of(b)]
        assert len(differing) == 1
        assert differing[0][0].additional_kwargs.get("time_context") is True


@pytest.mark.unit
class TestPrefixSurvivesANewQuery:
    @pytest.mark.parametrize("tier", list(AgentTier))
    async def test_a_new_query_leaves_the_cacheable_block_intact(self, tier: AgentTier) -> None:
        """The defect this change fixed: with volatile content mis-slotted into
        the stable block, a new query moved the cache boundary up into the
        prompt and every subagent turn paid full price."""
        user = HarnessUser()
        first = await effective_context(
            tier,
            ContextSeed(
                user=user,
                query="summarise my unread mail",
                sources=ContextSources(
                    memories=[memory("Ships on Fridays", mentioned="2026-02-01")],
                    connected_integrations=[{"id": "gmail", "name": "Gmail"}],
                ),
            ),
        )
        second = await effective_context(
            tier,
            ContextSeed(
                user=user,
                query="what did I promise the design team?",
                sources=ContextSources(
                    memories=[memory("Owes the design team a spec", mentioned="2026-03-02")],
                    connected_integrations=[{"id": "gmail", "name": "Gmail"}],
                ),
            ),
        )

        shared = common_prefix_len(request_bytes(first), request_bytes(second))
        floor = stable_block_end(first)

        assert shared >= floor, (
            f"{tier.value}: a query change ended the shared prefix at byte {shared}, "
            f"inside the {floor}-byte cacheable block"
        )


@pytest.mark.unit
class TestTheFloorCanFail:
    """A floor no realistic regression can breach is decoration. This pins that
    the measurement responds to the exact defect it guards against — and it is
    why the floor is a boundary rather than the ratio originally proposed, which
    this same check showed to be insensitive at the real prompt sizes."""

    async def test_volatile_content_in_the_stable_block_breaches_the_floor(self) -> None:
        user = HarnessUser()
        runs = [
            await effective_context(
                AgentTier.EXECUTOR,
                ContextSeed(
                    user=user,
                    query=query,
                    sources=ContextSources(memories=[memory(text, mentioned="2026-02-01")]),
                ),
            )
            for query, text in (("one", "alpha"), ("two", "beta"))
        ]

        # The pre-fix arrangement: volatile content concatenated into the stable
        # message, which is exactly what create_agent_context_message produced.
        def folded(messages: list) -> list:
            from langchain_core.messages import SystemMessage

            from app.agents.context.slots import DYNAMIC_CONTEXT_MARKER, mark

            stable = next(m for m in messages if slot_of(m) is PromptSlot.DYNAMIC_STABLE)
            recall = next(m for m in messages if slot_of(m) is PromptSlot.MEMORY_RECALL)
            merged = mark(
                SystemMessage(content=f"{text_of(stable)}\n{text_of(recall)}"),
                DYNAMIC_CONTEXT_MARKER,
            )
            return [m if m is not stable else merged for m in messages if m is not recall]

        first, second = folded(runs[0]), folded(runs[1])
        shared = common_prefix_len(request_bytes(first), request_bytes(second))

        assert shared < stable_block_end(first), (
            "the floor did not notice volatile content sitting in the cacheable "
            "prefix — it cannot fail, so it is not guarding anything"
        )
