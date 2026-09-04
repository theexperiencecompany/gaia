"""Unit tests for `app.models.playbook_models` — the inline `$ask` slot.

The slot key is the address a written value is looked up by: the runner lists
it to the model that fills it and the evaluator substitutes by it, so a key
derived differently on either side is a hole reaching a real tool. The input
models are the tool boundary, lenient where a stray key is harmless and strict
exactly where silence would store less than the author wrote.
"""

from typing import Any

from pydantic import ValidationError
import pytest

from app.models.playbook_models import (
    DEFAULT_ASK_MAX_TOKENS,
    AskSlot,
    PlaybookHandoffStepInput,
    PlaybookStep,
    PlaybookStepInput,
    ask_slots,
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
            PlaybookStep(
                id="send",
                tool="send_mail",
                args={"body": [{"text": {"$ask": "the opening line"}}]},
            )
        ]

        located = ask_slots(steps)

        assert [item.key for item in located] == ["send.body.0.text"]
        assert located[0].slot.prompt == "the opening line"

    def test_a_step_without_an_id_is_addressed_by_its_tool_name(self) -> None:
        steps = [
            PlaybookStep(tool="web_search_tool", args={"query_text": {"$ask": "what to look up"}})
        ]

        assert [item.key for item in ask_slots(steps)] == ["web_search_tool.query_text"]

    def test_a_slot_inside_a_handoff_child_is_keyed_by_the_child_not_the_handoff(self) -> None:
        """A handoff's children are what actually call tools, and the evaluator
        fills args per child step. Keying by the handoff would look the value up
        under a prefix no step ever passes."""
        steps = [
            PlaybookStep(
                id="mail",
                handoff="gmail",
                steps=[
                    PlaybookStep(
                        id="fetch",
                        tool="GMAIL_FETCH_MESSAGES",
                        args={"query": {"$ask": "what to search the inbox for"}},
                    )
                ],
            )
        ]

        located = ask_slots(steps)

        assert [item.key for item in located] == ["fetch.query"]

    def test_a_step_with_neither_a_name_nor_a_tool_is_keyed_by_its_path_alone(self) -> None:
        """``exactly_one_shape`` forbids this step, so it only exists if one is
        conjured past validation (``model_construct``) — a stored document read
        back, say. The prefix then falls back to nothing, and the key is the
        argument path on its own; anything else spells a step name that no step
        answers to, and the written text is never substituted."""
        shapeless = PlaybookStep.model_construct(
            id="", tool=None, handoff=None, steps=[], args={"query": {"$ask": "what to look up"}}
        )

        assert [item.key for item in ask_slots([shapeless])] == [".query"]

    def test_slots_come_back_in_execution_order(self) -> None:
        steps = [
            PlaybookStep(id="first", tool="a", args={"x": {"$ask": "one"}}),
            PlaybookStep(
                id="handed",
                handoff="gmail",
                steps=[PlaybookStep(id="second", tool="b", args={"y": {"$ask": "two"}})],
            ),
            PlaybookStep(id="third", tool="c", args={"z": {"$ask": "three"}}),
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
