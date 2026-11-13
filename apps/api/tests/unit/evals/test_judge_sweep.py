"""The recorded judge eval, regraded through the production verdict reader and policy: the Judge's accuracy as a CI fact.

The answers of a recorded run (the Decisions pass, and the reasoning pass where the first was
unsure) are read by the production confidence gate, verdict reader and Rails, so an edit to a
threshold, an authority rule or a question fails here without a model call. The gate is zero
critical misses; the misses a recorded run still has are listed, and the list only shrinks.
"""

import json
from pathlib import Path

import pytest
from scripts.evals.core.cases import load_case_files
from scripts.evals.core.types import Case, CaseRun
from scripts.evals.suites import judge as suite
from scripts.evals.suites.judge import (
    DATA_DIR,
    EXTRA,
    JUDGE_GATE,
    Graded,
    RecordedCase,
    decisions_request_sha,
    failures_of,
    gold_disposition,
    is_graded,
    record,
    recorded_cases,
    regrade,
    state_of,
)

from app.constants.outbox_judge import JUDGE_CONFIDENCE_GATE
from app.services.outbox.judge_models import JudgePass
from app.services.outbox.judge_verdict import JudgeAnswerError
from tests._harness.judge import verdict

#: Critical rows the recorded run still gets wrong, each with why; remove an entry the day it is fixed.
KNOWN_CRITICAL_MISSES = {
    "time-money-TM03": "an OTP the user already got by SMS is told again as an interrupt",
    "time-money-TM08": "a BTC dip that recovered by morning is recorded though the user asked to be told",
    "time-money-TM15": "a credit card statement is read as personal, not finance",
    "work-W16": "company financials in an answer are read as personal, not finance",
}


@pytest.fixture(scope="module")
def cases() -> dict[str, Case]:
    return {case.id: case for case in load_case_files(DATA_DIR, "judge", EXTRA)}


@pytest.fixture(scope="module")
def recorded() -> dict[str, RecordedCase]:
    return recorded_cases()


@pytest.fixture(scope="module")
def graded(cases: dict[str, Case], recorded: dict[str, RecordedCase]):
    return {
        case_id: regrade(case, recorded[case_id]["decisions"], recorded[case_id]["reasoning"])
        for case_id, case in cases.items()
    }


def test_the_corpus_is_the_two_hundred_scenarios_and_every_one_is_recorded(
    cases: dict[str, Case], recorded: dict[str, RecordedCase]
) -> None:
    assert len(cases) == 200
    assert set(cases) == set(recorded)


def test_every_recorded_decisions_answer_belongs_to_the_request_production_sends(
    cases: dict[str, Case], recorded: dict[str, RecordedCase]
) -> None:
    stale = [
        case_id
        for case_id, case in cases.items()
        if recorded[case_id]["decisions"]["request_sha"] != decisions_request_sha(state_of(case))
    ]

    assert stale == [], "re-record: the questions, instructions or a case changed"


def test_no_critical_row_is_missed_beyond_the_known_ones(
    cases: dict[str, Case], graded: dict[str, Graded]
) -> None:
    missed = {
        case_id: graded[case_id].failures
        for case_id, case in cases.items()
        if is_graded(case) and case.expected["critical"] and graded[case_id].failures
    }

    assert set(missed) == set(KNOWN_CRITICAL_MISSES), missed


def test_the_holdout_has_no_critical_miss(
    cases: dict[str, Case], graded: dict[str, Graded]
) -> None:
    missed = [
        case_id
        for case_id, case in cases.items()
        if is_graded(case)
        and case.expected["critical"]
        and case.expected["split"] == "holdout"
        and graded[case_id].failures
    ]

    assert missed == []


def test_the_measured_shape_of_the_gate_holds(
    cases: dict[str, Case], graded: dict[str, Graded]
) -> None:
    rows = [(case, graded[case_id]) for case_id, case in cases.items() if is_graded(case)]
    alone = sum(g.decided_by is JudgePass.DECISIONS for _, g in rows)
    critical = [g for case, g in rows if case.expected["critical"]]

    assert (len(rows), len(critical)) == (151, 96)
    assert alone == 44
    assert sum(bool(g.failures) for g in critical) == len(KNOWN_CRITICAL_MISSES)


def test_the_judge_never_wakes_the_user_for_what_is_not_an_interrupt_beyond_the_measured(
    cases: dict[str, Case], graded: dict[str, Graded]
) -> None:
    woken = [
        case_id
        for case_id, case in cases.items()
        if is_graded(case)
        and graded[case_id].disposition == "now"
        and gold_disposition(case.expected["gold"]) != "now"
        and suite.is_quiet(state_of(case))
    ]

    assert len(woken) == 3


