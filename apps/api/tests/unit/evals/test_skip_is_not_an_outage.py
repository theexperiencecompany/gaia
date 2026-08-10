"""A skip scores zero and stays in the denominator; an outage leaves it.

Both used to arrive as ``CaseRun(error=...)``, so both were recorded ``errored``
and both left the denominator. GAIA's baseline records it exactly: graded 89,
errored 76, accuracy 0.4045 — 36/89, published as "GAIA 40.4%" for a benchmark
whose split is 165 questions. The honest figure over the split is 36/165 =
21.8%. Cases we declined to attempt quietly vanished from the number.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from scripts.evals.core import baseline, runner
from scripts.evals.core.invariants import check_records
from scripts.evals.core.types import Case, CaseRun


@pytest.fixture(autouse=True)
def _isolated_baselines(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Never write the repo's real baselines from a test."""
    monkeypatch.setattr(baseline, "BASELINES_DIR", tmp_path / "baselines")


class _Suite(runner.Suite):
    name = "gaia_bench"
    label = "GAIA-Bench"

    def score(self, case: Case, run: CaseRun) -> dict[str, float]:
        raise AssertionError("a declined case must never reach the scorer")


def _case(case_id: str, *, skip: str = "") -> Case:
    expected: dict[str, Any] = {"score": {"gates": ["gaia_exact"]}}
    if skip:
        expected["skip_reason"] = skip
    return Case(id=case_id, ticket="t", prompt="p", expected=expected)


def test_a_declined_case_is_skipped_not_errored() -> None:
    case = _case("gaia-mp3", skip="audio has no ingestion path")
    run = CaseRun(case_id=case.id, error="skipped: audio has no ingestion path")
    scores = runner._score_or_zero(case, run, _Suite())
    assert scores == {"gaia_exact": 0.0}
    assert runner._status_from_scores(case, scores, run.error) == "skipped"


def test_an_outage_is_still_errored() -> None:
    case = _case("gaia-live")
    run = CaseRun(case_id=case.id, error="ConnectError: all connection attempts failed")
    scores = runner._score_or_zero(case, run, _Suite())
    assert scores == {}
    assert runner._status_from_scores(case, scores, run.error) == "errored"


def test_the_skip_beats_the_error_text() -> None:
    """The transport signals a skip by setting `error`. Reading the error first
    is precisely what filed every skip as an outage."""
    case = _case("gaia-zip", skip="archives have no ingestion path")
    assert runner._status_from_scores(case, {"gaia_exact": 0.0}, "skipped: archives") == "skipped"


def _graded(status: str, case_id: str, *, skip: str | None = None) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "status": status,
        "category": "L1",
        "scores": {"gaia_exact": 1.0 if status == "passed" else 0.0},
        "skip_reason": skip,
        "text": "" if status in ("skipped", "errored") else "an answer",
        "messages": [] if status in ("skipped", "errored") else [{"role": "a", "content": "x"}],
        "tokens": {"input": 0 if status in ("skipped", "errored") else 12000, "output": 40},
        "duration_s": 0.0 if status == "skipped" else 20.0,
    }


def test_skips_stay_in_the_denominator_and_outages_do_not() -> None:
    records = (
        [_graded("passed", f"p{i}") for i in range(36)]
        + [_graded("failed", f"f{i}") for i in range(53)]
        + [_graded("skipped", f"s{i}", skip="unsupported attachment") for i in range(76)]
    )
    accuracy, graded, errored = baseline._accuracy(records)
    assert graded == 165
    assert errored == 0
    assert accuracy == pytest.approx(36 / 165, abs=1e-4)


def test_the_old_arithmetic_is_what_produced_the_published_number() -> None:
    """Same run with the skips recorded as outages: 36/89 = 40.4%, the figure
    that shipped, nearly double the honest one."""
    records = (
        [_graded("passed", f"p{i}") for i in range(36)]
        + [_graded("failed", f"f{i}") for i in range(53)]
        + [_graded("errored", f"e{i}") for i in range(76)]
    )
    accuracy, graded, errored = baseline._accuracy(records)
    assert (graded, errored) == (89, 76)
    assert accuracy == pytest.approx(0.4045, abs=1e-3)


def test_the_publish_gate_lets_a_declared_skip_carry_its_zero() -> None:
    """The gate refuses to score a case that produced nothing — which is what a
    scored-zero skip looks like. It has to tell "we never asked" from "we asked
    and got silence", and the declared reason is what tells it."""
    skips = [_graded("skipped", f"s{i}", skip="audio has no ingestion path") for i in range(9)]
    assert check_records(skips).ok, [v.detail for v in check_records(skips).violations]


def test_the_publish_gate_still_refuses_an_undeclared_silence() -> None:
    silent = [_graded("failed", f"c{i}") for i in range(9)]
    for record in silent:
        record["text"] = ""
        record["messages"] = []
        record["tokens"] = {"input": 0, "output": 0}
    report = check_records(silent)
    assert not report.ok
    assert any("produced nothing" in v.check for v in report.violations)


def test_a_denominator_change_is_not_reported_as_a_regression(tmp_path: Path) -> None:
    """attach's work makes 28 declined cases actually run. The numerator barely
    moves, so the rate falls — that is the measurement improving."""
    baseline.write(
        "gaia_bench",
        [_graded("passed", f"p{i}") for i in range(36)]
        + [_graded("failed", f"f{i}") for i in range(53)],
        "run-a",
        "v1",
    )
    wider = (
        [_graded("passed", f"p{i}") for i in range(38)]
        + [_graded("failed", f"f{i}") for i in range(51)]
        + [_graded("skipped", f"s{i}", skip="unsupported") for i in range(76)]
    )
    result = baseline.compare("gaia_bench", wider)
    assert any("denominator moved" in note for note in result.notes)
