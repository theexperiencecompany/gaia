"""The rules the whole context design exists to protect.

Each of these was, until now, defended only by a comment — and every comment
here documents a real incident. A comment cannot fail CI, which is why the
regressions kept coming back. These are the same rules as executable assertions,
and they hold across all five tiers.
"""

from dataclasses import replace
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
from tests.helpers import captured_wide_event

from app.agents.context.assemble import (
    VOLATILE_BLOCK_HEAD_CHARS,
    VOLATILE_BLOCK_MAX_CHARS,
    VOLATILE_BLOCK_TAIL_CHARS,
    assemble_context,
)
from app.agents.context.section_context import SectionContext
from app.agents.context.slots import (
    DYNAMIC_CONTEXT_MARKER,
    LEGACY_DYNAMIC_MARKER,
    MEMORY_RECALL_MARKER,
    PromptSlot,
    request_slot_order,
    slot_of,
)
from app.agents.context.text import VOLATILE_BLOCK_TRUNC_MARKER
from app.agents.llm.types import LLMProviderName
from app.constants.log_tags import LogTag

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
    is silently discarded — taking the entire persona with it.

    This binds on the GEMINI lane. The OpenAI wire has no such rule, and the tail
    layout spends exactly that freedom (see ``TestTheTailLayoutOnTheOpenAIWire``).
    """

    @pytest.mark.parametrize("tier", list(AgentTier))
    @pytest.mark.parametrize("multi_turn", [False, True])
    async def test_no_system_message_follows_a_non_system_message(
        self, tier: AgentTier, multi_turn: bool
    ) -> None:
        messages = await effective_context(
            tier,
            sources=RICH_SOURCES,
            prior_messages=list(STALE_THREAD) if multi_turn else None,
            configurable_overrides={"provider": LLMProviderName.GEMINI},
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
class TestTheTailLayoutOnTheOpenAIWire:
    """What the default (OpenRouter) lane does instead, and why.

    Every provider on the OpenAI wire applies a system message wherever it
    appears, so the per-turn slots sort BEHIND the conversation and the cacheable
    prefix grows to cover the history — measured 97% against 83% for the
    leading-block layout. Nothing here is safe on Gemini, which is why the layout
    is chosen per provider rather than globally.
    """

    @pytest.mark.parametrize("tier", list(AgentTier))
    async def test_the_per_turn_slots_sit_behind_the_conversation(self, tier: AgentTier) -> None:
        messages = await effective_context(
            tier, sources=RICH_SOURCES, prior_messages=list(STALE_THREAD)
        )

        slots = slots_of(messages)
        conversation_at = slots.index(PromptSlot.CONVERSATION)
        assert PromptSlot.MEMORY_RECALL in slots
        assert slots.index(PromptSlot.MEMORY_RECALL) > conversation_at

    @pytest.mark.parametrize("tier", list(AgentTier))
    async def test_the_stable_block_still_leads(self, tier: AgentTier) -> None:
        """The point of moving the churn to the tail is that everything ahead of
        the conversation is byte-stable — if a stable slot slipped behind it, the
        prefix would end at the static prompt again."""
        messages = await effective_context(
            tier, sources=RICH_SOURCES, prior_messages=list(STALE_THREAD)
        )

        slots = slots_of(messages)
        conversation_at = slots.index(PromptSlot.CONVERSATION)
        assert slots.index(PromptSlot.STATIC) < conversation_at
        assert slots.index(PromptSlot.DYNAMIC_STABLE) < conversation_at


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

    @pytest.mark.parametrize("provider", [LLMProviderName.OPENROUTER, LLMProviderName.GEMINI])
    @pytest.mark.parametrize("tier", list(AgentTier))
    async def test_slots_appear_in_canonical_order(
        self, tier: AgentTier, provider: LLMProviderName
    ) -> None:
        """Canonical means "the order this provider's layout declares" — the two
        differ, and sorting by the enum alone would only ever check one of them."""
        messages = await effective_context(
            tier,
            sources=RICH_SOURCES,
            prior_messages=list(STALE_THREAD),
            configurable_overrides={"provider": provider},
        )

        order = request_slot_order(provider)
        slots = slots_of(messages)
        assert slots == sorted(slots, key=order.index)

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


@pytest.mark.unit
class TestAnAssemblyDefectDegradesToAByteStableEmptyBlock:
    """The whole-assembly fallback is kept deliberately — a defect in the
    assembler must not cost a user their turn — and keeping it is what obliges
    proving it does exactly what it claims. Per-section failures are contained
    upstream, so this path only fires on a real defect, and every property below
    is one the fallback could silently get wrong: the block still has to hold
    the stable slot, and it has to be the SAME bytes every time or a persistent
    failure invalidates the prompt cache on every call on top of the original
    problem.
    """

    @staticmethod
    def _defective_gather() -> object:
        return patch(
            "app.agents.context.assemble._gather_sections",
            AsyncMock(side_effect=RuntimeError("assembler defect")),
        )

    async def test_the_turn_still_gets_a_context_and_it_is_empty(self) -> None:
        with self._defective_gather():
            assembled = await assemble_context(COMMS_CONTEXT)

        assert text_of(assembled.stable) == ""
        assert assembled.volatile is None
        assert assembled.messages() == [assembled.stable]

    async def test_the_empty_block_still_holds_the_stable_slot(self) -> None:
        """Unmarked it would not resolve to the slot, so the pruning node would
        leave a *stale* dynamic block from an earlier turn standing beside it —
        serving outdated identity rather than none."""
        with self._defective_gather():
            assembled = await assemble_context(COMMS_CONTEXT)

        assert slot_of(assembled.stable) is PromptSlot.DYNAMIC_STABLE
        assert assembled.stable.additional_kwargs[DYNAMIC_CONTEXT_MARKER] is True
        assert assembled.stable.additional_kwargs[LEGACY_DYNAMIC_MARKER] is True

    async def test_a_persistent_failure_produces_identical_bytes_every_call(self) -> None:
        with self._defective_gather():
            first = await assemble_context(COMMS_CONTEXT)
            second = await assemble_context(COMMS_CONTEXT)

        assert text_of(first.stable) == text_of(second.stable)
        assert first.stable.additional_kwargs == second.stable.additional_kwargs

    async def test_the_defect_reaches_the_wide_event_with_the_tier_and_user(self) -> None:
        """Silent degradation is what makes this fallback dangerous. An empty
        context looks exactly like a user with nothing stored, so the only way
        anyone learns it happened is this error — and it has to name the turn."""
        async with captured_wide_event() as event:
            with self._defective_gather():
                await assemble_context(COMMS_CONTEXT)

        assert event["errors"] == [
            {
                "msg": f"{LogTag.AGENT} Error assembling agent context",
                "error": "assembler defect",
                "error_type": "RuntimeError",
                "tier": COMMS_CONTEXT.tier.value,
                "user_id": COMMS_CONTEXT.user_id,
            }
        ]


@pytest.mark.unit
class TestTheGatherSlotsEachSectionWhereItDeclared:
    """The gather runs every section as one flat list and splits the results
    back apart by position. Nothing about that is self-checking: get the split
    wrong and per-turn content silently lands in the byte-stable prefix, which
    is the exact regression this whole package exists to prevent.
    """

    async def test_stable_and_volatile_content_do_not_cross_over(self) -> None:
        with fake_context_sources(RICH_SOURCES):
            assembled = await assemble_context(COMMS_CONTEXT)

        stable = text_of(assembled.stable)
        volatile = text_of(assembled.volatile)
        # "Prefers short answers" is a memory-core DOCUMENT: rewritten by the
        # consolidation pass, never per turn, so it declares the stable slot.
        # The core's agenda and activity journal are the churning half and are
        # split out into their own volatile section — see the sibling below.
        for declared_stable in ("Ada", "Asia/Kolkata", "Gmail", "Prefers short answers"):
            assert declared_stable in stable
            assert declared_stable not in volatile
        for declared_volatile in (
            "Ships on Fridays",
            "GAIA can run scheduled workflows",
            "ship the context refactor",
        ):
            assert declared_volatile in volatile
            assert declared_volatile not in stable

    async def test_the_memory_cores_churning_half_is_split_off_into_the_volatile_block(
        self,
    ) -> None:
        """``get_core_context`` renders the stable documents, the agenda and the
        activity journal as one string. The agenda's commitments move and the
        journal grows on every turn, so leaving them joined to the documents puts
        per-turn bytes inside the cached prefix — measured as ~10 points of comms
        hit rate before the split."""
        core = (
            "- Prefers short answers.\n\n"
            "## Current agenda\n- Ship the merge by Friday\n\n"
            "## Recent activity\n- Asked about the invoice at 14:02"
        )
        with fake_context_sources(replace(RICH_SOURCES, core_memory=core)):
            assembled = await assemble_context(COMMS_CONTEXT)

        stable = text_of(assembled.stable)
        volatile = text_of(assembled.volatile)
        assert "Prefers short answers" in stable
        assert "Current agenda" not in stable
        assert "Recent activity" not in stable
        assert "Ship the merge by Friday" in volatile
        assert "Asked about the invoice at 14:02" in volatile

    async def test_an_empty_section_leaves_no_blank_gap(self) -> None:
        """Sections that render nothing are dropped, not joined as empty
        strings — otherwise every absent section adds a stray separator and the
        block arrives padded with blank lines."""
        with fake_context_sources(ContextSources()):
            assembled = await assemble_context(COMMS_CONTEXT)

        assert text_of(assembled.stable) == "User Name: Ada\nUser Timezone: Asia/Kolkata"

    async def test_the_volatile_block_is_bounded_however_big_its_sections_get(self) -> None:
        """Sections are emitted whole; this is the backstop on their SUM, so one
        runaway section cannot blow the context window and the bill. Driven
        through the skills section because it is the one that can grow without
        bound — a user's whole installed skill list.
        """
        skills = "## Available skills\n" + "- inbox-triage\n" * 2000
        with fake_context_sources(replace(RICH_SOURCES, skills=skills)):
            assembled = await assemble_context(replace(COMMS_CONTEXT, tier=AgentTier.EXECUTOR))

        volatile = text_of(assembled.volatile)
        assert len(volatile) <= VOLATILE_BLOCK_MAX_CHARS + len(VOLATILE_BLOCK_TRUNC_MARKER)
        assert VOLATILE_BLOCK_TRUNC_MARKER in volatile

    async def test_a_volatile_block_exactly_at_the_cap_is_left_whole(self) -> None:
        """The ceiling truncates what exceeds it, not what exactly fills it."""
        skills = "S" * VOLATILE_BLOCK_MAX_CHARS
        with fake_context_sources(ContextSources(skills=skills)):
            assembled = await assemble_context(replace(COMMS_CONTEXT, tier=AgentTier.EXECUTOR))

        assert text_of(assembled.volatile) == skills

    async def test_an_oversized_volatile_block_keeps_head_and_tail_verbatim(self) -> None:
        """Over the ceiling: head + the exact truncation marker + tail, nothing
        else. The marker's own bytes are asserted whole — a marker that grew
        extra characters would still satisfy a substring check while changing
        what every request sends."""
        head = "H" * VOLATILE_BLOCK_HEAD_CHARS
        middle = "M" * 1_000
        tail = "T" * VOLATILE_BLOCK_TAIL_CHARS
        with fake_context_sources(ContextSources(skills=head + middle + tail)):
            assembled = await assemble_context(replace(COMMS_CONTEXT, tier=AgentTier.EXECUTOR))

        assert text_of(assembled.volatile) == f"{head}{VOLATILE_BLOCK_TRUNC_MARKER}{tail}"

    async def test_nothing_per_turn_to_say_means_no_volatile_message_at_all(self) -> None:
        """An empty volatile block would still occupy its slot and cost bytes."""
        with fake_context_sources(ContextSources()):
            assembled = await assemble_context(COMMS_CONTEXT)

        assert assembled.volatile is None
        assert assembled.messages() == [assembled.stable]


@pytest.mark.unit
class TestTheAssemblyIsRecordedOnTheWideEvent:
    """``dynamic_context`` is how anyone answers "what did the agent actually
    see?" for a turn that already happened. A wrong field here does not break a
    prompt, so nothing else would ever catch it — it just makes every later
    investigation quietly lie."""

    async def test_it_records_what_each_slot_received(self) -> None:
        async with captured_wide_event() as event:
            with fake_context_sources(RICH_SOURCES):
                assembled = await assemble_context(COMMS_CONTEXT)

        assert event["dynamic_context"] == {
            "tier": "comms",
            "source": "web",
            "has_core_memory": True,
            "has_memories": True,
            "has_gaia_knowledge": True,
            # Comms holds no file or shell tools, so it is given no skills.
            "has_skills": False,
            "has_active_todo": False,
            "execution_mode": "interactive",
            "stable_chars": len(text_of(assembled.stable)),
            "memory_recall_chars": len(text_of(assembled.volatile)),
            "has_memory_recall": True,
        }

    async def test_an_empty_assembly_is_recorded_as_empty(self) -> None:
        async with captured_wide_event() as event:
            with fake_context_sources(ContextSources()):
                await assemble_context(COMMS_CONTEXT)

        record = event["dynamic_context"]
        assert record["has_core_memory"] is False
        assert record["has_memories"] is False
        assert record["has_gaia_knowledge"] is False
        assert record["has_memory_recall"] is False
        assert record["memory_recall_chars"] == 0
        assert record["stable_chars"] > 0

    async def test_the_real_channel_is_recorded_when_there_is_one(self) -> None:
        """``web`` is the default for a turn with no channel, not a label to
        stamp on every turn — a Slack turn recorded as web is unfindable."""
        async with captured_wide_event() as event:
            with fake_context_sources(ContextSources()):
                await assemble_context(replace(COMMS_CONTEXT, source="slack"))

        assert event["dynamic_context"]["source"] == "slack"

    async def test_a_background_run_bound_to_a_todo_is_recorded_as_such(self) -> None:
        async with captured_wide_event() as event:
            with fake_context_sources(ContextSources()):
                await assemble_context(
                    replace(COMMS_CONTEXT, execution_mode="background", active_todo_id="todo-7")
                )

        record = event["dynamic_context"]
        assert record["execution_mode"] == "background"
        assert record["has_active_todo"] is True


@pytest.mark.unit
class TestEachBlockDeclaresItsOwnSlot:
    """``manage_system_prompts_node`` resolves a message to a slot by its
    marker, not by where it sits. An unmarked block is not recognised as the
    slot's holder, so the stale copy from the previous turn is never replaced —
    the thread stacks dynamic blocks and the cache prefix shatters, which is the
    exact regression the pruning node exists to prevent.
    """

    async def test_the_stable_block_declares_the_stable_slot(self) -> None:
        with fake_context_sources(RICH_SOURCES):
            assembled = await assemble_context(COMMS_CONTEXT)

        assert slot_of(assembled.stable) is PromptSlot.DYNAMIC_STABLE
        assert assembled.stable.additional_kwargs[DYNAMIC_CONTEXT_MARKER] is True

    async def test_the_stable_block_also_answers_to_the_pre_split_marker(self) -> None:
        """Threads checkpointed before the stable/volatile split carry only the
        legacy key; dropping it strands every one of them with an unresolvable
        block that never gets replaced."""
        with fake_context_sources(RICH_SOURCES):
            assembled = await assemble_context(COMMS_CONTEXT)

        assert assembled.stable.additional_kwargs[LEGACY_DYNAMIC_MARKER] is True

    async def test_the_volatile_block_declares_the_recall_slot(self) -> None:
        with fake_context_sources(RICH_SOURCES):
            assembled = await assemble_context(COMMS_CONTEXT)

        assert assembled.volatile is not None
        assert slot_of(assembled.volatile) is PromptSlot.MEMORY_RECALL
        assert assembled.volatile.additional_kwargs[MEMORY_RECALL_MARKER] is True


@pytest.mark.unit
class TestAWorkerTierRecordsItsOwnSections:
    """Comms is given no skills section at all, so the skills field can only be
    proven on a tier that actually has one — asserted on comms it would read as
    ``False`` whatever the code did."""

    async def test_the_executor_records_the_skills_it_was_given(self) -> None:
        async with captured_wide_event() as event:
            with fake_context_sources(RICH_SOURCES):
                await assemble_context(replace(COMMS_CONTEXT, tier=AgentTier.EXECUTOR))

        assert event["dynamic_context"]["tier"] == "executor"
        assert event["dynamic_context"]["has_skills"] is True

    async def test_comms_is_recorded_as_having_no_skills(self) -> None:
        async with captured_wide_event() as event:
            with fake_context_sources(RICH_SOURCES):
                await assemble_context(COMMS_CONTEXT)

        assert event["dynamic_context"]["has_skills"] is False
