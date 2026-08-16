"""The rules the whole context design exists to protect.

Each of these was, until now, defended only by a comment — and every comment
here documents a real incident. A comment cannot fail CI, which is why the
regressions kept coming back. These are the same rules as executable assertions,
and they hold across all five tiers.
"""

from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
import pytest
from tests._harness.context_chain import (
    FIXED_NOW,
    AgentTier,
    HarnessUser,
    effective_context,
    message_in_slot,
    slots_of,
    text_of,
)
from tests._harness.context_sources import (
    ContextSources,
    fake_context_sources,
    knowledge,
    memory,
)

from app.agents.context.assemble import assemble_context
from app.agents.context.section_context import SectionContext
from app.agents.context.slots import PromptSlot, slot_of

RICH_SOURCES = ContextSources(
    core_memory="- Prefers short answers.",
    memories=[memory("Ships on Fridays", mentioned="2026-02-01")],
    gaia_knowledge=[knowledge("GAIA can run scheduled workflows.")],
    tracked_todos="Tracked: ship the context refactor",
    skills="## Available skills\n- inbox-triage",
    connected_integrations=[{"id": "gmail", "name": "Gmail"}],
    provider_metadata={"email": "ada@example.com"},
    custom_instructions="Always archive newsletters.",
    workflow_integrations_hint="# Connected integrations\nGmail (`gmail`)",
)

#: A checkpointed thread's worth of prior turns, carrying a stale copy of every
#: slot a tier can produce. The collapse invariants are only interesting here —
#: a first turn has nothing to collapse.
STALE_THREAD = [
    SystemMessage(content="stale static"),
    SystemMessage(content="stale dynamic", additional_kwargs={"dynamic_context": True}),
    SystemMessage(content="stale recall", additional_kwargs={"memory_recall": True}),
    SystemMessage(content="stale todo", additional_kwargs={"todo_context": True}),
    SystemMessage(content="stale bg", name="background_executor"),
    SystemMessage(content="stale status", additional_kwargs={"executor_status": True}),
    HumanMessage(content="an earlier question"),
    AIMessage(content="an earlier answer"),
    HumanMessage(content="stale clock", additional_kwargs={"time_context": True}),
]


@pytest.mark.unit
class TestSystemBlockIsLeadingAndContiguous:
    """``langchain-google-genai`` promotes a ``SystemMessage`` to
    ``system_instruction`` only while the system block is leading and unbroken.
    The first non-system message ends the block, and every later system message
    is silently discarded — taking the entire persona with it."""

    @pytest.mark.parametrize("tier", list(AgentTier))
    @pytest.mark.parametrize("multi_turn", [False, True])
    async def test_no_system_message_follows_a_non_system_message(
        self, tier: AgentTier, multi_turn: bool
    ) -> None:
        messages = await effective_context(
            tier,
            sources=RICH_SOURCES,
            prior_messages=list(STALE_THREAD) if multi_turn else None,
        )

        first_non_system = next(
            (index for index, m in enumerate(messages) if m.type != "system"), len(messages)
        )
        trailing_system = [m for m in messages[first_non_system:] if m.type == "system"]
        assert not trailing_system, (
            f"{len(trailing_system)} system message(s) sit after the conversation begins; "
            "Gemini would drop every one of them"
        )


@pytest.mark.unit
class TestStaticPromptIsUserIndependent:
    """The static prefix is byte-identical across users so the first user of the
    day on a channel warms the cache for everyone after them. Leaking one user's
    name into it costs every other user their turn-1 cache hit."""

    @pytest.mark.parametrize("tier", list(AgentTier))
    async def test_two_users_share_a_byte_identical_static_prompt(self, tier: AgentTier) -> None:
        ada = HarnessUser(user_id="user-alpha", name="Ada", timezone="Asia/Kolkata")
        grace = HarnessUser(user_id="user-beta", name="Grace", timezone="America/New_York")

        for_ada = await effective_context(tier, user=ada, sources=RICH_SOURCES)
        for_grace = await effective_context(tier, user=grace, sources=RICH_SOURCES)

        assert text_of(message_in_slot(for_ada, PromptSlot.STATIC)) == text_of(
            message_in_slot(for_grace, PromptSlot.STATIC)
        )

    @pytest.mark.parametrize("tier", list(AgentTier))
    async def test_static_prompt_holds_no_per_user_bytes(self, tier: AgentTier) -> None:
        # Values chosen so none can appear as a substring of ordinary prompt
        # prose — "Ada" matches "Adaptation" and would fail for the wrong reason.
        user = HarnessUser(
            name="Zylphara",
            user_id="user-qxv71",
            email="zylphara@example.invalid",
            timezone="Asia/Kolkata",
        )
        messages = await effective_context(tier, user=user, sources=RICH_SOURCES)

        static = text_of(message_in_slot(messages, PromptSlot.STATIC))
        for leak in (user.name, user.user_id, user.timezone, user.email):
            assert leak not in static, f"{leak!r} leaked into the shared static prompt"

    @pytest.mark.parametrize("tier", list(AgentTier))
    async def test_identity_is_carried_outside_the_static_prompt(self, tier: AgentTier) -> None:
        user = HarnessUser(name="Zylphara", timezone="Asia/Kolkata")
        messages = await effective_context(tier, user=user, sources=RICH_SOURCES)

        carried = " ".join(
            text_of(m) for m in messages if m.type == "system" and m.content != messages[0].content
        )
        assert user.name in carried
        assert user.timezone in carried


