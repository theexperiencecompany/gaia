"""The defects the harness exposed, each pinned before it was fixed.

None of these could be written before effective_context existed: every one
of them is invisible at the seed and only shows up in the array the model
actually receives. That is the whole reason they survived in production.

Every test here was written and observed RED before its fix, and the invariants
they rest on are mutation-checked (see test_context_invariants.py). They
deliberately carry no @pytest.mark.regression marker: that gate re-runs
marked tests against the base revision, and these import a harness the same
change introduces, so on base they do not fail — they fail to *collect*. An
error is not proof, and claiming the marker would assert a proof the gate
cannot actually perform.
"""

from langchain_core.messages import SystemMessage
import pytest
from tests._harness.context_chain import (
    AgentTier,
    ContextSeed,
    bound_for,
    effective_context,
    message_in_slot,
    seed_only,
    slots_of,
    text_of,
)
from tests._harness.context_sources import ContextSources, memory

from app.agents.context.slots import PromptSlot
from app.constants.llm import LLMProviderName

VOLATILE_SOURCES = ContextSources(
    core_memory="- Prefers short answers.",
    memories=[memory("Ships on Fridays", mentioned="2026-02-01")],
    skills="## Available skills\n- inbox-triage",
    connected_integrations=[{"id": "gmail", "name": "Gmail"}],
    account_identity={"email": "ada@example.com"},
    global_instructions="Reply in plain English.",
    integration_instructions="Always archive newsletters.",
    tracked_todos="Tracked: ship the context refactor",
    workflow_integrations_hint="# Connected integrations\nGmail (`gmail`)",
)

#: Tiers whose context carries per-query content. Comms already split its
#: volatile block out; every worker tier folded it into the cacheable prefix.
WORKER_TIERS = [
    AgentTier.EXECUTOR,
    AgentTier.PROVIDER_SUBAGENT,
    AgentTier.SPAWN,
    AgentTier.WORKFLOW_AUTHORING,
]


@pytest.mark.unit
class TestVolatileContentIsNotInTheCacheablePrefix:
    """create_agent_context_message stamped every subagent's per-turn content into the byte-stable prefix, moving the cache boundary on each query."""

    @pytest.mark.parametrize("tier", WORKER_TIERS)
    async def test_recalled_memories_are_in_the_volatile_slot(self, tier: AgentTier) -> None:
        messages = await effective_context(tier, ContextSeed(sources=VOLATILE_SOURCES))

        recall = text_of(message_in_slot(messages, PromptSlot.MEMORY_RECALL))
        assert "Ships on Fridays" in recall

    @pytest.mark.parametrize("tier", WORKER_TIERS)
    async def test_skills_are_in_the_cached_prefix(self, tier: AgentTier) -> None:
        """The skills listing is byte-stable per (user, agent) and Redis-cached 12h, so it belongs in the prefix — the same trade integrations_manifest already makes for connects."""
        messages = await effective_context(tier, ContextSeed(sources=VOLATILE_SOURCES))

        stable = text_of(message_in_slot(messages, PromptSlot.DYNAMIC_STABLE))
        recall = text_of(message_in_slot(messages, PromptSlot.MEMORY_RECALL))
        assert "inbox-triage" in stable
        assert "inbox-triage" not in recall

    @pytest.mark.parametrize("tier", [AgentTier.EXECUTOR, AgentTier.PROVIDER_SUBAGENT])
    async def test_run_banners_are_in_the_volatile_slot(self, tier: AgentTier) -> None:
        messages = await effective_context(
            tier,
            ContextSeed(
                sources=VOLATILE_SOURCES, configurable_overrides={"execution_mode": "background"}
            ),
        )

        recall = text_of(message_in_slot(messages, PromptSlot.MEMORY_RECALL))
        assert "BACKGROUND EXECUTION" in recall

    @pytest.mark.parametrize("tier", WORKER_TIERS)
    async def test_stable_slot_holds_no_per_query_content(self, tier: AgentTier) -> None:
        messages = await effective_context(tier, ContextSeed(sources=VOLATILE_SOURCES))

        stable = text_of(message_in_slot(messages, PromptSlot.DYNAMIC_STABLE))
        # "Prefers short answers" is absent: a memory-core document is rewritten by
        # consolidation, not per query, so it belongs in the prefix (agenda/journal churn
        # separately in the volatile slot); "inbox-triage" is likewise prefix-only, on purpose.
        assert "Ships on Fridays" not in stable, (
            "per-query recall churns per turn but sits in the cacheable prefix"
        )


