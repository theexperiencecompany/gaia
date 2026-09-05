"""Unit tests for `app.models.playbook_models` — the inline `$ask` slot.

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
    PlaybookHandoffStepInput,
    PlaybookStep,
    PlaybookStepInput,
    TimeSlot,
    ToolStep,
    ask_slots,
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
        """A handoff's children are what actually call tools, and the evaluator
        fills args per child step. Keying by the handoff would look the value up
        under a prefix no step ever passes."""
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


class TestPlaybookStepInput:
    def test_unknown_keys_are_dropped_instead_of_refusing_the_write(self) -> None:
        """17 of 57 production authoring attempts were thrown away whole for a
        ``goal`` beside an otherwise correct call."""
        step = PlaybookStepInput.model_validate(
            {"id": "agenda", "tool": "list_events", "goal": "read", "note": "daily"}
        )

        assert step.to_step().model_dump(exclude_defaults=True) == {
            "id": "agenda",
            "tool": "list_events",
        }

    @pytest.mark.parametrize(
        "step",
        [
            {"id": "agenda", "tool": "list_events", "handoff": "gmail"},
            {"id": "agenda"},
        ],
        ids=["both", "neither"],
    )
    def test_a_node_is_a_tool_call_or_a_handoff_and_never_both_or_neither(
        self, step: dict[str, Any]
    ) -> None:
        """The one rule still worth failing a write over: a malformed node means
        the runner would silently skip a step instead of running it."""
        with pytest.raises(ValidationError, match="exactly one of"):
            PlaybookStepInput.model_validate(step)


class TestPlaybookHandoffStepInput:
    @pytest.mark.parametrize(
        ("child", "named"),
        [
            (
                {"id": "mail", "tool": "list_events", "steps": [{"id": "x", "tool": "y"}]},
                "steps",
            ),
            ({"id": "mail", "tool": "list_events", "handoff": "todos"}, "handoff"),
            (
                {"id": "mail", "tool": "list_events", "handoff": "todos", "steps": []},
                "handoff or steps",
            ),
        ],
        ids=["steps", "handoff", "both"],
    )
    def test_a_child_that_nests_a_level_deeper_is_refused_by_name(
        self, child: dict[str, Any], named: str
    ) -> None:
        """The child model drops unknown keys, and ``steps``/``handoff`` ARE
        unknown to it. Without this rule a grandchild delegation is discarded
        silently and the stored playbook runs less than the author wrote while
        reporting success. The message has to name which key, or the author
        cannot tell nesting from a typo."""
        with pytest.raises(ValidationError) as raised:
            PlaybookHandoffStepInput.model_validate(child)

        assert (
            f"a handoff's child is one tool call and cannot carry {named}: playbooks are "
            "one level deep, so list the calls that subagent made as the handoff's own steps"
        ) in str(raised.value)

    def test_a_stray_annotation_on_a_child_is_still_dropped(self) -> None:
        """The refusal above is exactly two keys wide: a ``goal`` on a child is
        the same harmless annotation it is on a top-level step."""
        child = PlaybookHandoffStepInput.model_validate(
            {"id": "mail", "tool": "list_events", "goal": "read the agenda"}
        )

        assert child.to_step().model_dump(exclude_defaults=True) == {
            "id": "mail",
            "tool": "list_events",
        }


class TestArgsSpelledRight:
    """``args`` under another name is dropped as unknown, and the step then
    stores a call with no arguments at all while reporting a successful write."""

    @pytest.mark.parametrize(
        "near_miss",
        ["arguments", "input", "inputs", "params", "parameters", "kwargs"],
    )
    @pytest.mark.parametrize(
        "model",
        [PlaybookStepInput, PlaybookHandoffStepInput],
        ids=["top-level", "handoff-child"],
    )
    def test_arguments_under_another_name_are_refused_by_that_name(
        self, model: type[PlaybookStepInput] | type[PlaybookHandoffStepInput], near_miss: str
    ) -> None:
        with pytest.raises(ValidationError) as raised:
            model.model_validate({"id": "mail", "tool": "send_email", near_miss: {"to": "a@b.com"}})

        assert f"a step's arguments go under 'args', not {near_miss!r}; rename it" in str(
            raised.value
        )

    @pytest.mark.parametrize(
        "model",
        [PlaybookStepInput, PlaybookHandoffStepInput],
        ids=["top-level", "handoff-child"],
    )
    def test_a_stray_alias_beside_real_args_is_dropped_not_refused(
        self, model: type[PlaybookStepInput] | type[PlaybookHandoffStepInput]
    ) -> None:
        """The refusal is about arguments going missing. With ``args`` present
        nothing is lost, so the extra key is the same harmless annotation any
        other unknown key is."""
        step = model.model_validate(
            {
                "id": "mail",
                "tool": "send_email",
                "args": {"to": "a@b.com"},
                "arguments": {"to": "z@z.com"},
            }
        )

        assert step.args == {"to": "a@b.com"}


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
        """The parser reports a bad slot to the author from this failure, and
        the budget bound is what keeps one replay from turning into an unbounded
        generation — the whole point of freezing a sequence is a bounded cost."""
        with pytest.raises(ValidationError):
            AskSlot.model_validate(value)


@pytest.mark.unit
class TestStepInputBecomesAStep:
    """The authoring input converts to exactly the executed step, and refuses
    a loop without its ceiling naming the step."""

    def test_a_repeating_call_keeps_every_field(self) -> None:
        step = PlaybookStepInput(
            id="mails",
            tool="send_email",
            args={"to": "$item"},
            for_each="$steps.events.ids",
            max_items=5,
        ).to_step()
        assert step == ForEachStep(
            id="mails",
            tool="send_email",
            args={"to": "$item"},
            for_each="$steps.events.ids",
            max_items=5,
        )

    def test_a_handoff_keeps_its_id_and_converts_every_child(self) -> None:
        step = PlaybookStepInput(
            id="sweep",
            handoff="calendar",
            steps=[PlaybookHandoffStepInput(id="agenda", tool="list_events")],
        ).to_step()
        assert step == HandoffStep(
            id="sweep",
            handoff="calendar",
            steps=[ToolStep(id="agenda", tool="list_events", args={})],
        )

    @pytest.mark.parametrize(("step_id", "named"), [("mails", "mails"), ("", "send_email")])
    def test_a_loop_without_a_ceiling_is_refused_naming_the_step(
        self, step_id: str, named: str
    ) -> None:
        step = PlaybookStepInput(id=step_id, tool="send_email", for_each="$steps.events.ids")
        with pytest.raises(ValueError) as raised:
            step.to_step()
        assert str(raised.value) == (
            f"step {named}: for_each needs max_items, at most 25, so the replay's cost is "
            "known before it runs"
        )

    @pytest.mark.parametrize(("step_id", "named"), [("mails", "mails"), ("", "<unnamed>")])
    def test_a_ceiling_without_a_loop_is_refused_naming_the_step(
        self, step_id: str, named: str
    ) -> None:
        with pytest.raises(ValidationError) as raised:
            PlaybookStepInput(id=step_id, tool="send_email", max_items=3)
        assert f"step {named}: max_items only means something with for_each" in str(raised.value)

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