def test_a_regraded_case_scores_through_the_suites_own_gate(
    cases: dict[str, Case], graded: dict[str, Graded]
) -> None:
    for case_id in ("time-money-TM03", "work-W01"):
        case = cases[case_id]
        run = CaseRun(
            case_id=case_id,
            end_state={
                "disposition": graded[case_id].disposition,
                "failures": list(graded[case_id].failures),
            },
        )
        expected = 0.0 if case_id in KNOWN_CRITICAL_MISSES else 1.0

        assert EXTRA[JUDGE_GATE](case, run) == expected


def test_a_run_that_recorded_nothing_fails_every_case_even_those_the_judge_does_not_grade(
    cases: dict[str, Case],
) -> None:
    empty = CaseRun(case_id="x")

    assert {EXTRA[JUDGE_GATE](case, empty) for case in cases.values()} == {0.0}
    assert {
        EXTRA[JUDGE_GATE](case, CaseRun(case_id="x", end_state={"text": "echo"}))
        for case in cases.values()
    } == {0.0}


def test_an_unsure_decisions_pass_with_no_reasoning_pass_recorded_cannot_be_regraded(
    cases: dict[str, Case], recorded: dict[str, RecordedCase]
) -> None:
    unsure = next(
        case_id
        for case_id, row in recorded.items()
        if row["reasoning"] is not None
        and min(
            row["decisions"]["answers"][q].get("confidence") or 0.0
            for q in ("worth_telling", "within_minutes", "before_checkin", "authenticity")
        )
        < JUDGE_CONFIDENCE_GATE
    )

    with pytest.raises(JudgeAnswerError, match="no reasoning pass"):
        regrade(cases[unsure], recorded[unsure]["decisions"], None)


@pytest.mark.parametrize(
    ("gold", "disposition", "sensitivity", "quiet", "expected"),
    [
        (
            {"urgency": "interrupt", "relevance": "new"},
            "soon",
            "none",
            True,
            ("late now->soon (held overnight)",),
        ),
        ({"urgency": "interrupt", "relevance": "new"}, "soon", "none", False, ()),
        (
            {"urgency": "interrupt", "relevance": "new"},
            "later",
            "none",
            False,
            ("late now->later",),
        ),
        ({"urgency": "timely", "relevance": "new"}, "fyi", "none", False, ("missed soon->fyi",)),
        (
            {"urgency": "timely", "relevance": "new", "authenticity": "suspicious"},
            "soon",
            "none",
            False,
            ("scam relayed",),
        ),
        (
            {"urgency": "interrupt", "relevance": "moot"},
            "now",
            "none",
            False,
            ("moot pushed ->now",),
        ),
        ({"urgency": "routine", "relevance": "moot"}, "now", "none", False, ()),
        (
            {"urgency": "routine", "relevance": "new", "sensitivity": "health"},
            "later",
            "none",
            False,
            ("exposed",),
        ),
        (
            {"urgency": "routine", "relevance": "new", "sensitivity": "health"},
            "later",
            "finance",
            False,
            (),
        ),
    ],
)
def test_each_way_a_disposition_hurts_the_user_is_named(
    gold: dict[str, str], disposition: str, sensitivity: str, quiet: bool, expected: tuple[str, ...]
) -> None:
    gold = {"sensitivity": "none", **gold}

    assert failures_of(gold, disposition, verdict(sensitivity=sensitivity), quiet=quiet) == expected


def test_a_recorded_run_is_kept_for_regrading(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "judge-run"
    run_dir.mkdir(parents=True)
    end_state = {"decisions": {"request_sha": "abc", "answers": {}}, "reasoning": None}
    (run_dir / "journal.jsonl").write_text(
        json.dumps({"case_id": "work-W01", "status": "passed", "end_state": end_state}) + "\n"
    )

    out = record(run_dir, tmp_path / "recorded")

    assert json.loads(out.read_text()) == {"case_id": "work-W01", **end_state}


def test_a_run_with_an_unanswered_case_cannot_be_recorded(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "judge-run"
    run_dir.mkdir(parents=True)
    (run_dir / "journal.jsonl").write_text(
        json.dumps({"case_id": "work-W02", "status": "errored", "end_state": None}) + "\n"
    )

    with pytest.raises(SystemExit, match="work-W02"):
        record(run_dir, tmp_path / "recorded")