@pytest.mark.unit
class TestEveryTierKnowsTheDate:
    """The workflow authoring subagent seeded no clock, so it could not resolve phrases like "every Monday"."""

    async def test_workflow_authoring_receives_exactly_one_clock(self) -> None:
        messages = await effective_context(
            AgentTier.WORKFLOW_AUTHORING, ContextSeed(sources=VOLATILE_SOURCES)
        )

        clocks = [m for m in messages if m.additional_kwargs.get("time_context")]
        assert len(clocks) == 1


@pytest.mark.unit
class TestSeedOrderIsAlreadyCanonical:
    """Comms emitted […, human, time] while every other tier emitted […, time, human]; only the hook chain's reorder hid it."""

    @pytest.mark.parametrize("tier", list(AgentTier))
    async def test_seed_is_in_canonical_slot_order(self, tier: AgentTier) -> None:
        slots = slots_of(await seed_only(tier, sources=VOLATILE_SOURCES))

        assert slots == sorted(slots)

    @pytest.mark.parametrize("tier", list(AgentTier))
    async def test_hooks_leave_a_fresh_seed_order_unchanged(self, tier: AgentTier) -> None:
        """Asserted on the Gemini lane, the seed's native layout; the OpenAI wire's reorder is a separate, deliberate hook pinned in TestTheTailLayoutOnTheOpenAIWire."""
        seed = slots_of(await seed_only(tier, sources=VOLATILE_SOURCES))
        effective = slots_of(
            await effective_context(
                tier,
                ContextSeed(
                    sources=VOLATILE_SOURCES,
                    configurable_overrides=bound_for(LLMProviderName.GEMINI),
                ),
            )
        )

        assert [slot for slot in effective if slot in seed] == seed


@pytest.mark.unit
class TestAQueryChangeMovesOnlyTheVolatileSlot:
    """The prefix-stability guarantee: two queries from the same user and tier must differ only in the volatile slot and the turn."""

    @pytest.mark.parametrize("tier", list(AgentTier))
    async def test_static_and_stable_are_byte_identical_across_queries(
        self, tier: AgentTier
    ) -> None:
        first = await effective_context(
            tier,
            ContextSeed(
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
                query="what did I promise the design team?",
                sources=ContextSources(
                    memories=[memory("Owes the design team a spec", mentioned="2026-03-02")],
                    connected_integrations=[{"id": "gmail", "name": "Gmail"}],
                ),
            ),
        )

        for slot in (PromptSlot.STATIC, PromptSlot.DYNAMIC_STABLE):
            assert text_of(message_in_slot(first, slot)) == text_of(
                message_in_slot(second, slot)
            ), f"{slot.name} moved when only the query changed"

    @pytest.mark.parametrize("tier", list(AgentTier))
    async def test_the_difference_lands_in_the_volatile_slot(self, tier: AgentTier) -> None:
        messages = await effective_context(
            tier,
            ContextSeed(
                query="what did I promise the design team?",
                sources=ContextSources(
                    memories=[memory("Owes the design team a spec", mentioned="2026-03-02")]
                ),
            ),
        )

        recall = text_of(message_in_slot(messages, PromptSlot.MEMORY_RECALL))
        assert "Owes the design team a spec" in recall


@pytest.mark.unit
class TestALegacyOnboardingPromptStaysInItsOwnSlot:
    """Checkpoints still replay the retired onboarding prompt; read as STATIC it would evict the real one."""

    async def test_replayed_copies_collapse_to_one_and_leave_the_static_prompt_alone(self) -> None:
        stale = [
            SystemMessage(
                content=f"stale onboarding {n}", additional_kwargs={"onboarding_context": True}
            )
            for n in (1, 2)
        ]
        replayed = await effective_context(AgentTier.COMMS, ContextSeed(prior_messages=stale))
        fresh = await effective_context(AgentTier.COMMS)

        assert slots_of(replayed).count(PromptSlot.ONBOARDING) == 1
        assert stale[0] not in replayed
        assert text_of(message_in_slot(replayed, PromptSlot.STATIC)) == text_of(
            message_in_slot(fresh, PromptSlot.STATIC)
        )
