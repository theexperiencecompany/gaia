"""Unit tests for app.models.playbook_models — the inline $ask slot.

The slot key is the address a written value is looked up by: the runner lists
it to the model that fills it and the evaluator substitutes by it, so a key
derived differently on either side is a hole reaching a real tool. The input
models are the tool boundary, lenient where a stray key is harmless and strict
exactly where silence would store less than the author wrote.
"""

from typing import Any

from pydantic import TypeAdapter, ValidationError
import pytest

from app.models.playbook_models import (
    DEFAULT_ASK_MAX_TOKENS,
    AskSlot,
    ForEachStep,
    HandoffStep,
    PlaybookAskAnswer,
    PlaybookStep,
    TimeSlot,
    ToolStep,
    ask_slots,
    is_read_call,
    is_work_call,
    walk_ask_slots,
)


class TestAskSlotKeys:
    """The key one slot answers to.

    The runner lists these keys to the model that writes the values and the
    evaluator substitutes by the same key. A key derived differently on either
    side is a slot that is written and never substituted, so the raw slot dict
    reaches a real tool.
    """

    def test_a_nested_argument_path_is_spelled_out_from_the_step_id(self) -> None:
        steps = [
            ToolStep(
                id="send",
                tool="send_mail",
                args={"body": [{"text": {"$ask": "the opening line"}}]},
            )
        ]

        located = ask_slots(steps)

        assert [item.key for item in located] == ["send.body.0.text"]
        assert located[0].slot.prompt == "the opening line"

    def test_a_step_without_an_id_is_addressed_by_its_tool_name(self) -> None:
        steps = [ToolStep(tool="web_search_tool", args={"query_text": {"$ask": "what to look up"}})]

        assert [item.key for item in ask_slots(steps)] == ["web_search_tool.query_text"]

    def test_a_slot_inside_a_handoff_child_is_keyed_by_the_child_not_the_handoff(self) -> None:
        """Keying by the handoff would look the value up under a prefix no step ever passes."""
        steps = [
            HandoffStep(
                id="mail",
                handoff="gmail",
                steps=[
                    ToolStep(
                        id="fetch",
                        tool="GMAIL_FETCH_MESSAGES",
                        args={"query": {"$ask": "what to search the inbox for"}},
                    )
                ],
            )
        ]

        located = ask_slots(steps)

        assert [item.key for item in located] == ["fetch.query"]

    def test_slots_come_back_in_execution_order(self) -> None:
        steps = [
            ToolStep(id="first", tool="a", args={"x": {"$ask": "one"}}),
            HandoffStep(
                id="handed",
                handoff="gmail",
                steps=[ToolStep(id="second", tool="b", args={"y": {"$ask": "two"}})],
            ),
            ToolStep(id="third", tool="c", args={"z": {"$ask": "three"}}),
        ]

        assert [item.key for item in ask_slots(steps)] == ["first.x", "second.y", "third.z"]


class TestAskSlot:
    def test_the_prompt_is_read_from_the_dollar_ask_key(self) -> None:
        assert AskSlot.model_validate({"$ask": "what to write"}).prompt == "what to write"
        assert AskSlot.model_validate({"$ask": "what to write"}).max_tokens == (
            DEFAULT_ASK_MAX_TOKENS
        )

    @pytest.mark.parametrize(
        "value",
        [
            {"$ask": "what to write", "uses": ["agenda"]},
            {"$ask": "what to write", "prompt": "again"},
            {"$ask": ""},
            {"$ask": "what to write", "max_tokens": 0},
            {"$ask": "what to write", "max_tokens": 8193},
        ],
        ids=["legacy-uses", "aliased-name", "empty-prompt", "zero-budget", "over-budget"],
    )
    def test_a_slot_that_is_not_exactly_a_prompt_and_a_budget_is_refused(
        self, value: dict[str, Any]
    ) -> None:
        """The budget bound keeps one replay from turning into an unbounded generation."""
        with pytest.raises(ValidationError):
            AskSlot.model_validate(value)


@pytest.mark.unit
class TestForEachSourceShape:
    """A loop source is the whole value: one placeholder or one ask slot."""

    def test_a_loop_source_woven_into_prose_is_refused_with_the_reason(self) -> None:
        with pytest.raises(ValidationError) as raised:
            ForEachStep(id="s", tool="t", args={}, for_each="overdue-$steps.list", max_items=2)
        assert (
            "for_each must be the whole value, either one placeholder naming a list "
            "($steps.<step_id>.<field>) or an $ask slot, but it is 'overdue-$steps.list'; a "
            "placeholder inside a longer string resolves to text, and text is not a list"
        ) in str(raised.value)


