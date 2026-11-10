"""The finish_task report contract: what the executor may say, and what it may not."""

from typing import Any

from pydantic import ValidationError
import pytest

from app.constants.agents import OutcomeState
from app.constants.task_report import (
    AnswerVerdict,
    FactKind,
    FailureReason,
    FailureRecovery,
    NeedsYouKind,
    TimeMeaning,
)
from app.models.task_report_models import FinishTaskArgs

pytestmark = pytest.mark.unit


def _args(**fields: Any) -> dict[str, Any]:
    return {"result": "the deliverable", **fields}


class TestOutcomeState:
    def test_the_merged_enum_lists_every_outcome(self) -> None:
        assert {state.value for state in OutcomeState} == {
            "done",
            "partial",
            "failed",
            "needs_you",
            "blocked",
            "schedule",
            "subscribe",
            "nothing_new",
            "no_action_needed",
            "unverified",
            "cancelled",
        }

    def test_ask_is_no_longer_an_outcome(self) -> None:
        with pytest.raises(ValidationError):
            FinishTaskArgs.model_validate(_args(outcome="ask"))


class TestFinishTaskArgs:
    def test_a_subagent_finish_needs_only_a_result(self) -> None:
        args = FinishTaskArgs.model_validate({"result": "data"})

        assert args.outcome is None
        assert args.facts == []
        assert args.answer is None

    def test_a_result_is_required(self) -> None:
        with pytest.raises(ValidationError):
            FinishTaskArgs.model_validate({"outcome": "done"})

    def test_a_full_report_round_trips(self) -> None:
        args = FinishTaskArgs.model_validate(
            _args(
                outcome="partial",
                facts=[
                    {
                        "text": "Sent the quote to the supplier.",
                        "kind": "did",
                        "source_call_ids": ["c1"],
                        "counterparty": "the supplier",
                        "unprompted": False,
                    },
                    {
                        "text": "The renewal is due.",
                        "kind": "observed",
                        "source_call_ids": ["c2"],
                        "time": {"at": "2026-11-20", "meaning": "due_by", "if_missed": "it lapses"},
                        "quote": "renews on 20 Nov",
                        "unprompted": True,
                    },
                ],
                answer={"recommendation": "take the cheaper one", "verdict": "mixed"},
                scope={"covered": "inbox, last 7 days", "complete": False, "gaps": ["spam folder"]},
                needs_you={
                    "kind": "choose",
                    "ask": "Which date works?",
                    "options": [{"label": "Mon", "consequence": "loses the discount"}],
                    "expires_at": "2026-11-12",
                },
                failure={"reason": "not_found", "recovery": "none"},
            )
        )

        assert args.outcome is OutcomeState.PARTIAL
        assert [fact.kind for fact in args.facts] == [FactKind.DID, FactKind.OBSERVED]
        assert args.facts[1].time is not None
        assert args.facts[1].time.meaning is TimeMeaning.DUE_BY
        assert args.facts[1].unprompted is True
        assert args.answer is not None
        assert args.answer.verdict is AnswerVerdict.MIXED
        assert args.scope is not None
        assert args.scope.gaps == ["spam folder"]
        assert args.needs_you is not None
        assert args.needs_you.kind is NeedsYouKind.CHOOSE
        assert args.failure is not None
        assert args.failure.reason is FailureReason.NOT_FOUND
        assert args.failure.recovery is FailureRecovery.NONE

    @pytest.mark.parametrize(
        "bad",
        [
            {"facts": [{"text": "x", "kind": "guessed"}]},
            {"facts": [{"text": "x", "kind": "did", "mood": "happy"}]},
            {"scope": {"covered": "x"}},
            {"needs_you": {"kind": "approve", "ask": "ok?"}},
            {"failure": {"reason": "bad_luck", "recovery": "none"}},
            {"answer": {"verdict": "maybe"}},
            {"unknown_field": 1},
        ],
    )
    def test_a_malformed_report_is_refused_not_repaired(self, bad: dict[str, Any]) -> None:
        with pytest.raises(ValidationError):
            FinishTaskArgs.model_validate(_args(**bad))

    def test_every_report_field_carries_its_rule_in_the_tool_schema(self) -> None:
        schema = FinishTaskArgs.model_json_schema()
        defs = schema["$defs"]

        top = schema["properties"]
        for name in ("result", "outcome", "facts", "answer", "scope", "needs_you", "failure"):
            assert "description" in top[name], name
        for model in ("ReportFact", "ReportScope", "ReportNeedsYou", "ReportFailure"):
            for field, prop in defs[model]["properties"].items():
                assert "description" in prop, f"{model}.{field}"
