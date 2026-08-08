"""Baseline comparison.

The baseline files existed and nothing read them for a verdict, so a regression
shipped silently. These pin that a drop is now caught, and — just as important —
that ordinary noise is not.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from scripts.evals.core import baseline


def _records(passed: int, failed: int, category: str = "todos") -> list[dict[str, Any]]:
    return [
        {"case_id": f"p{i}", "status": "passed", "category": category} for i in range(passed)
    ] + [{"case_id": f"f{i}", "status": "failed", "category": category} for i in range(failed)]


@pytest.fixture(autouse=True)
def _isolated_baselines(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(baseline, "BASELINES_DIR", tmp_path)


def test_a_real_drop_is_caught() -> None:
    baseline.write("demo", _records(18, 2), "run-a", "v1")
    worse = baseline.compare("demo", _records(10, 10))
    assert not worse.ok
    assert "below the baseline" in worse.regressions[0]


def test_noise_is_not_a_regression() -> None:
    """One case flipping in twenty must not fail a run, or the gate is noise."""
    baseline.write("demo", _records(18, 2), "run-a", "v1")
    same_ish = baseline.compare("demo", _records(17, 3))
    assert same_ish.ok, same_ish.regressions


def test_improvement_is_never_a_regression() -> None:
    baseline.write("demo", _records(10, 10), "run-a", "v1")
    better = baseline.compare("demo", _records(18, 2))
    assert better.ok
    assert (better.delta or 0) > 0


def test_a_thin_suite_reports_but_does_not_fail() -> None:
    """Below the minimum, a 'drop' is one case flipping."""
    baseline.write("demo", _records(4, 0), "run-a", "v1")
    thin = baseline.compare("demo", _records(1, 2))
    assert thin.ok
    assert any("too few" in note for note in thin.notes)


def test_a_per_category_drop_is_caught_even_when_the_suite_holds() -> None:
    records = _records(10, 0, "todos") + _records(10, 0, "gmail")
    baseline.write("demo", records, "run-a", "v1")
    # gmail collapses, todos improves; the suite total barely moves.
    regressed = _records(10, 0, "todos") + _records(2, 8, "gmail")
    result = baseline.compare("demo", regressed)
    assert not result.ok
    assert any("gmail" in r for r in result.regressions)


def test_no_baseline_is_reported_not_failed() -> None:
    fresh = baseline.compare("never-seen", _records(5, 5))
    assert fresh.ok
    assert fresh.baseline_accuracy is None
    assert "--rebaseline" in fresh.render()


def test_errored_cases_are_excluded_from_accuracy() -> None:
    """An outage must not drag the rate down — it is not a wrong answer."""
    records = _records(9, 1) + [{"case_id": "e", "status": "errored", "category": "todos"}]
    result = baseline.compare("demo", records)
    assert result.graded == 10
    assert result.errored == 1
    assert result.accuracy == pytest.approx(0.9)


def test_rebaseline_records_categories_for_the_next_comparison() -> None:
    path = baseline.write("demo", _records(6, 0, "web"), "run-x", "v2")
    stored = json.loads(path.read_text())
    assert stored["per_category"] == {"web": [6, 6]}
    assert stored["run_id"] == "run-x"
    assert stored["app_version"] == "v2"
