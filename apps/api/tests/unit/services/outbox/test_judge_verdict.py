"""Reading the Judge's answers into a verdict: the thresholds, the deadline instants, and what is refused."""

from datetime import UTC, datetime

import pytest

from app.constants.outbox_judge import JudgeQuestion
from app.models.quiet_hours_models import DEFAULT_QUIET_HOURS
from app.services.outbox.judge_models import (
    Deadline,
    JudgePass,
    JudgeVerdict,
    Moment,
    ReasoningAnswer,
    Relevance,
    Sensitivity,
)
from app.services.outbox.judge_verdict import (
    ChoiceAnswer,
    JudgeAnswerError,
    PassAnswers,
    UserClock,
    answers_from_reasoning,
    build_verdict,
    deliver_by,
)
from app.services.outbox.models import UrgencyClass
from app.utils.timezone import Timezone
from tests._harness.judge import NOW, answers, choice

IST = UserClock(Timezone.parse("Asia/Kolkata"), DEFAULT_QUIET_HOURS)


def _read(passed: PassAnswers, runs: frozenset[str] = frozenset()) -> JudgeVerdict:
    return build_verdict(
        passed,
        decided_by=JudgePass.DECISIONS,
        decisions_confidence=0.9,
        now=NOW,
        clock=IST,
        offered_runs=runs,
    )


def _yes(p: float) -> ChoiceAnswer:
    return choice("yes", {"yes": p, "no": 1 - p})


@pytest.mark.parametrize(
    ("minutes", "checkin", "expected"),
    [
        (0.45, 0.0, UrgencyClass.INTERRUPT),
        (0.44, 0.0, UrgencyClass.ROUTINE),
        (0.1, 0.5, UrgencyClass.TIMELY),
        (0.1, 0.49, UrgencyClass.ROUTINE),
        (0.9, 0.9, UrgencyClass.INTERRUPT),
    ],
)
def test_urgency_is_read_from_the_two_yes_no_decisions(
    minutes: float, checkin: float, expected: UrgencyClass
) -> None:
    passed = answers(
        within_minutes=_yes(minutes),
        before_checkin=_yes(checkin),
    )

    assert _read(passed).urgency is expected


def test_what_neither_decision_asks_for_is_routine_or_background_by_the_urgency_vote() -> None:
    routine = answers(urgency=choice("routine", {"routine": 0.5, "background": 0.4}))
    background = answers(urgency=choice("background", {"routine": 0.3, "background": 0.6}))

    assert _read(routine).urgency is UrgencyClass.ROUTINE
    assert _read(background).urgency is UrgencyClass.BACKGROUND


@pytest.mark.parametrize(("p_no", "relevance"), [(0.45, Relevance.MOOT), (0.44, Relevance.NEW)])
def test_not_worth_telling_starts_at_the_measured_threshold(
    p_no: float, relevance: Relevance
) -> None:
    passed = answers(
        worth_telling=choice("no", {"yes": 1 - p_no, "no": p_no}),
        relevance=choice("moot", {"moot": 0.9, "new": 0.1}),
    )

    verdict = _read(passed)

    assert verdict.relevance is relevance
    assert verdict.not_worth_probability == pytest.approx(p_no)


def test_the_reason_it_is_not_worth_telling_is_the_likeliest_one() -> None:
    passed = answers(
        worth_telling=choice("no", {"yes": 0.1, "no": 0.9}),
        relevance=choice(
            "superseded", {"new": 0.1, "moot": 0.2, "superseded": 0.5, "already_known": 0.2}
        ),
    )

    assert _read(passed).relevance is Relevance.SUPERSEDED


def test_not_worth_telling_with_no_reason_named_is_moot() -> None:
    passed = answers(
        worth_telling=choice("no", {"yes": 0.1, "no": 0.9}),
        relevance=choice("new", {"new": 1.0}),
    )

    assert _read(passed).relevance is Relevance.MOOT


@pytest.mark.parametrize(("p", "suspicious"), [(0.5, True), (0.49, False)])
def test_suspicious_starts_at_the_measured_threshold(p: float, suspicious: bool) -> None:
    passed = answers(authenticity=choice("suspicious", {"suspicious": p, "genuine": 1 - p}))

    assert _read(passed).suspicious is suspicious


def test_a_group_may_hear_only_what_is_not_sensitive() -> None:
    assert _read(answers(sensitivity=choice("none"))).audience_ok_for_group is True
    assert _read(answers(sensitivity=choice("personal"))).audience_ok_for_group is False


def test_sensitivity_and_moment_are_what_the_judge_chose() -> None:
    verdict = _read(answers(sensitivity=choice("health"), moment=choice("soften")))

    assert (verdict.sensitivity, verdict.moment) == (Sensitivity.HEALTH, Moment.SOFTEN)


