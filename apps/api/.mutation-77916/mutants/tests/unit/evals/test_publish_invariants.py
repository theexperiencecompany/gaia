"""Publish-gate invariants.

Fixtures use the real token series from the runs that shipped these defects, so
a regression is caught by the data that caused it.
"""

from __future__ import annotations

from typing import Any

from scripts.evals.core.invariants import check_records


def _ran(case_id: str, tokens_in: int, status: str = "passed") -> dict[str, Any]:
    return {
        "case_id": case_id,
        "status": status,
        "text": "a real answer",
        "messages": [{"role": "assistant", "content": "a real answer"}],
        "scores": {"communicate": 1.0},
        "tokens": {"input": tokens_in, "output": tokens_in // 10},
    }


def test_a_case_that_produced_nothing_cannot_carry_a_score() -> None:
    """76 cases once errored with empty transcripts and zero tokens, were
    journaled as failures, and were averaged in as 0.0."""
    records = [
        {
            "case_id": f"lme-{i}",
            "status": "failed",
            "text": "",
            "messages": [],
            "scores": {"gaia_exact": 0.0},
            "tokens": {"input": 0, "output": 0},
        }
        for i in range(5)
    ]
    report = check_records(records)
    assert not report.ok
    assert any("produced nothing" in v.check for v in report.violations)


#: Real per-case deltas from the run that overstated usage 74x. The pair of
#: tests below is only worth anything while both use the SAME series, so it is
#: written once — accumulated for one test, raw for the other.
_REAL_DELTAS = [
    14316,
    13315,
    13818,
    7328,
    13890,
    14956,
    13932,
    8260,
    14834,
    13854,
    18060,
    19564,
    12233,
    9481,
    14402,
    13117,
    7935,
    14690,
    13508,
    12944,
    15221,
    8873,
    13366,
    14075,
    13990,
]


def test_cumulative_token_counts_are_rejected() -> None:
    """Built from the real per-case deltas of the run that overstated usage 74x,
    accumulated the way that run recorded them."""
    running = 0
    cumulative = []
    for delta in _REAL_DELTAS:
        running += delta
        cumulative.append(running)
    report = check_records([_ran(f"c{i}", n) for i, n in enumerate(cumulative)])
    assert not report.ok
    assert any("cumulative" in v.check for v in report.violations)


def test_a_long_genuine_series_still_publishes() -> None:
    """The same deltas as themselves — a real per-case series of the same length
    must not trip the cumulative check."""
    report = check_records([_ran(f"c{i}", n) for i, n in enumerate(_REAL_DELTAS)])
    assert report.ok, [v.detail for v in report.violations]


def test_a_genuine_per_case_series_passes() -> None:
    """The same cases measured correctly. Must not trip, or the gate is noise."""
    real = [14262, 13474, 14052, 7290, 13910, 14957, 13319, 13752, 14018, 13844]
    report = check_records([_ran(f"c{i}", n) for i, n in enumerate(real)])
    assert report.ok, [v.detail for v in report.violations]


def test_journal_and_tracker_must_agree() -> None:
    records = [_ran(f"c{i}", 1000) for i in range(10)]  # 1000 in / 100 out each
    agreeing = {f"c{i}": (1000, 100) for i in range(10)}
    assert check_records(records, metered_by_case=agreeing).ok
    disagreeing = {f"c{i}": (50_000, 100) for i in range(10)}
    result = check_records(records, metered_by_case=disagreeing)
    assert not result.ok
    assert any("disagree with the tracker" in v.check for v in result.violations)


def test_in_flight_spend_at_abort_does_not_block_publish() -> None:
    """An aborted run's tracker holds spend for cases the journal never saw.
    The intersection rule must ignore them, or every abort re-publish fails."""
    records = [_ran(f"c{i}", 1000) for i in range(10)]
    metered = {f"c{i}": (1000, 100) for i in range(10)}
    metered["in-flight-never-journaled"] = (62_000, 7_000)
    assert check_records(records, metered_by_case=metered).ok


def test_a_case_graded_twice_is_caught() -> None:
    """Two graded records for one case double-count in every aggregation."""
    report = check_records([_ran("same", 100), _ran("same", 120)])
    assert not report.ok
    assert any("graded more than once" in v.check for v in report.violations)


def test_a_retry_superseding_an_error_is_not_a_duplicate() -> None:
    """The sweep mechanism appends errored-then-graded by design; blocking it
    would punish exactly the path that clears errored cases."""
    errored = _ran("same", 0)
    errored["status"] = "errored"
    errored["tokens"]["input"] = 0
    report = check_records([errored, _ran("same", 12_000)])
    assert not any("graded more than once" in v.check for v in report.violations)


def test_a_clean_run_publishes() -> None:
    varied = [14262, 13474, 14052, 7290, 13910, 14957, 13319, 8752, 14018, 13844, 9001, 13120]
    report = check_records([_ran(f"c{i}", n) for i, n in enumerate(varied)])
    assert report.ok, [v.detail for v in report.violations]


def _worked_for(case_id: str, tokens_in: int, seconds: float) -> dict[str, Any]:
    record = _ran(case_id, tokens_in)
    record["tokens"]["input"] = tokens_in
    record["duration_s"] = seconds
    return record


def test_an_expensive_case_is_not_a_corrupt_one() -> None:
    """No upper bound, deliberately. The app's own per-call accounting puts a
    real capability case at a 131k median and the largest measured at 9.6M —
    context grows step over step and compaction is skipped without JuiceFS. A
    cap below that fails every honest native run, which is how a gate gets
    switched off."""
    huge = [_worked_for(f"c{i}", n, 120.0) for i, n in enumerate((1_722_668, 2_981_848, 723_820))]
    assert check_records(huge).ok, [v.detail for v in check_records(huge).violations]


def test_contamination_is_caught_by_reconciliation_not_by_size() -> None:
    """What the old cap was really catching: a per-case delta on a shared meter
    credits every case with its neighbours' spend, so the journal sums to
    roughly the concurrency times the truth. That fails against the tracker
    whatever the magnitude."""
    inflated = [_worked_for(f"c{i}", 390_716, 60.0) for i in range(12)]
    report = check_records(inflated, metered_by_case={f"c{i}": (131_393, 4_000) for i in range(12)})
    assert not report.ok
    assert any("disagree with the tracker" in v.check for v in report.violations)


def test_an_estimate_of_the_question_is_not_a_measurement() -> None:
    """gaia_bench recorded a median of 56 input tokens and hil 16, for cases that
    spent a real minute in the agent. Both estimate from the question's character
    count, which never sees the system prompt — and nothing caught it, because
    every check only ever looked for numbers that were too LARGE."""
    report = check_records([_worked_for(f"gaia-{i}", n, 53.4) for i, n in enumerate((104, 56, 88))])
    assert not report.ok
    assert any("implausibly small" in v.check for v in report.violations)


def test_a_meter_that_never_fired_is_caught_too() -> None:
    """regression journaled 0 tokens for every case: it read a per-provider total
    under a provider name the tracker never used."""
    report = check_records([_worked_for(f"reg-{i}", 0, 5.4) for i in range(5)])
    assert not report.ok
    assert any("implausibly small" in v.check for v in report.violations)


def test_a_fake_transport_is_not_held_to_the_floor() -> None:
    """A transport that answers in 0.07s never called a model, so it has nothing
    to under-count. Note this exempts smoke by its speed, not by its name — and
    smoke's first case sometimes takes 1.7-2.7s of warmup, so it is NOT reliably
    exempt. The real fix there is for the suite to stop inventing token figures."""
    report = check_records([_worked_for(f"smoke-{i}", 120, 0.07) for i in range(3)])
    assert report.ok, [v.detail for v in report.violations]


def test_an_errored_case_is_not_held_to_the_floor() -> None:
    """A case that died partway has a partial reading by definition. Flagging it
    fires on exactly the runs an outage already ruined — verified against
    comms-20260808-092206, where all 5 records the floor caught were errored."""
    dead = [_worked_for(f"c{i}", 0, 30.0) for i in range(5)]
    for record in dead:
        record["status"] = "errored"
        record["scores"] = {}
    assert check_records(dead).ok, [v.detail for v in check_records(dead).violations]


def test_a_graded_case_is_still_held_to_the_floor() -> None:
    """The true positives all reach a verdict: every record the floor catches in
    gaia_bench, hil and regression is passed or failed."""
    graded = [_worked_for(f"c{i}", 104, 30.0) for i in range(5)]
    for record in graded:
        record["status"] = "failed"
    report = check_records(graded)
    assert not report.ok
    assert any("implausibly small" in v.check for v in report.violations)


def test_a_real_measurement_is_never_called_too_small() -> None:
    report = check_records([_worked_for(f"c{i}", n, 30.0) for i, n in enumerate((22713, 3699))])
    assert report.ok, [v.detail for v in report.violations]


def test_an_outage_graded_as_a_wrong_answer_blocks_the_run() -> None:
    """164 GAIA cases were journaled `failed` carrying an HTTP 500 from a dead
    API, with no transcript and no scores, and were averaged into accuracy."""
    outage = [
        {
            "case_id": f"gaia-{i}",
            "status": "failed",
            "text": "",
            "messages": [],
            "tool_calls": [],
            "scores": {},
            "tokens": {"input": 0, "output": 0},
            "duration_s": 0.01,
            "error": "RuntimeError: dev executor endpoint failed: HTTP 500",
        }
        for i in range(6)
    ]
    report = check_records(outage)
    assert not report.ok
    assert any("outage was graded" in v.check for v in report.violations)


def test_the_same_outage_recorded_honestly_publishes() -> None:
    """`errored` is the honest status — unscored, out of the denominator. It is
    the grading of a fault as a wrong answer that must stop a run, not the fault."""
    honest = [
        {
            "case_id": f"gaia-{i}",
            "status": "errored",
            "text": "",
            "messages": [],
            "tool_calls": [],
            "scores": {},
            "tokens": {"input": 0, "output": 0},
            "duration_s": 0.01,
            "error": "RuntimeError: dev executor endpoint failed: HTTP 500",
        }
        for i in range(6)
    ]
    assert check_records(honest).ok


def test_a_case_that_failed_on_its_merits_is_not_mistaken_for_an_outage() -> None:
    """A real wrong answer has a transcript. It must stay in the denominator."""
    wrong = [
        {
            "case_id": "c1",
            "status": "failed",
            "text": "Paris",
            "messages": [{"role": "assistant", "content": "Paris"}],
            "tool_calls": [],
            "scores": {"gaia_exact": 0.0},
            "tokens": {"input": 12000, "output": 40},
            "duration_s": 20.0,
            "error": None,
        }
    ]
    assert check_records(wrong).ok
