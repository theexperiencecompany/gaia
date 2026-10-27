"""The ownership suite's own gates: each passes the right run and rejects the wrong one."""

from __future__ import annotations

from typing import Any

import pytest
from scripts.evals.core.types import Case, CaseRun
from scripts.evals.suites.ownership import (
    DELIVERED_KIND,
    executor_brief_gate,
    followup_gate,
    question_budget_gate,
    reply_brevity_gate,
)
from scripts.evals.suites.quality import REACTION_KIND

pytestmark = pytest.mark.unit

PROMPT = "remind me about the meeting"


def _case(**ownership: Any) -> Case:
    return Case(id="c", ticket="t", prompt=PROMPT, expected={"ownership": ownership})


def _run(
    *replies: dict[str, str],
    tool_calls: list[dict[str, Any]] | None = None,
    end_state: dict[str, Any] | None = None,
) -> CaseRun:
    messages = [{"role": "user", "content": PROMPT}, *replies]
    return CaseRun(
        case_id="c",
        messages=messages,
        tool_calls=tool_calls or [],
        end_state=end_state,
        text=" ".join(r["content"] for r in replies),
    )


def _say(text: str, kind: str = "") -> dict[str, str]:
    message = {"role": "assistant", "content": text}
    if kind:
        message["kind"] = kind
    return message


class TestQuestionBudget:
    def test_exactly_one_question_passes_an_ask_one_budget(self) -> None:
        case = _case(questions={"min": 1, "max": 1})

        assert question_budget_gate(case, _run(_say("Which meeting, the 3pm sync?"))) == 1.0

    def test_two_questions_fail_it(self) -> None:
        case = _case(questions={"min": 1, "max": 1})
        run = _run(_say("Which meeting? And what time?"))

        assert question_budget_gate(case, run) == 0.0

    def test_a_guess_with_no_question_fails_it(self) -> None:
        case = _case(questions={"min": 1, "max": 1})

        assert question_budget_gate(case, _run(_say("Reminder set for 3pm."))) == 0.0

    def test_only_the_reply_after_the_last_user_turn_counts(self) -> None:
        case = _case(questions={"min": 0, "max": 0})
        run = _run(_say("on it", REACTION_KIND), _say("Set for 6pm.", DELIVERED_KIND))

        assert question_budget_gate(case, run) == 1.0

    def test_a_reaction_alone_is_a_reply_with_no_questions(self) -> None:
        case = _case(questions={"min": 0, "max": 0})

        assert question_budget_gate(case, _run(_say("[reaction: 👋]", REACTION_KIND))) == 1.0

    def test_parroting_the_prompt_is_no_reply(self) -> None:
        case = _case(questions={"min": 0, "max": 1})

        assert question_budget_gate(case, _run(_say(PROMPT))) == 0.0

    def test_an_empty_run_fails(self) -> None:
        assert question_budget_gate(_case(questions={"min": 0, "max": 0}), _run()) == 0.0


class TestReplyBrevity:
    def test_within_budget_passes(self) -> None:
        assert reply_brevity_gate(_case(max_words=5), _run(_say("Set for 6pm."))) == 1.0

    def test_over_budget_fails(self) -> None:
        run = _run(_say("Here is a long answer that keeps going well past the budget."))

        assert reply_brevity_gate(_case(max_words=5), run) == 0.0


class TestFollowup:
    def test_required_passes_on_a_new_follow_up_that_wakes(self) -> None:
        case = _case(followup="required", followup_contains="visa")
        run = _run(
            _say("I'll nudge you Friday."),
            end_state={"followups": [{"id": "r", "title": "Visa documents", "wake": True}]},
        )

        assert followup_gate(case, run) == 1.0

    def test_required_fails_on_one_that_never_wakes(self) -> None:
        case = _case(followup="required", followup_contains="visa")
        run = _run(
            _say("On your list."),
            end_state={"followups": [{"id": "t", "title": "Visa documents", "wake": False}]},
        )

        assert followup_gate(case, run) == 0.0

    def test_forbidden_fails_on_any_new_follow_up(self) -> None:
        run = _run(
            _say("Noted."),
            end_state={"followups": [{"id": "r", "title": "Birthday", "wake": True}]},
        )

        assert followup_gate(_case(followup="forbidden"), run) == 0.0

    def test_forbidden_passes_when_nothing_was_created(self) -> None:
        run = _run(_say("Sounds lovely."), end_state={"followups": []})

        assert followup_gate(_case(followup="forbidden"), run) == 1.0

    def test_no_projection_is_never_a_pass(self) -> None:
        assert followup_gate(_case(followup="forbidden"), _run(_say("Noted."))) == 0.0


class TestExecutorBrief:
    def test_a_brief_with_the_specifics_and_a_done_state_passes(self) -> None:
        case = _case(brief={"terms": ["plumber"], "min_criteria": 1})
        call = {
            "name": "call_executor",
            "args": {"task": "Remind Alex at 6pm", "acceptance_criteria": ["plumber reminder set"]},
        }

        assert executor_brief_gate(case, _run(tool_calls=[call])) == 1.0

    def test_a_brief_missing_the_specific_fails(self) -> None:
        case = _case(brief={"terms": ["plumber"], "min_criteria": 1})
        call = {
            "name": "call_executor",
            "args": {"task": "Set a reminder", "acceptance_criteria": ["reminder set"]},
        }

        assert executor_brief_gate(case, _run(tool_calls=[call])) == 0.0

    def test_no_handoff_fails(self) -> None:
        case = _case(brief={"terms": [], "min_criteria": 1})

        assert executor_brief_gate(case, _run(_say("done"))) == 0.0
