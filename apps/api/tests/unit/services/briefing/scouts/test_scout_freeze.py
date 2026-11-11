"""Matching a scout report's steps back to the calls its learn run made."""

from datetime import datetime
from typing import Any

from langchain_core.messages import AIMessage, ToolMessage
import pytest

from app.models.playbook_models import ToolStep
from app.services.briefing.scouts.freeze import LearnCall, freeze_sources, learn_calls
from app.services.workflow.playbook.parser import RecordedResult


def _ai(*calls: tuple[str, dict[str, object], str]) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": args, "id": call_id} for name, args, call_id in calls],
    )


def _step(tool: str = "list", **args: object) -> ToolStep:
    return ToolStep(id="s", tool=tool, args=args)


def _call(tool: str = "list", result: object = None, **args: object) -> LearnCall:
    return LearnCall(tool_name=tool, args=args, result=result)


class TestLearnCalls:
    def test_an_answered_call_carries_its_tool_args_and_parsed_answer(self) -> None:
        messages = [
            _ai(("list", {"q": "me"}, "c1")),
            ToolMessage(content='{"items": [1]}', tool_call_id="c1"),
        ]

        assert learn_calls(messages) == [_call("list", {"items": [1]}, q="me")]

    def test_a_non_text_answer_is_parsed_from_its_json_with_odd_values_as_text(self) -> None:
        when = datetime(2026, 1, 2, 3, 4, 5)
        blocks: list[str | dict[str, Any]] = [{"type": "text", "text": "hi", "when": when}]
        messages = [_ai(("list", {}, "c1")), ToolMessage(content=blocks, tool_call_id="c1")]

        [call] = learn_calls(messages)

        assert call.result == [{"type": "text", "text": "hi", "when": "2026-01-02 03:04:05"}]

    def test_only_named_answered_calls_count_in_call_order(self) -> None:
        messages = [
            _ai(("", {}, "nameless"), ("unanswered", {}, "c9"), ("first", {"a": 1}, "c1")),
            ToolMessage(content="plain text", tool_call_id="nameless"),
            ToolMessage(content="ok", tool_call_id="c1"),
            _ai(("second", {}, "c2")),
            ToolMessage(content="[]", tool_call_id="c2"),
        ]

        assert learn_calls(messages) == [
            _call("first", "ok", a=1),
            _call("second", []),
        ]


class TestFreezeSources:
    def test_the_last_agreeing_call_wins_and_a_call_answers_one_step_only(self) -> None:
        calls = [_call(result=n, q="x") for n in range(3)]

        sources = freeze_sources([_step(q="x"), _step(q="x")], calls)

        assert sources == [
            RecordedResult(args={"q": "x"}, result=2),
            RecordedResult(args={"q": "x"}, result=1),
        ]

    def test_a_step_for_a_tool_that_never_ran_says_so(self) -> None:
        assert freeze_sources([_step("other")], [_call()]) == (
            "steps[0]: other did not run in this run; a playbook freezes calls "
            "that ran and produced their result — run it, or drop the step"
        )

    def test_a_step_whose_calls_earlier_steps_froze_says_so(self) -> None:
        assert freeze_sources([_step(), _step()], [_call()]) == (
            "steps[1]: list ran 1 time(s) in this run and earlier steps froze "
            "every one of them; a step cannot replay a call the run did not make — drop "
            "this step, or run it again"
        )

    def test_a_step_whose_args_no_call_used_names_the_last_call_left(self) -> None:
        calls = [_call(q="a"), _call(q="b")]

        assert freeze_sources([_step(q="z")], calls) == (
            "steps[0]: list ran 2 time(s) in this run, but never with these args "
            '(the last call used {"q": "b"}); freeze the call that ran, '
            "with the args that produced its result, or run it with these args"
        )

    def test_every_unmatched_step_is_named_in_order(self) -> None:
        problem = (
            "{} did not run in this run; a playbook freezes calls "
            "that ran and produced their result — run it, or drop the step"
        )

        assert freeze_sources([_step("a"), _step("b")], []) == (
            f"steps[0]: {problem.format('a')}; steps[1]: {problem.format('b')}"
        )


def _agrees(step_value: object, recorded_value: object) -> bool:
    return isinstance(freeze_sources([_step(v=step_value)], [_call(v=recorded_value)]), list)


class TestArgsAgreement:
    @pytest.mark.parametrize(
        ("step_value", "recorded_value"),
        [
            ({"$ask": "who?"}, "ana"),
            ({"$time": "now"}, "2026-01-01"),
            ("$steps.a.id", 5),
            ("PR $steps.a.id", "PR 7"),
            ("ana", "ana"),
            ({"k": "v"}, {"k": "v", "extra": 1}),
            ({"k": {"n": 1}}, {"k": {"n": 1}}),
            (["a", {"k": 1}], ["a", {"k": 1}]),
            ([], []),
            (5, 5),
            (True, True),
        ],
    )
    def test_a_step_value_the_recorded_one_could_be(
        self, step_value: object, recorded_value: object
    ) -> None:
        assert _agrees(step_value, recorded_value)

    @pytest.mark.parametrize(
        ("step_value", "recorded_value"),
        [
            ("PR $steps.a.id", 7),
            ("ana", "bo"),
            ("ana", 5),
            ({"k": "v"}, {"k": "w"}),
            ({"k": "v"}, {"other": "v"}),
            ({"k": "v"}, "v"),
            ({"a": 1, "b": 2}, {"a": 1}),
            ({"a": 1, "b": 2}, {"a": 9, "b": 2}),
            (["a", "b"], ["a"]),
            (["a"], ["a", "b"]),
            (["a", "b"], ["a", "c"]),
            (["a"], "a"),
            ([], {}),
            (5, 6),
            (True, False),
        ],
    )
    def test_a_step_value_the_recorded_one_could_not_be(
        self, step_value: object, recorded_value: object
    ) -> None:
        assert not _agrees(step_value, recorded_value)
