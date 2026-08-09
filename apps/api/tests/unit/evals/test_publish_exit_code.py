"""What the run loop does with a regression once it has one.

A regression is a result, not a crash: the report and the journal are what
someone will actually look at, so they have to be on disk before the process
exits non-zero. An exit that beats the report to the punch turns "the suite got
worse" into "the harness crashed", and the evidence is gone.

This drives ``_publish_run`` itself rather than a re-implementation of it, so
the ordering is pinned where it actually happens.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from scripts.evals.core import baseline, runner
from scripts.evals.core.cost import EvalCostTracker
from scripts.evals.core.journal import RunJournal, RunMeta
from scripts.evals.core.types import Case, ProviderPrice


class _Suite(runner.Suite):
    name = "demo"
    project = "gaia-demo"
    label = "Demo"


def _record(case_id: str, status: str) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "status": status,
        "category": "todos",
        "text": "a real answer",
        "messages": [{"role": "assistant", "content": "a real answer"}],
        "scores": {"communicate": 1.0 if status == "passed" else 0.0},
        "tokens": {"input": 1000 + len(case_id), "output": 100},
        "duration_s": 1.0,
        "provider": "opencode",
    }


@pytest.fixture(autouse=True)
def _isolated_baselines(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(baseline, "BASELINES_DIR", tmp_path / "baselines")


def _publish(tmp_path: Path, passed: int, failed: int) -> Path:
    journal = RunJournal(tmp_path / "runs", "run-b")
    journal.create_meta(
        RunMeta(
            run_id="run-b",
            suite="demo",
            started_at="2026-08-08T00:00:00+00:00",
            status="finished",
            app_version="v9",
        )
    )
    for index in range(passed):
        journal.append(_record(f"p{index}", "passed"))
    for index in range(failed):
        journal.append(_record(f"f{index}", "failed"))
    opts = runner.RunOptions(suite="demo", no_finalize=True)
    tracker = EvalCostTracker({}, 1.0)
    return runner._publish_run(
        journal,
        _Suite(),
        None,
        opts,
        [Case(id="p0", ticket="t", prompt="p")],
        {"opencode": ProviderPrice()},
        tracker,
        journal.records(),
    )


def test_a_regression_exits_non_zero_after_the_report_is_written(tmp_path: Path) -> None:
    baseline.write("demo", [_record(f"p{i}", "passed") for i in range(20)], "run-a", "v8")
    with pytest.raises(SystemExit) as exit_info:
        _publish(tmp_path, passed=10, failed=10)
    assert exit_info.value.code == 1
    assert (tmp_path / "runs" / "run-b" / "report.html").exists(), (
        "the report must be on disk before the exit code carries the verdict away"
    )


def test_a_clean_run_returns_its_journal(tmp_path: Path) -> None:
    baseline.write("demo", [_record(f"p{i}", "passed") for i in range(20)], "run-a", "v8")
    assert _publish(tmp_path, passed=19, failed=1).name == "run-b"


def test_numbers_that_do_not_reconcile_block_the_report_entirely(tmp_path: Path) -> None:
    """The other exit: nothing publishable was measured, so nothing is published."""
    journal = RunJournal(tmp_path / "runs", "run-c")
    journal.create_meta(
        RunMeta(run_id="run-c", suite="demo", started_at="2026-08-08T00:00:00+00:00")
    )
    journal.append(
        {
            "case_id": "silent",
            "status": "failed",
            "text": "",
            "messages": [],
            "scores": {"communicate": 0.0},
            "tokens": {"input": 0, "output": 0},
        }
    )
    with pytest.raises(SystemExit) as exit_info:
        runner._publish_run(
            journal,
            _Suite(),
            None,
            runner.RunOptions(suite="demo", no_finalize=True),
            [],
            {},
            EvalCostTracker({}, 1.0),
            journal.records(),
        )
    assert exit_info.value.code == 2
    assert not (tmp_path / "runs" / "run-c" / "report.html").exists()