@pytest.mark.unit
class TestStoredDocuments:
    def test_a_handoff_document_carries_its_id_only_when_it_has_one(self) -> None:
        child = ToolStep(id="agenda", tool="list_events", args={"calendar_id": "primary"})
        named = HandoffStep(id="sweep", handoff="calendar", steps=[child]).to_document()
        unnamed = HandoffStep(handoff="calendar", steps=[child]).to_document()
        assert named == {
            "id": "sweep",
            "handoff": "calendar",
            "steps": [{"id": "agenda", "tool": "list_events", "args": {"calendar_id": "primary"}}],
        }
        assert "id" not in unnamed

    def test_an_ask_source_is_stored_without_its_defaults(self) -> None:
        step = ForEachStep(
            id="s",
            tool="t",
            args={},
            for_each=AskSlot.model_validate({"$ask": "pick the overdue ones"}),
            max_items=2,
        )
        assert step.to_document()["for_each"] == {"$ask": "pick the overdue ones"}

    def test_nulls_and_an_empty_child_list_read_as_unset(self) -> None:
        """Documents from before the step variants carry every field."""
        stored = {
            "id": "agenda",
            "tool": "list_events",
            "args": {},
            "handoff": None,
            "for_each": None,
            "max_items": None,
            "steps": [],
        }
        assert TypeAdapter(PlaybookStep).validate_python(stored) == ToolStep(
            id="agenda", tool="list_events", args={}
        )

    def test_a_step_that_is_already_a_model_passes_through(self) -> None:
        step = ToolStep(id="agenda", tool="list_events", args={})
        assert TypeAdapter(PlaybookStep).validate_python(step) is step


@pytest.mark.unit
class TestTimeSlot:
    @pytest.mark.parametrize("placeholder", ["$now", " $today + 1d 09:00 ", "$now - 2h"])
    def test_a_time_root_with_an_optional_offset_and_clock_is_a_time(
        self, placeholder: str
    ) -> None:
        slot = TimeSlot.model_validate({"$time": placeholder, "format": "%Y"})
        assert slot.placeholder == placeholder.strip()

    @pytest.mark.parametrize("placeholder", ["$trigger", "$trigger.when", "$now.hour", "hello"])
    def test_anything_else_is_refused_with_the_grammar(self, placeholder: str) -> None:
        with pytest.raises(ValidationError) as raised:
            TimeSlot.model_validate({"$time": placeholder, "format": "%Y"})
        assert (
            "$time takes one time placeholder ($now or $today, with an optional offset and "
            f"clock such as $today + 1d 09:00), not {placeholder!r}"
        ) in str(raised.value)

    def test_a_layout_has_to_carry_a_field(self) -> None:
        with pytest.raises(ValidationError) as raised:
            TimeSlot.model_validate({"$time": "$now", "format": "year"})
        assert "format 'year' carries no strftime field" in str(raised.value)

    def test_a_time_slot_is_a_leaf_for_the_ask_walk(self) -> None:
        assert list(walk_ask_slots({"$time": {"$ask": "when"}, "format": "%Y"})) == []


@pytest.mark.unit
class TestAskAnswerKinds:
    @pytest.mark.parametrize(
        "answer",
        [{"name": "mail.body"}, {"name": "mail.body", "text": "hi", "items": ["a"]}],
        ids=["neither", "both"],
    )
    def test_an_answer_is_text_or_items_never_both_or_neither(self, answer: dict[str, Any]) -> None:
        with pytest.raises(ValidationError) as raised:
            PlaybookAskAnswer.model_validate(answer)
        assert (
            "mail.body: answer with text, or with items for a for_each slot, not both and "
            "not neither"
        ) in str(raised.value)


@pytest.mark.unit
class TestIsWorkCall:
    @pytest.mark.parametrize(
        ("tool_name", "expected"),
        [
            ("send_email", True),
            ("GMAIL-SEND-EMAIL", True),
            ("create_todo", True),
            ("list_todos", False),
            ("GMAIL_FETCH_MESSAGES", False),
        ],
    )
    def test_a_call_is_work_when_one_part_of_its_name_is_a_doing_verb(
        self, tool_name: str, expected: bool
    ) -> None:
        assert is_work_call(tool_name) is expected


@pytest.mark.parametrize(
    ("tool", "reads"),
    [
        ("GMAIL_FETCH_MESSAGES", True),
        ("gmail-fetch-messages", True),
        ("list_todos", True),
        ("search_and_delete_mail", False),
        ("file_notes", False),
        ("GMAIL_SEND_EMAIL", False),
    ],
)
def test_a_call_reads_only_with_a_read_verb_and_no_work_verb(tool: str, reads: bool) -> None:
    assert is_read_call(tool) is reads
