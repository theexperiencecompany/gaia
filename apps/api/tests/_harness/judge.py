"""Stand-ins for the Judge: a verdict to build on, a scripted judge, and scripted pass answers.

The unit and timeline tests never reach a model: the Judge is a function the outbox calls, so
a test scripts what it said and asserts what the Rails and the ledger did with it.
"""

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from app.constants.outbox_judge import JudgeQuestion
from app.services.outbox.judge_models import (
    Deadline,
    JudgePass,
    JudgeVerdict,
    Moment,
    Relevance,
    Sensitivity,
)
from app.services.outbox.judge_verdict import ChoiceAnswer, PassAnswers
from app.services.outbox.models import (
    Initiative,
    NoticeOutcome,
    NoticeReport,
    OutboxReport,
    ProducerKind,
    Subject,
    SubjectKind,
    UrgencyClass,
)
from app.services.outbox.policy import urgency_of

NOW = datetime(2026, 11, 10, 9, 0, tzinfo=UTC)


def verdict(**overrides: Any) -> JudgeVerdict:
    """Build a verdict that says nothing remarkable: new, routine, not sensitive, decided by the Decisions pass."""
    fields: dict[str, Any] = {
        "urgency": UrgencyClass.ROUTINE,
        "deadline": Deadline.NONE,
        "relevance": Relevance.NEW,
        "sensitivity": Sensitivity.NONE,
        "audience_ok_for_group": True,
        "moment": Moment.OK,
        "suspicious": False,
        "reason": "scripted",
        "confidence": 0.9,
        "not_worth_probability": 0.0,
        "decided_by": JudgePass.DECISIONS,
    }
    return JudgeVerdict.model_validate({**fields, **overrides})


class ScriptedJudge:
    """Stands in for judge_report: says what it was told to about a report, else nothing remarkable."""

    def __init__(self) -> None:
        self.verdicts: dict[str, JudgeVerdict | None] = {}
        self.asked: list[str] = []

    async def __call__(self, report: OutboxReport) -> JudgeVerdict | None:
        self.asked.append(report.report_id)
        if report.report_id in self.verdicts:
            return self.verdicts[report.report_id]
        return verdict(urgency=urgency_of(report))


def choice(
    value: str, probabilities: Mapping[str, float] | None = None, confidence: float = 0.9
) -> ChoiceAnswer:
    """One question's answer."""
    return ChoiceAnswer(value, probabilities or {}, confidence)


def answers(**overrides: ChoiceAnswer) -> PassAnswers:
    """Answers to every question that say nothing remarkable; override any by question name."""
    base: dict[JudgeQuestion, ChoiceAnswer] = {
        JudgeQuestion.URGENCY: choice("routine"),
        JudgeQuestion.DEADLINE: choice("none"),
        JudgeQuestion.RELEVANCE: choice("new"),
        JudgeQuestion.SENSITIVITY: choice("none"),
        JudgeQuestion.MOMENT: choice("ok"),
        JudgeQuestion.AUTHENTICITY: choice("genuine"),
        JudgeQuestion.WORTH_TELLING: choice("yes", {"yes": 0.9, "no": 0.1}),
        JudgeQuestion.WITHIN_MINUTES: choice("no", {"yes": 0.1, "no": 0.9}),
        JudgeQuestion.BEFORE_CHECKIN: choice("no", {"yes": 0.1, "no": 0.9}),
    }
    base.update({JudgeQuestion(name): answer for name, answer in overrides.items()})
    return PassAnswers(answers=base)


def notice(**overrides: Any) -> NoticeReport:
    """Build a notice from a self-initiated producer: nothing the user said, no timing they chose."""
    fields: dict[str, Any] = {
        "report_id": "n1",
        "recipient": "6812f0b3c9a14e2b7d5a91cc",
        "producer": ProducerKind.TODO,
        "subject": Subject(kind=SubjectKind.TODO_RUN, id="s1", label="Weekly price check"),
        "occurred_at": NOW,
        "initiative": Initiative.SELF_INITIATED,
        "outcome": NoticeOutcome.INFO,
        "facts": ["The flight fell to 210 dollars."],
    }
    return NoticeReport.model_validate({**fields, **overrides})
