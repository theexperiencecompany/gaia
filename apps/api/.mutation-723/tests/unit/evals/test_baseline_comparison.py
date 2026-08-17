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
from scripts.evals.core.journal import RunJournal, RunMeta


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
    records = _records(2, 8, "todos") + _records(10, 0, "gmail")
    baseline.write("demo", records, "run-a", "v1")
    # gmail collapses, todos improves; the suite total stays put, so only the
    # per-category check can fail the run.
    regressed = _records(10, 0, "todos") + _records(2, 8, "gmail")
    result = baseline.compare("demo", regressed)
    assert not result.ok
    assert all("suite accuracy" not in r for r in result.regressions)
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


def _run_on_disk(
    runs_dir: Path,
    run_id: str,
    records: list[dict[str, Any]],
    *,
    status: str = "finished",
    excluded: str | None = None,
) -> RunJournal:
    journal = RunJournal(runs_dir, run_id)
    journal.create_meta(
        RunMeta(
            run_id=run_id,
            suite="demo",
            started_at="2026-08-08T00:00:00+00:00",
            status=status,
            app_version="v9",
            excluded=excluded,
        )
    )
    for record in records:
        journal.append(record)
    return journal


def test_a_run_is_judged_against_the_baseline_from_its_journal_alone(tmp_path: Path) -> None:
    """The offline `compare` command and the live run loop take this one path."""
    baseline.write("demo", _records(18, 2), "run-a", "v1")
    journal = _run_on_disk(tmp_path, "run-b", _records(10, 10))
    result = baseline.for_run(journal)
    assert not result.ok
    assert result.baseline_run == "run-a"


def test_rebaseline_writes_then_judges_against_itself(tmp_path: Path) -> None:
    journal = _run_on_disk(tmp_path, "run-b", _records(10, 10))
    result = baseline.for_run(journal, rebaseline=True)
    assert result.ok
    assert json.loads(baseline.path_for("demo").read_text())["run_id"] == "run-b"


def test_an_excluded_run_can_never_become_the_baseline(tmp_path: Path) -> None:
    """Its numbers are on record as wrong; enshrining them sets the bar to a bug."""
    journal = _run_on_disk(tmp_path, "run-b", _records(1, 19), excluded="token accounting defect")
    with pytest.raises(SystemExit, match="excluded"):
        baseline.for_run(journal, rebaseline=True)
    assert not baseline.path_for("demo").exists()


def test_an_unfinished_run_can_never_become_the_baseline(tmp_path: Path) -> None:
    """An aborted run holds only the cases that ran before the backend died."""
    journal = _run_on_disk(tmp_path, "run-b", _records(2, 0), status="aborted")
    with pytest.raises(SystemExit, match="not 'finished'"):
        baseline.for_run(journal, rebaseline=True)
    assert not baseline.path_for("demo").exists()


def test_a_provisional_baseline_says_so_at_every_comparison(tmp_path: Path) -> None:
    """A baseline is only as good as the stack the run was made against. Every
    baseline on disk came from an API with no JuiceFS mount, so the agent had no
    file ops — a later run on a working stack would read as an improvement it
    did not earn."""
    journal = _run_on_disk(tmp_path, "run-a", _records(18, 2))
    baseline.for_run(journal, rebaseline=True, provisional="no JuiceFS mount: no file ops")
    later = baseline.compare("demo", _records(17, 3))
    assert later.provisional == "no JuiceFS mount: no file ops"
    assert "no JuiceFS mount" in later.render()
    assert "PROVISIONAL BASELINE" in later.render()


def test_a_trustworthy_baseline_carries_no_caveat(tmp_path: Path) -> None:
    journal = _run_on_disk(tmp_path, "run-a", _records(18, 2))
    baseline.for_run(journal, rebaseline=True)
    later = baseline.compare("demo", _records(17, 3))
    assert later.provisional == ""
    assert "PROVISIONAL" not in later.render()


def test_a_provisional_baseline_still_reports_a_regression(tmp_path: Path) -> None:
    """The caveat explains the number; it does not suppress it."""
    journal = _run_on_disk(tmp_path, "run-a", _records(18, 2))
    baseline.for_run(journal, rebaseline=True, provisional="crippled stack")
    worse = baseline.compare("demo", _records(8, 12))
    assert not worse.ok
    assert "crippled stack" in worse.render()


def test_a_retried_case_is_counted_once(tmp_path: Path) -> None:
    """The journal appends, so a fixed case must not be counted as its old failure."""
    journal = _run_on_disk(tmp_path, "run-b", _records(9, 1))
    journal.append({"case_id": "f0", "status": "passed", "category": "todos"})
    result = baseline.for_run(journal)
    assert result.graded == 10
    assert result.accuracy == pytest.approx(1.0)
