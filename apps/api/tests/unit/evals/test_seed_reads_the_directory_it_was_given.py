"""``seed(runs_dir=...)`` must read the journals it was pointed at.

``_group_runs_by_project`` honoured the parameter while ``_seed_project`` opened
each journal at the module-level ``RUNS_DIR``. Any caller passing a different
directory — the ingest pilot, a test, a copy of the runs tree — grouped run ids
from one place and read records from another, so the backfill silently wrote
nothing (or, worse, whatever an unrelated run of the same id happened to hold).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from scripts.evals.core import opiksink, seed as seed_module
from scripts.evals.core.runner import SUITE_REGISTRY, Suite

from .conftest import eval_config

RUN_ID = "smoke-20260808-093921-98a7ac"
PROJECT = "gaia-smoke"

RECORD: dict[str, Any] = {
    "case_id": "smoke-one",
    "ticket": "t",
    "prompt": "add milk",
    "text": "added",
    "status": "passed",
    "provider": "fake",
    "model": "fake-model",
    "tokens": {"input": 1200, "output": 340, "source": "metered"},
    "duration_s": 4.2,
    "ts": "2026-08-08T09:39:20+00:00",
}


class _SmokeSuite(Suite):
    name = "smoke"
    project = PROJECT
    label = "smoke"


def _journal_at(runs_dir: Path) -> None:
    run_dir = runs_dir / RUN_ID
    run_dir.mkdir(parents=True)
    (run_dir / "run.json").write_text(
        json.dumps({"run_id": RUN_ID, "suite": "smoke", "started_at": "", "app_version": "v1"})
    )
    (run_dir / "journal.jsonl").write_text(json.dumps(RECORD) + "\n")


def test_seed_backfills_from_the_runs_dir_it_was_given(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    written: list[str] = []
    runs_dir = tmp_path / "elsewhere"
    _journal_at(runs_dir)
    # The registry holds suite CLASSES; seed reads `.project` off the class.
    monkeypatch.setitem(SUITE_REGISTRY, "smoke", _SmokeSuite)
    monkeypatch.setattr(seed_module, "RUNS_DIR", tmp_path / "not-this-one")
    monkeypatch.setattr(seed_module, "_apply_description", lambda project: None)
    monkeypatch.setattr(seed_module, "_refuse_to_double", lambda project, traces: None)
    monkeypatch.setattr(opiksink, "flush", lambda project: None)
    monkeypatch.setattr(opiksink, "close_clients", lambda: None)
    monkeypatch.setattr(
        opiksink, "log_case_trace", lambda project, trace: written.append(trace.case_id)
    )

    seed_module.seed(eval_config(), runs_dir=runs_dir)

    assert written == ["smoke-one"]