@pytest.mark.unit
class TestClockPlacement:
    """The clock ticks every minute. In ``system_instruction`` it would push the
    cache boundary back to just before the timestamp on every call, so it rides
    a ``HumanMessage`` at the very tail of contents instead."""

    @pytest.mark.parametrize("tier", list(AgentTier))
    async def test_clock_is_the_final_message_and_is_human(self, tier: AgentTier) -> None:
        messages = await effective_context(tier, sources=RICH_SOURCES)

        assert messages[-1].type == "human"
        assert slots_of(messages)[-1] is PromptSlot.TIME

    @pytest.mark.parametrize("tier", list(AgentTier))
    async def test_no_system_message_carries_a_timestamp(self, tier: AgentTier) -> None:
        messages = await effective_context(tier, sources=RICH_SOURCES)

        stamp = FIXED_NOW.strftime("%H:%M")
        for message in messages:
            if message.type == "system":
                assert stamp not in text_of(message), (
                    "a minute-ticking byte in the system block resets the cache boundary "
                    "on every call"
                )

    async def test_only_the_latest_clock_survives_a_multi_turn_thread(self) -> None:
        messages = await effective_context(
            AgentTier.EXECUTOR, sources=RICH_SOURCES, prior_messages=list(STALE_THREAD)
        )

        clocks = [m for m in messages if m.additional_kwargs.get("time_context")]
        assert len(clocks) == 1
        assert FIXED_NOW.strftime("%H:%M") in text_of(clocks[0])


@pytest.mark.unit
class TestOneMessagePerSlot:
    @pytest.mark.parametrize("tier", list(AgentTier))
    async def test_every_singleton_slot_holds_at_most_one_message(self, tier: AgentTier) -> None:
        messages = await effective_context(
            tier, sources=RICH_SOURCES, prior_messages=list(STALE_THREAD)
        )

        slots = slots_of(messages)
        for slot in PromptSlot:
            if slot is PromptSlot.CONVERSATION:
                continue
            assert slots.count(slot) <= 1, f"{slot.name} survived {slots.count(slot)} times"

    @pytest.mark.parametrize("tier", list(AgentTier))
    async def test_the_survivor_is_the_latest(self, tier: AgentTier) -> None:
        """Every message in ``STALE_THREAD`` carries recognisable stale text, so a
        survivor of a slot this turn refilled is unmistakable.

        Only slots the current turn actually produces are checked. The background
        -executor and executor-status frames are injected by other paths and have
        no current-turn copy to displace, so a stale one legitimately survives.
        """
        messages = await effective_context(
            tier, sources=RICH_SOURCES, prior_messages=list(STALE_THREAD)
        )

        refilled = {PromptSlot.STATIC, PromptSlot.DYNAMIC_STABLE, PromptSlot.TIME}
        for message in messages:
            if slot_of(message) in refilled:
                assert not text_of(message).startswith("stale "), (
                    f"a stale {message.content!r} outlived the current turn's copy"
                )

    @pytest.mark.parametrize("tier", list(AgentTier))
    async def test_slots_appear_in_canonical_order(self, tier: AgentTier) -> None:
        messages = await effective_context(
            tier, sources=RICH_SOURCES, prior_messages=list(STALE_THREAD)
        )

        slots = slots_of(messages)
        assert slots == sorted(slots)

    async def test_conversation_history_is_preserved_in_order(self) -> None:
        """Collapsing slots must never collapse the conversation."""
        messages = await effective_context(
            AgentTier.EXECUTOR, sources=RICH_SOURCES, prior_messages=list(STALE_THREAD)
        )

        turns = [text_of(m) for m in messages if m.type in ("human", "ai")]
        assert turns[:2] == ["an earlier question", "an earlier answer"]


