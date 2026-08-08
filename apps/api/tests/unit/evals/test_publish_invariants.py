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


def test_cumulative_token_counts_are_rejected() -> None:
    """Built from the real per-case deltas of the run that overstated usage 74x,
    accumulated the way that run recorded them."""
    deltas = [
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
    running = 0
    cumulative = []
    for delta in deltas:
        running += delta
        cumulative.append(running)
    report = check_records([_ran(f"c{i}", n) for i, n in enumerate(cumulative)])
    assert not report.ok
    assert any("cumulative" in v.check for v in report.violations)


def test_a_long_genuine_series_still_publishes() -> None:
    """The same deltas as themselves — a real per-case series of the same length
    must not trip the cumulative check."""
    deltas = [
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
    report = check_records([_ran(f"c{i}", n) for i, n in enumerate(deltas)])
    assert report.ok, [v.detail for v in report.violations]


def test_a_genuine_per_case_series_passes() -> None:
    """The same cases measured correctly. Must not trip, or the gate is noise."""
    real = [14262, 13474, 14052, 7290, 13910, 14957, 13319, 13752, 14018, 13844]
    report = check_records([_ran(f"c{i}", n) for i, n in enumerate(real)])
    assert report.ok, [v.detail for v in report.violations]


def test_journal_and_tracker_must_agree() -> None:
    records = [_ran(f"c{i}", 1000) for i in range(10)]  # 10_000 in
    assert check_records(records, metered_total=(10_000, 1_000)).ok
    disagreeing = check_records(records, metered_total=(500_000, 1_000))
    assert not disagreeing.ok
    assert any("disagree with the tracker" in v.check for v in disagreeing.violations)


def test_duplicate_case_records_are_caught() -> None:
    """A re-run appends, so an aggregation counts the stale attempt too."""
    report = check_records([_ran("same", 100), _ran("same", 120)])
    assert not report.ok
    assert any("duplicate" in v.check for v in report.violations)


def test_a_clean_run_publishes() -> None:
    varied = [14262, 13474, 14052, 7290, 13910, 14957, 13319, 8752, 14018, 13844, 9001, 13120]
    report = check_records([_ran(f"c{i}", n) for i, n in enumerate(varied)])
    assert report.ok, [v.detail for v in report.violations]
