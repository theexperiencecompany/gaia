"""Slot classification — the single place a message's position is decided."""

from typing import Any, ClassVar, cast

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage
import pytest

from app.agents.context.slots import (
    SINGLETON_SLOTS,
    TAIL_VOLATILE_SLOTS,
    PromptSlot,
    has_marker,
    mark,
    request_slot_order,
    slot_of,
)


@pytest.mark.unit
class TestSlotOf:
    def test_plain_system_message_is_static(self) -> None:
        assert slot_of(SystemMessage(content="prompt")) is PromptSlot.STATIC

    @pytest.mark.parametrize(
        ("marker", "expected"),
        [
            ("dynamic_context", PromptSlot.DYNAMIC_STABLE),
            ("memory_message", PromptSlot.DYNAMIC_STABLE),
            ("memory_recall", PromptSlot.MEMORY_RECALL),
            ("todo_context", PromptSlot.TODO_CONTEXT),
            ("executor_status", PromptSlot.EXECUTOR_STATUS),
            ("onboarding_context", PromptSlot.ONBOARDING),
        ],
    )
    def test_marker_selects_slot(self, marker: str, expected: PromptSlot) -> None:
        message = SystemMessage(content="x", additional_kwargs={marker: True})
        assert slot_of(message) is expected

    def test_background_executor_is_identified_by_name(self) -> None:
        """It carries no marker — the comms narrator builds it with no graph state."""
        message = SystemMessage(content="result", name="background_executor")
        assert slot_of(message) is PromptSlot.BACKGROUND_EXECUTOR

    def test_time_context_human_message_is_the_time_slot(self) -> None:
        message = HumanMessage(content="now", additional_kwargs={"time_context": True})
        assert slot_of(message) is PromptSlot.TIME

    def test_ordinary_turns_are_conversation(self) -> None:
        assert slot_of(HumanMessage(content="hi")) is PromptSlot.CONVERSATION
        assert slot_of(AIMessage(content="hello")) is PromptSlot.CONVERSATION

    def test_volatile_marker_wins_over_the_stable_one(self) -> None:
        """A block carrying both must be read as volatile, or per-turn content
        lands in the cacheable prefix — the defect this whole module exists for."""
        message = SystemMessage(
            content="x", additional_kwargs={"dynamic_context": True, "memory_recall": True}
        )
        assert slot_of(message) is PromptSlot.MEMORY_RECALL


@pytest.mark.unit
class TestMarkerReading:
    def test_marker_in_model_extra_still_resolves(self) -> None:
        """Checkpoints written before markers moved to additional_kwargs, and any
        marker passed as a bare constructor kwarg, land here instead."""

        class FakeMessage:
            additional_kwargs: ClassVar[dict[str, Any]] = {}
            model_extra: ClassVar[dict[str, Any]] = {"dynamic_context": True}

        message = cast(AnyMessage, FakeMessage())
        assert has_marker(message, "dynamic_context") is True
        assert slot_of(cast(AnyMessage, SystemMessage(content="x", memory_message=True))) is (
            PromptSlot.DYNAMIC_STABLE
        )

    def test_mark_writes_where_checkpointing_preserves_it(self) -> None:
        message = mark(SystemMessage(content="x"), "memory_recall")
        assert message.additional_kwargs["memory_recall"] is True


@pytest.mark.unit
class TestSlotOrder:
    def test_declaration_order_is_the_cache_contract(self) -> None:
        """Named explicitly rather than derived: this sequence is the thing the
        Gemini contiguity rule and the prompt cache both depend on, so a reorder
        must be a deliberate edit here, not a side effect of adding a member."""
        assert list(PromptSlot) == [
            PromptSlot.STATIC,
            PromptSlot.DYNAMIC_STABLE,
            PromptSlot.ONBOARDING,
            PromptSlot.TODO_CONTEXT,
            PromptSlot.BACKGROUND_EXECUTOR,
            PromptSlot.EXECUTOR_STATUS,
            PromptSlot.MEMORY_RECALL,
            PromptSlot.CONVERSATION,
            PromptSlot.TIME,
        ]

    def test_conversation_is_the_only_accumulating_slot(self) -> None:
        assert set(PromptSlot) - SINGLETON_SLOTS == {PromptSlot.CONVERSATION}


@pytest.mark.unit
class TestRequestSlotOrder:
    """Which layout a request gets, and why it may differ per provider."""

    @pytest.mark.parametrize("provider", ["openrouter", "custom"])
    def test_the_openai_wire_puts_every_per_turn_slot_behind_the_conversation(
        self, provider: str
    ) -> None:
        """The point of the whole layout: with the volatile slots behind it, the
        conversation sits inside the byte-stable prefix and the provider's
        implicit cache covers the history (97% vs 83% measured)."""
        assert request_slot_order(provider) == (
            PromptSlot.STATIC,
            PromptSlot.DYNAMIC_STABLE,
            PromptSlot.ONBOARDING,
            PromptSlot.CONVERSATION,
            PromptSlot.TODO_CONTEXT,
            PromptSlot.BACKGROUND_EXECUTOR,
            PromptSlot.EXECUTOR_STATUS,
            PromptSlot.MEMORY_RECALL,
            PromptSlot.TIME,
        )

    def test_gemini_keeps_the_leading_block_layout(self) -> None:
        """``langchain-google-genai`` drops every system message after the first
        non-system one, so a tail slot there is not a colder cache — it is content
        the model never sees."""
        assert request_slot_order("gemini") == tuple(PromptSlot)

    def test_an_unknown_or_missing_provider_gets_the_safe_layout(self) -> None:
        """The leading block is correct everywhere and merely colder; the tail
        layout is correct only where it has been verified. A configurable with no
        provider must therefore land on the safe one."""
        assert request_slot_order(None) == tuple(PromptSlot)
        assert request_slot_order("some-new-provider") == tuple(PromptSlot)

    def test_no_slot_is_lost_or_duplicated_by_the_reorder(self) -> None:
        """A layout that silently dropped a slot would delete that content from
        the request — the same failure mode as Gemini's contiguity rule."""
        for provider in ("openrouter", "gemini", None):
            order = request_slot_order(provider)
            assert sorted(order) == sorted(PromptSlot)

    def test_every_tail_volatile_slot_is_actually_moved(self) -> None:
        """Pins the set itself: adding a per-turn slot to the enum without adding
        it here leaves per-turn bytes inside the cached prefix, which is invisible
        except as a slow decay in the hit rate."""
        order = request_slot_order("openrouter")
        conversation_at = order.index(PromptSlot.CONVERSATION)
        assert {slot for slot in TAIL_VOLATILE_SLOTS} == {
            slot
            for slot in order[conversation_at + 1 :]
            if slot in SINGLETON_SLOTS and slot is not PromptSlot.TIME
        }