@pytest.mark.unit
class TestLegacyMarkersStillResolve:
    """Threads checkpointed before the marker split are still replayed."""

    async def test_memory_message_only_resolves_to_the_stable_slot(self) -> None:
        legacy = SystemMessage(content="legacy ctx", additional_kwargs={"memory_message": True})

        assert slot_of(legacy) is PromptSlot.DYNAMIC_STABLE

        messages = await effective_context(
            AgentTier.EXECUTOR, sources=RICH_SOURCES, prior_messages=[legacy]
        )
        assert legacy not in messages, "the legacy block competes for the stable slot and loses"

    async def test_marker_in_model_extra_resolves(self) -> None:
        """A marker passed as a bare constructor kwarg lands in ``model_extra``,
        not ``additional_kwargs``.

        Asserted on the slot directly. Inferring it from "the message did not
        survive" cannot fail: a misresolved message competes for the *static*
        slot and loses there too, so the array looks identical either way.
        """
        legacy = SystemMessage(content="legacy ctx", memory_message=True)

        assert legacy.model_extra == {"memory_message": True}, (
            "precondition: the marker must actually be in model_extra for this "
            "test to be exercising the fallback at all"
        )
        assert slot_of(legacy) is PromptSlot.DYNAMIC_STABLE

        messages = await effective_context(
            AgentTier.EXECUTOR, sources=RICH_SOURCES, prior_messages=[legacy]
        )
        assert legacy not in messages


@pytest.mark.unit
class TestWorkspaceSessionNeverGuesses:
    """``vfs_session_id`` is the executor's pin to the conversation thread.
    ``thread_id`` is the ``executor_<conv>`` wrapper — using it would state
    ``/workspace/sessions/executor_<conv>/``, sending the agent's deliverables
    outside the directory the artifact watcher scans, where they are lost."""

    @pytest.mark.parametrize(
        "tier", [AgentTier.EXECUTOR, AgentTier.PROVIDER_SUBAGENT, AgentTier.SPAWN]
    )
    async def test_absent_vfs_session_id_yields_no_banner(self, tier: AgentTier) -> None:
        messages = await effective_context(
            tier, sources=RICH_SOURCES, configurable_overrides={"vfs_session_id": None}
        )

        assembled = " ".join(text_of(m) for m in messages if m.type == "system")
        assert "Session directory:" not in assembled

    @pytest.mark.parametrize(
        "tier", [AgentTier.EXECUTOR, AgentTier.PROVIDER_SUBAGENT, AgentTier.SPAWN]
    )
    async def test_it_never_falls_back_to_thread_id(self, tier: AgentTier) -> None:
        messages = await effective_context(
            tier, sources=RICH_SOURCES, configurable_overrides={"vfs_session_id": None}
        )

        assembled = " ".join(text_of(m) for m in messages if m.type == "system")
        assert f"{tier.value}-thread" not in assembled


#: Each fallible read a comms turn performs, paired with the text only its own
#: section renders — so a survivor can be told apart from the section that failed.
FALLIBLE_SOURCES = [
    ("app.memory.engine.memory_engine.get_core_context", "Prefers short answers"),
    ("app.memory.engine.memory_engine.recall", "Ships on Fridays"),
    (
        "app.services.gaia_knowledge_service.gaia_knowledge_service.search_knowledge",
        "GAIA can run scheduled workflows",
    ),
    ("app.agents.context.fetchers._cached_tracked_todos_summary", "ship the context refactor"),
    ("app.agents.context.fetchers.get_connected_integrations_named", "Gmail"),
]

COMMS_CONTEXT = SectionContext(
    tier=AgentTier.COMMS,
    user_id="user-alpha",
    user_name="Ada",
    user_timezone="Asia/Kolkata",
    query="what is on my plate?",
)


@pytest.mark.unit
class TestOneFailingSourceCostsOnlyItsOwnSection:
    """Sections are gathered concurrently, so a section that raises instead of
    degrading takes the whole gather down with it — and the assembly-wide
    fallback then serves an *empty* stable block. A transient error on one
    enrichment read therefore strips the user's name, timezone, preferences,
    connected integrations and memories from the same turn.

    ``build_tracked_todos_block`` was the one fetcher that left its service call
    unguarded, so a Mongo blip on the todo service silently cost a comms turn
    every other piece of context it had.
    """

    @pytest.mark.parametrize(("target", "own_text"), FALLIBLE_SOURCES)
    async def test_every_other_section_survives(self, target: str, own_text: str) -> None:
        with (
            fake_context_sources(RICH_SOURCES),
            patch(target, AsyncMock(side_effect=RuntimeError("source down"))),
        ):
            assembled = await assemble_context(COMMS_CONTEXT)

        rendered = "\n".join(text_of(m) for m in assembled.messages())
        survivors = [text for _, text in FALLIBLE_SOURCES if text != own_text]
        for text in ("Ada", "Asia/Kolkata", *survivors):
            assert text in rendered, (
                f"{target} failing erased {text!r}, which it has nothing to do with"
            )

    @pytest.mark.parametrize(("target", "own_text"), FALLIBLE_SOURCES)
    async def test_only_the_failing_section_is_missing(self, target: str, own_text: str) -> None:
        """Guards the test above from passing vacuously: if a patched target
        were not actually on the section's path, nothing would have degraded."""
        with (
            fake_context_sources(RICH_SOURCES),
            patch(target, AsyncMock(side_effect=RuntimeError("source down"))),
        ):
            assembled = await assemble_context(COMMS_CONTEXT)

        rendered = "\n".join(text_of(m) for m in assembled.messages())
        assert own_text not in rendered
