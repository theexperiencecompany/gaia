"""Flip detection across runs.

The detector's whole value is telling "the agent wavers" apart from "a fix
landed". It can only do that where the run recorded which build produced it —
and almost every run on disk predates version stamping, so the distinction had
to be honest about what it cannot attribute rather than crediting an unstamped
flip to a fix that may never have happened.
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.evals.core import flaky


def _write_run(
    runs_dir: Path,
    run_id: str,
    suite: str,
    outcomes: dict[str, str],
    *,
    app_version: str = "",
    excluded: str | None = None,
) -> None:
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "run.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "suite": suite,
                "started_at": "2026-08-08T00:00:00+00:00",
                "app_version": app_version,
                "excluded": excluded,
            }
        )
    )
    (run_dir / "journal.jsonl").write_text(
        "".join(
            json.dumps({"case_id": case_id, "status": status}) + "\n"
            for case_id, status in outcomes.items()
        )
    )


def test_a_flip_within_one_version_is_flaky(tmp_path: Path) -> None:
    _write_run(tmp_path, "s-1", "demo", {"a": "passed"}, app_version="v1")
    _write_run(tmp_path, "s-2", "demo", {"a": "failed"}, app_version="v1")
    entry = flaky.history(tmp_path)[("demo", "a")]
    assert entry.flaky
    assert not entry.undetermined
    assert entry.pass_rate == 0.5


def test_a_flip_between_recorded_versions_is_a_fix_not_a_flake(tmp_path: Path) -> None:
    _write_run(tmp_path, "s-1", "demo", {"a": "failed"}, app_version="v1")
    _write_run(tmp_path, "s-2", "demo", {"a": "passed"}, app_version="v2")
    entry = flaky.history(tmp_path)[("demo", "a")]
    assert not entry.flaky
    assert entry.changed_across_versions
    assert not entry.undetermined


def test_a_flip_across_unstamped_runs_is_undetermined_not_a_fix(tmp_path: Path) -> None:
    """Neither run says which build produced it, so nothing was demonstrated.

    Reporting this as "a fix landing" is a claim the data cannot support: it
    hides real flakiness behind a reassuring sentence, which is exactly the
    shape of every silent-green defect in this harness.
    """
    _write_run(tmp_path, "s-1", "demo", {"a": "passed"})
    _write_run(tmp_path, "s-2", "demo", {"a": "failed"})
    entry = flaky.history(tmp_path)[("demo", "a")]
    assert not entry.flaky
    assert entry.undetermined
    assert not entry.changed_across_versions


def test_a_flip_against_one_unstamped_run_is_undetermined(tmp_path: Path) -> None:
    """One side stamped is still not two builds to compare."""
    _write_run(tmp_path, "s-1", "demo", {"a": "passed"})
    _write_run(tmp_path, "s-2", "demo", {"a": "failed"}, app_version="v2")
    entry = flaky.history(tmp_path)[("demo", "a")]
    assert entry.undetermined
    assert not entry.changed_across_versions


def test_an_excluded_run_is_never_an_observation(tmp_path: Path) -> None:
    _write_run(tmp_path, "s-1", "demo", {"a": "passed"}, app_version="v1")
    _write_run(tmp_path, "s-2", "demo", {"a": "failed"}, app_version="v1", excluded="token defect")
    entry = flaky.history(tmp_path)[("demo", "a")]
    assert not entry.flaky
    assert entry.graded == 1


def test_a_retry_within_a_run_is_one_observation(tmp_path: Path) -> None:
    run_dir = tmp_path / "s-1"
    run_dir.mkdir()
    (run_dir / "run.json").write_text(json.dumps({"suite": "demo", "app_version": "v1"}))
    (run_dir / "journal.jsonl").write_text(
        json.dumps({"case_id": "a", "status": "failed"})
        + "\n"
        + json.dumps({"case_id": "a", "status": "passed"})
        + "\n"
    )
    entry = flaky.history(tmp_path)[("demo", "a")]
    assert entry.graded == 1
    assert not entry.flaky


def test_the_report_names_the_undetermined_bucket(tmp_path: Path) -> None:
    _write_run(tmp_path, "s-1", "demo", {"a": "passed"})
    _write_run(tmp_path, "s-2", "demo", {"a": "failed"})
    rendered = flaky.report(tmp_path)
    assert "undetermined" in rendered
    assert "1 " in rendered
