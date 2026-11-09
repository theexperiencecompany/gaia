"""Slot classification — the single place a message's position is decided."""

from typing import Any, ClassVar, cast

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage
import pytest

from app.agents.context.slots import (
    LEADING_SLOTS,
    PRESENCE_NOTE_MARKER,
    PromptSlot,
    has_marker,
    is_gaia_authored_note,
    mark,
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
            ("onboarding_context", PromptSlot.ONBOARDING),
        ],
    )
    def test_marker_selects_slot(self, marker: str, expected: PromptSlot) -> None:
        message = SystemMessage(content="x", additional_kwargs={marker: True})
        assert slot_of(message) is expected

    def test_a_background_report_written_as_a_system_message_is_conversation(self) -> None:
        """Older code wrote it as an unmarked system message; read as the static prompt, it would replace it."""
        message = SystemMessage(content="result", name="background_executor")
        assert slot_of(message) is PromptSlot.CONVERSATION

    def test_time_context_human_message_is_the_time_slot(self) -> None:
        message = HumanMessage(content="now", additional_kwargs={"time_context": True})
        assert slot_of(message) is PromptSlot.TIME

    def test_ordinary_turns_are_conversation(self) -> None:
        assert slot_of(HumanMessage(content="hi")) is PromptSlot.CONVERSATION
        assert slot_of(AIMessage(content="hello")) is PromptSlot.CONVERSATION

    def test_volatile_marker_wins_over_the_stable_one(self) -> None:
        """A block carrying both must be read as volatile, or per-turn content lands in the cacheable prefix."""
        message = SystemMessage(
            content="x", additional_kwargs={"dynamic_context": True, "memory_recall": True}
        )
        assert slot_of(message) is PromptSlot.MEMORY_RECALL


@pytest.mark.unit
class TestMarkerReading:
    def test_marker_in_model_extra_still_resolves(self) -> None:
        """Checkpoints written before markers moved to additional_kwargs land here instead."""

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
class TestTheLayout:
    def test_declaration_order_is_the_order_the_leading_slots_are_sent_in(self) -> None:
        assert list(PromptSlot) == [
            PromptSlot.STATIC,
            PromptSlot.DYNAMIC_STABLE,
            PromptSlot.ONBOARDING,
            PromptSlot.MEMORY_RECALL,
            PromptSlot.CONVERSATION,
            PromptSlot.TIME,
        ]

    def test_only_settings_driven_slots_lead(self) -> None:
        """A slot that changes per turn must never lead, or every turn re-bills the history."""
        assert {
            PromptSlot.STATIC,
            PromptSlot.DYNAMIC_STABLE,
            PromptSlot.ONBOARDING,
        } == LEADING_SLOTS


@pytest.mark.unit
class TestGaiaAuthoredNotes:
    """Per-turn text GAIA wrote is never the user's words: not summarized, not a request turn."""

    @pytest.mark.parametrize(
        "message",
        [
            mark(HumanMessage(content="[Surface change]"), PRESENCE_NOTE_MARKER),
            SystemMessage(content="recall", additional_kwargs={"memory_recall": True}),
            HumanMessage(content="[Current UTC Time]", additional_kwargs={"time_context": True}),
        ],
        ids=["presence", "recall", "clock"],
    )
    def test_turn_notes_are_gaia_authored(self, message: AnyMessage) -> None:
        assert is_gaia_authored_note(message)

    @pytest.mark.parametrize(
        "message",
        [
            HumanMessage(content="book the table"),
            AIMessage(content="done"),
            SystemMessage(content="static prompt"),
            SystemMessage(content="stable", additional_kwargs={"dynamic_context": True}),
        ],
        ids=["user", "reply", "static", "stable"],
    )
    def test_everything_else_is_not(self, message: AnyMessage) -> None:
        assert not is_gaia_authored_note(message)
