"""A run must always leave its metadata saying what actually happened.

Two ways it did not:

* ``--resume`` with a mistyped run id created an empty run directory (the
  journal makes its directory unconditionally) and then died pages later on
  ``NoneType has no attribute 'suite'`` — a message that says nothing about the
  typo, and a stray directory left behind for ``sweep`` and ``cost`` to read.
* A concurrent run returned from its own branch *before* the interrupt handler
  and the finalize block. Ctrl-C on one propagated out of ``run_suite`` with the
  traces unflushed and ``run.json`` still saying ``running`` — the state
  ``--resume``, ``sweep`` and ``ingest`` all read as "a run still in flight".

Ctrl-C reaches an asyncio program at the ``await`` the main coroutine is
sitting on, so the concurrent case injects it there rather than inside a case:
a ``KeyboardInterrupt`` raised inside a Task is re-raised into the event loop by
design and can never be caught by the awaiting coroutine, which would test the
opposite of what a real interrupt does.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from scripts.evals.core import runner as runner_mod
from scripts.evals.core.cost import EvalCostTracker
from scripts.evals.core.providers import EvalConfig, ProviderConfig
from scripts.evals.core.runner import RunOptions, Suite, run_suite
from scripts.evals.core.types import Case, CaseRun, ProviderHealth

from .conftest import eval_config

SUITE_NAME = "interrupting"
PROJECT = "gaia-smoke"


class _InterruptingSuite(Suite):
    """Answers ``case-0``, then raises the interrupt on ``case-1``."""

    name = SUITE_NAME
    project = PROJECT
    label = SUITE_NAME

    def load_cases(self, cfg: EvalConfig) -> list[Case]:
        del cfg
        return [
            Case(id="case-0", ticket="t", prompt="p"),
            Case(id="case-1", ticket="t", prompt="p"),
        ]

    def score(self, case: Case, run: CaseRun) -> dict[str, float]:
        del case, run
        return {}

    async def transport(
        self, case: Case, cfg: EvalConfig, tracker: EvalCostTracker, provider: ProviderConfig
    ) -> CaseRun:
        del cfg, tracker, provider
        if case.id == "case-1":
            raise KeyboardInterrupt
        return CaseRun(case_id=case.id, text="answered", messages=[])


def _meta(runs_dir: Path) -> dict[str, Any]:
    run_dir = next(d for d in runs_dir.iterdir() if d.is_dir())
    return json.loads((run_dir / "run.json").read_text())


def _isolate(runs_dir: Path, monkeypatch: pytest.MonkeyPatch, flushed: list[str]) -> None:
    monkeypatch.setattr(runner_mod, "RUNS_DIR", runs_dir)
    monkeypatch.setattr(runner_mod, "health_check", lambda p: ProviderHealth(True))
    monkeypatch.setattr(runner_mod, "pin_settings", lambda p: None)
    monkeypatch.setattr(runner_mod, "_log_trace", lambda *a, **k: None)
    monkeypatch.setattr(runner_mod, "_flush_traces", lambda project: flushed.append(project))
    monkeypatch.setitem(runner_mod.SUITE_REGISTRY, SUITE_NAME, lambda cfg: _InterruptingSuite())


async def test_resume_with_unknown_run_id_stops_before_creating_anything(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    _isolate(runs_dir, monkeypatch, [])

    with pytest.raises(SystemExit) as exit_info:
        await run_suite(eval_config(), RunOptions(suite=SUITE_NAME, resume=f"{SUITE_NAME}-typo"))

    assert f"{SUITE_NAME}-typo" in str(exit_info.value)
    assert list(runs_dir.iterdir()) == [], "a failed --resume must not leave a run directory"


async def test_a_sequential_run_interrupted_mid_case_is_recorded_as_stopped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs_dir = tmp_path / "runs"
    flushed: list[str] = []
    _isolate(runs_dir, monkeypatch, flushed)

    # The interrupt is absorbed: the run publishes what it did get, and
    # run.json is what has to remember that it was cut short.
    await run_suite(eval_config(), RunOptions(suite=SUITE_NAME))

    meta = _meta(runs_dir)
    assert meta["status"] == "stopped"
    assert meta["finished_at"]
    assert flushed == [PROJECT], "buffered traces must be flushed on the way out"


async def test_a_concurrent_run_interrupted_mid_run_is_recorded_as_stopped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs_dir = tmp_path / "runs"
    flushed: list[str] = []
    _isolate(runs_dir, monkeypatch, flushed)

    async def _interrupted(*args: object, **kwargs: object) -> str | None:
        raise KeyboardInterrupt

    monkeypatch.setattr(runner_mod, "_run_cases_concurrently", _interrupted)

    await run_suite(eval_config(), RunOptions(suite=SUITE_NAME, concurrency=4))

    meta = _meta(runs_dir)
    assert meta["status"] == "stopped"
    assert meta["finished_at"]
    assert flushed == [PROJECT], "buffered traces must be flushed on the way out"
