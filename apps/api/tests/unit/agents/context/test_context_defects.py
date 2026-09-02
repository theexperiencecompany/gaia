"""The defects the harness exposed, each pinned before it was fixed.

None of these could be written before ``effective_context`` existed: every one
of them is invisible at the seed and only shows up in the array the model
actually receives. That is the whole reason they survived in production.

Every test here was written and observed RED before its fix, and the invariants
they rest on are mutation-checked (see ``test_context_invariants.py``). They
deliberately carry no ``@pytest.mark.regression`` marker: that gate re-runs
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
    HarnessUser,
    effective_context,
    message_in_slot,
    seed_only,
    slots_of,
    text_of,
)
from tests._harness.context_sources import ContextSources, memory

from app.agents.context.slots import PromptSlot
from app.agents.llm.types import LLMProviderName

VOLATILE_SOURCES = ContextSources(
    core_memory="- Prefers short answers.",
    memories=[memory("Ships on Fridays", mentioned="2026-02-01")],
    skills="## Available skills\n- inbox-triage",
    connected_integrations=[{"id": "gmail", "name": "Gmail"}],
    provider_metadata={"email": "ada@example.com"},
    custom_instructions="Always archive newsletters.",
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
    """``create_agent_context_message`` stamped ``dynamic_context`` and never
    ``memory_recall``, so every subagent's per-turn content — recalled memories,
    skills, provider metadata, run banners — landed in the byte-stable slot at
    index 1. That is inside the region the implicit cache keys on, so each new
    query moved the cache boundary to the top of the prompt: exactly the failure
    ``manage_system_prompts_node`` exists to prevent.
    """

    @pytest.mark.parametrize("tier", WORKER_TIERS)
    async def test_recalled_memories_are_in_the_volatile_slot(self, tier: AgentTier) -> None:
        messages = await effective_context(tier, ContextSeed(sources=VOLATILE_SOURCES))

        recall = text_of(message_in_slot(messages, PromptSlot.MEMORY_RECALL))
        assert "Ships on Fridays" in recall

    @pytest.mark.parametrize("tier", WORKER_TIERS)
    async def test_skills_are_in_the_cached_prefix(self, tier: AgentTier) -> None:
        """The listing is byte-stable per (user, agent) — no query, no clock,
        Redis-cached 12h — so it belongs in the prefix where it costs nothing
        per call, not in the tail it was re-read from on every worker call.
        A mid-conversation skill install breaks the prefix once; that is the
        same trade integrations_manifest already makes for connects."""
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
        # "Prefers short answers" is deliberately absent: a memory-core DOCUMENT
        # is rewritten by consolidation, not per query, so it belongs in the
        # prefix. The core's agenda and journal are what churn, and they are a
        # separate section in the volatile slot. "inbox-triage" (the skills
        # listing) is likewise absent: it is byte-stable per (user, agent) and
        # now lives in the prefix on purpose.
        assert "Ships on Fridays" not in stable, (
            "per-query recall churns per turn but sits in the cacheable prefix"
        )


@pytest.mark.unit
class TestEveryTierKnowsTheDate:
    """The workflow authoring subagent seeded no clock at all. Nothing in the
    code explained the omission, and a workflow author that cannot tell today's
    date cannot resolve "every Monday" or "starting next week"."""

    async def test_workflow_authoring_receives_exactly_one_clock(self) -> None:
        messages = await effective_context(
            AgentTier.WORKFLOW_AUTHORING, ContextSeed(sources=VOLATILE_SOURCES)
        )

        clocks = [m for m in messages if m.additional_kwargs.get("time_context")]
        assert len(clocks) == 1


@pytest.mark.unit
class TestSeedOrderIsAlreadyCanonical:
    """Comms emitted ``[…, human, time]`` and every other tier ``[…, time, human]``.
    Harmless only because the hook chain reordered it — the invariant was enforced
    in one place and violated in another, which is how it stays broken."""

    @pytest.mark.parametrize("tier", list(AgentTier))
    async def test_seed_is_in_canonical_slot_order(self, tier: AgentTier) -> None:
        slots = slots_of(await seed_only(tier, sources=VOLATILE_SOURCES))

        assert slots == sorted(slots)

    @pytest.mark.parametrize("tier", list(AgentTier))
    async def test_hooks_leave_a_fresh_seed_order_unchanged(self, tier: AgentTier) -> None:
        """Reordering should be a normalisation of already-correct input, not a
        correction the tiers silently depend on.

        Asserted on the Gemini lane, which is the layout the seed is written in.
        The OpenAI wire's tail layout IS a deliberate reorder by the hook — the
        one thing a tier cannot do itself, because the seed is built before the
        provider is known to it (pinned in ``test_context_invariants``:
        ``TestTheTailLayoutOnTheOpenAIWire``).
        """
        seed = slots_of(await seed_only(tier, sources=VOLATILE_SOURCES))
        effective = slots_of(
            await effective_context(
                tier,
                ContextSeed(
                    sources=VOLATILE_SOURCES,
                    configurable_overrides={"provider": LLMProviderName.GEMINI},
                ),
            )
        )

        assert [slot for slot in effective if slot in seed] == seed


@pytest.mark.unit
class TestAQueryChangeMovesOnlyTheVolatileSlot:
    """The prefix-stability guarantee, stated as behaviour: two queries from the
    same user on the same tier must differ only in the volatile slot and the
    turn itself."""

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
class TestOnboardingPromptDoesNotEvictIdentity:
    """``construct_langchain_messages`` appended the onboarding prompt carrying
    ``memory_message=True`` *after* the stable dynamic-context message, and the
    node keeps only the latest holder of that marker — so on every onboarding
    turn the user's name, timezone, preferences and connected-integrations
    manifest silently never reached the model. Onboarding is precisely when
    knowing the user matters most."""

    async def test_identity_survives_an_onboarding_turn(self) -> None:
        user = HarnessUser(name="Zylphara", timezone="Asia/Kolkata")
        messages = await effective_context(
            AgentTier.COMMS,
            ContextSeed(
                user=user,
                sources=ContextSources(connected_integrations=[{"id": "gmail", "name": "Gmail"}]),
                onboarding_prompt="Welcome! Ask about their inbox.",
            ),
        )

        stable = text_of(message_in_slot(messages, PromptSlot.DYNAMIC_STABLE))
        assert user.name in stable
        assert "Gmail" in stable

    async def test_the_onboarding_prompt_still_reaches_the_model(self) -> None:
        messages = await effective_context(
            AgentTier.COMMS, ContextSeed(onboarding_prompt="Welcome! Ask about their inbox.")
        )

        assembled = " ".join(text_of(m) for m in messages if m.type == "system")
        assert "Ask about their inbox" in assembled

    async def test_the_comms_persona_also_survives(self) -> None:
        """The onboarding prompt must not evict the static prompt either — the
        obvious 'fix' of dropping its marker would just move the eviction."""
        with_onboarding = await effective_context(
            AgentTier.COMMS, ContextSeed(onboarding_prompt="Welcome! Ask about their inbox.")
        )
        without = await effective_context(AgentTier.COMMS)

        assert text_of(message_in_slot(with_onboarding, PromptSlot.STATIC)) == text_of(
            message_in_slot(without, PromptSlot.STATIC)
        )

    async def test_a_stale_onboarding_prompt_is_collapsed(self) -> None:
        stale = SystemMessage(
            content="stale onboarding", additional_kwargs={"onboarding_context": True}
        )
        messages = await effective_context(
            AgentTier.COMMS,
            ContextSeed(
                onboarding_prompt="Welcome! Ask about their inbox.", prior_messages=[stale]
            ),
        )

        assert slots_of(messages).count(PromptSlot.ONBOARDING) == 1
        assert stale not in messages
