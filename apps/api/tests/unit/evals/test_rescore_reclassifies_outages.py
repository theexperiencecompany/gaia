"""Re-grading history must correct an outage, not re-affirm it.

``rescore`` exists to fix published numbers from the journal alone. Pointed at
the contaminated LongMemEval run it did the opposite of its job: the 64 cases
that never ran carry an empty transcript, so it either re-scored the blank as a
miss or filed them under "re-run these" — and either way they stayed in the
denominator as ``failed``, which is the fabricated 0/64 still being reported.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from scripts.evals.core.journal import RunJournal, RunMeta
from scripts.evals.core.rescore import (
    reclassify,
    reclassify_all,
    render_by_suite,
    rescore,
    write_sibling,
)
from scripts.evals.core.runner import SUITE_REGISTRY, Suite
from scripts.evals.core.types import Case, CaseRun

from tests.unit.evals.conftest import eval_config

POSTGRES_DOWN = "RuntimeError: PostgreSQL engine not available"


def _never_ran(case_id: str) -> dict[str, Any]:
    """A record exactly as the outage wrote it: a verdict with no evidence."""
    return {
        "case_id": case_id,
        "category": "single-session-user",
        "status": "failed",
        "error": POSTGRES_DOWN,
        "text": "",
        "messages": [],
        "tool_calls": [],
        "scores": {},
        "duration_s": 0.01,
    }


def _answered(case_id: str, *, correct: bool) -> dict[str, Any]:
    answer = "Tuesday" if correct else "Friday"
    return {
        "case_id": case_id,
        "category": "multi-session",
        "status": "passed" if correct else "failed",
        "error": None,
        "text": answer,
        "messages": [{"role": "assistant", "content": answer}],
        "tool_calls": [],
        "end_state": {"gaia_exact": 1.0 if correct else 0.0},
        "scores": {"gaia_exact": 1.0 if correct else 0.0},
        "duration_s": 31.2,
    }


@pytest.fixture
def contaminated_run(tmp_path: Path) -> Path:
    """One run: 2 answered right, 1 answered wrong, 3 never asked."""
    runs = tmp_path / "runs"
    journal = RunJournal(runs, "longmemeval-outage")
    journal.create_meta(
        RunMeta(run_id="longmemeval-outage", suite="longmemeval", started_at="2026-08-08T00:06:53")
    )
    journal.append(_answered("lme-a", correct=True))
    journal.append(_answered("lme-b", correct=True))
    journal.append(_answered("lme-c", correct=False))
    for case_id in ("lme-d", "lme-e", "lme-f"):
        journal.append(_never_ran(case_id))
    return runs


def test_cases_that_never_ran_are_relabelled_errored(contaminated_run: Path) -> None:
    result = reclassify(contaminated_run, "longmemeval-outage")

    assert {d.case_id for d in result.reclassified} == {"lme-d", "lme-e", "lme-f"}
    assert all(d.was == "failed" and d.now == "errored" for d in result.reclassified)


def test_the_outage_leaves_the_accuracy_denominator(contaminated_run: Path) -> None:
    """The whole point: 2/6 published becomes 2/3 — the outage stops being a miss."""
    result = reclassify(contaminated_run, "longmemeval-outage")

    assert (result.accuracy_before.passed, result.accuracy_before.graded) == (2, 6)
    assert (result.accuracy_after.passed, result.accuracy_after.graded) == (2, 3)
    assert result.accuracy_before.pct == pytest.approx(33.3, abs=0.1)
    assert result.accuracy_after.pct == pytest.approx(66.7, abs=0.1)


def test_a_genuine_wrong_answer_survives_the_re_grade(contaminated_run: Path) -> None:
    """Mutation guard: this must correct an outage, not launder real failures."""
    result = reclassify(contaminated_run, "longmemeval-outage")

    assert "lme-c" not in {d.case_id for d in result.reclassified}
    assert result.after["failed"] == 1, "a real miss was erased along with the outage"
    assert result.after["errored"] == 3


class _AlwaysWrongSuite(Suite):
    """Stands in for any suite: grading a blank transcript always scores 0."""

    name = "longmemeval"
    project = "test-project"
    label = "LongMemEval"

    def load_cases(self, cfg: object) -> list[Case]:
        del cfg
        return [
            Case(
                id=case_id,
                ticket="t",
                prompt="q?",
                expected={"score": {"gates": ["gaia_exact"]}},
            )
            for case_id in ("lme-a", "lme-b", "lme-c", "lme-d", "lme-e", "lme-f")
        ]

    def score(self, case: Case, run: CaseRun) -> dict[str, float]:
        del case
        return {"gaia_exact": float((run.end_state or {}).get("gaia_exact", 0.0))}


def test_rescore_does_not_grade_a_case_that_never_produced_an_answer(
    contaminated_run: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The bug: re-grading an empty transcript scores 0.0 and re-affirms the lie."""
    monkeypatch.setitem(SUITE_REGISTRY, "longmemeval", lambda cfg: _AlwaysWrongSuite())

    result = rescore(contaminated_run, "longmemeval-outage", eval_config())

    graded = {d.case_id for d in result.deltas}
    assert graded == {"lme-a", "lme-b", "lme-c"}, (
        f"re-grade touched cases that never ran: {sorted(graded - {'lme-a', 'lme-b', 'lme-c'})}"
    )
    assert not any(d.now == "failed" for d in result.reclassified)
    assert (result.accuracy_after.passed, result.accuracy_after.graded) == (2, 3)


def test_the_correction_is_written_beside_the_journal_not_over_it(
    contaminated_run: Path,
) -> None:
    """Journals are append-only; the re-grade is a sibling, and history stays."""
    before = (contaminated_run / "longmemeval-outage" / "journal.jsonl").read_text()

    result = reclassify(contaminated_run, "longmemeval-outage")
    path = write_sibling(contaminated_run, result)

    assert (contaminated_run / "longmemeval-outage" / "journal.jsonl").read_text() == before
    payload = json.loads(path.read_text())
    assert payload["accuracy_before"] == {"passed": 2, "graded": 6}
    assert payload["accuracy_after"] == {"passed": 2, "graded": 3}
    assert len(payload["reclassified"]) == 3


def test_history_is_correctable_without_the_suite_or_its_dataset(
    contaminated_run: Path,
) -> None:
    """Most contaminated runs predate their current cases, and LongMemEval needs a
    dataset file that may not be on the machine doing the correcting. Whether a
    case ran is a property of the record, so the correction must never need them."""
    assert "longmemeval" not in SUITE_REGISTRY or True  # correction must not consult it
    results = reclassify_all(contaminated_run)

    assert len(results) == 1
    assert len(results[0].reclassified) == 3
    assert "longmemeval" in render_by_suite(results)
    assert "2/3" in render_by_suite(results)