def test_the_gate_confidence_is_the_least_confident_decision_question() -> None:
    passed = answers(
        worth_telling=choice("yes", {"yes": 0.9}, confidence=0.8),
        within_minutes=choice("no", {"no": 0.9}, confidence=0.4),
        before_checkin=choice("no", {"no": 0.9}, confidence=0.9),
        authenticity=choice("genuine", confidence=0.95),
        urgency=choice("routine", confidence=0.0),
    )

    assert passed.gate_confidence() == pytest.approx(0.4)


def test_an_answer_with_no_confidence_does_not_pass_the_gate() -> None:
    passed = answers(within_minutes=choice("no", {"no": 0.9}, confidence=None))

    assert passed.gate_confidence() == 0.0


def test_a_missing_answer_raises() -> None:
    passed = PassAnswers(answers={})

    with pytest.raises(JudgeAnswerError, match="worth_telling"):
        _read(passed)


@pytest.mark.parametrize(
    ("deadline", "expected"),
    [
        (Deadline.WITHIN_1H, datetime(2026, 11, 10, 10, 0, tzinfo=UTC)),
        # 14:30 IST: the day's sleep hour, 22:00 IST, is 16:30 UTC.
        (Deadline.WITHIN_TODAY, datetime(2026, 11, 10, 16, 30, tzinfo=UTC)),
        # The next 08:00 IST is the morning of the 11th: 02:30 UTC.
        (Deadline.BEFORE_NEXT_MORNING, datetime(2026, 11, 11, 2, 30, tzinfo=UTC)),
        (Deadline.LATER, None),
        (Deadline.NONE, None),
    ],
)
def test_a_deadline_bucket_is_an_instant_on_the_users_own_clock(
    deadline: Deadline, expected: datetime | None
) -> None:
    assert deliver_by(deadline, NOW, IST) == expected


def test_a_deadline_already_past_for_today_is_now() -> None:
    late = datetime(2026, 11, 10, 17, 0, tzinfo=UTC)

    assert deliver_by(Deadline.WITHIN_TODAY, late, IST) == late


def test_a_wait_for_an_offered_run_is_kept() -> None:
    passed = answers(wait_for_run=choice("workflow:wf_1"))

    assert _read(passed, frozenset({"workflow:wf_1"})).wait_for_run == "workflow:wf_1"


def test_a_wait_for_a_run_that_was_not_offered_raises() -> None:
    with pytest.raises(JudgeAnswerError, match="not offered"):
        _read(answers(wait_for_run=choice("workflow:ghost")), frozenset({"workflow:wf_1"}))


def test_no_wait_is_none() -> None:
    assert _read(answers(wait_for_run=choice("none")), frozenset({"x"})).wait_for_run is None


def _reasoning(**overrides: object) -> ReasoningAnswer:
    fields: dict[str, object] = {
        "urgency": "routine",
        "deadline": "within_today",
        "relevance": "new",
        "sensitivity": "finance",
        "moment": "ok",
        "authenticity": "genuine",
        "worth_telling": "yes",
        "within_minutes": "no",
        "before_checkin": "yes",
        "wait_for_run": None,
        "reason": "A card decline needs a fix today.",
        "relevance_ref": None,
        "same_fact_key": "card-decline-0412",
        "corrects": None,
        "valid_until": datetime(2026, 11, 11, tzinfo=UTC),
        "topics": ["money"],
        "rules_applied": ["money alerts matter"],
    }
    return ReasoningAnswer.model_validate({**fields, **overrides})


def test_the_reasoning_model_answers_are_read_as_certain_and_bring_the_free_form_facts() -> None:
    verdict = build_verdict(
        answers_from_reasoning(_reasoning()),
        decided_by=JudgePass.REASONING,
        decisions_confidence=0.31,
        now=NOW,
        clock=IST,
        offered_runs=frozenset(),
    )

    assert verdict.urgency is UrgencyClass.TIMELY
    assert verdict.decided_by is JudgePass.REASONING
    assert verdict.confidence == pytest.approx(0.31)
    assert (verdict.reason, verdict.same_fact_key, verdict.topics) == (
        "A card decline needs a fix today.",
        "card-decline-0412",
        ["money"],
    )
    assert verdict.valid_until == datetime(2026, 11, 11, tzinfo=UTC)
    assert verdict.not_worth_probability == 0.0


def test_the_reasoning_model_saying_no_is_read_as_certainly_not_worth_telling() -> None:
    passed = answers_from_reasoning(_reasoning(worth_telling="no", relevance="superseded"))

    verdict = build_verdict(
        passed,
        decided_by=JudgePass.REASONING,
        decisions_confidence=None,
        now=NOW,
        clock=IST,
        offered_runs=frozenset(),
    )

    assert (verdict.relevance, verdict.not_worth_probability) == (Relevance.SUPERSEDED, 1.0)
    assert passed.get(JudgeQuestion.WAIT_FOR_RUN).choice == "none"


def test_a_decisions_verdict_has_a_machine_reason_and_no_free_form_facts() -> None:
    verdict = _read(answers())

    assert verdict.reason.startswith("Decisions: worth_telling=yes")
    assert (verdict.same_fact_key, verdict.topics, verdict.valid_until) == (None, [], None)
