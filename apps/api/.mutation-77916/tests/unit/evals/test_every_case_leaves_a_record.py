"""A case must never vanish from a run.

Provider rotation used to advance a single counter that was initialised once,
outside the case loop. One case that exhausted the rotation left the counter at
``len(healthy)``, so every later case skipped the attempt loop entirely: no
request, no error, and — because the fallback record was guarded on an error
having been seen — no journal entry either. The run simply reported fewer cases
than it was given, and nothing said so.

A silently dropped case is worse than a failed one: a failure is a measurement,
an absence is a lie by omission that also shrinks the denominator.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

import pytest
from scripts.evals.core import runner as runner_mod
from scripts.evals.core.journal import RunJournal
from scripts.evals.core.providers import EvalConfig, ProviderConfig
from scripts.evals.core.runner import RunOptions, Suite, run_suite
from scripts.evals.core.types import Case, CaseRun, ProviderError, ProviderHealth

CASE_COUNT = 4


def _config() -> EvalConfig:
    providers = {
        name: ProviderConfig(
            name=name,
            lane="custom",
            base_url="http://localhost:9",
            api_key="test-key",
            model=f"{name}-model",
            budget_usd=1.0,
            price_in_per_1m=0.0,
            price_out_per_1m=0.0,
        )
        for name in ("alpha", "beta")
    }
    return EvalConfig(
        providers=providers,
        rotation_order=["alpha", "beta"],
        default_max_usd=1.0,
        judge={"base_url_env": "X", "api_key_env": "Y"},
    )


class _FirstCaseBurnsRotation(Suite):
    """Case 0 makes every provider raise ProviderError; the rest are healthy.

    That is the exact shape the bug needed: rotation exhausted once, early.
    """

    name = "burns-rotation"
    project = "test-project"
    label = "Burns Rotation"

    def __init__(self, cfg: EvalConfig) -> None:
        del cfg
        self.attempted: list[str] = []

    def load_cases(self, cfg: EvalConfig) -> list[Case]:
        del cfg
        return [
            Case(id=f"case-{i}", ticket="t", prompt="q?", expected={"score": {"gates": []}})
            for i in range(CASE_COUNT)
        ]

    async def transport(
        self, case: Case, cfg: EvalConfig, tracker: object, provider: object
    ) -> CaseRun:
        del cfg, tracker
        self.attempted.append(case.id)
        if case.id == "case-0":
            raise ProviderError(getattr(provider, "name", "?"), "simulated lane failure")
        return CaseRun(case_id=case.id, text="an answer", messages=[])

    def score(self, case: Case, run: CaseRun) -> dict[str, float]:
        del case, run
        return {"communicate": 1.0}


@pytest.fixture
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> _FirstCaseBurnsRotation:
    suite = _FirstCaseBurnsRotation(_config())
    monkeypatch.setattr(runner_mod, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(runner_mod, "health_check", lambda p: ProviderHealth(True))
    monkeypatch.setattr(runner_mod, "pin_settings", lambda p: None)
    monkeypatch.setattr(runner_mod, "_log_trace", lambda *a, **k: None)
    monkeypatch.setattr(runner_mod, "_flush_traces", lambda *a, **k: None)
    monkeypatch.setitem(runner_mod.SUITE_REGISTRY, "burns-rotation", lambda cfg: suite)
    return suite


async def test_rotation_exhausted_on_one_case_does_not_drop_the_rest(
    isolated: _FirstCaseBurnsRotation, tmp_path: Path
) -> None:
    run_dir = await run_suite(_config(), RunOptions(suite="burns-rotation", no_finalize=True))

    records = RunJournal(runner_mod.RUNS_DIR, run_dir.name).records()
    recorded = {str(r["case_id"]) for r in records}
    assert recorded == {f"case-{i}" for i in range(CASE_COUNT)}, (
        "every case must leave a record; missing "
        f"{ {f'case-{i}' for i in range(CASE_COUNT)} - recorded }"
    )

    # And the later cases must have actually been ATTEMPTED, not just recorded
    # as unrun — rotation resets, so a healthy provider is available again.
    assert "case-3" in isolated.attempted, "later cases were never sent to a provider"

    by_case: dict[str, Any] = {str(r["case_id"]): r for r in records}
    assert by_case["case-3"]["status"] == "passed"


async def test_a_case_that_never_ran_is_recorded_as_errored(
    isolated: _FirstCaseBurnsRotation, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With every lane over budget there is nothing to attempt — the case still
    has to appear, labelled unrun, rather than disappearing from the count."""

    class _AllOverBudget:
        total_exceeded = False
        exceeded_budget: ClassVar[set[str]] = {"alpha", "beta"}
        total_input = 0
        total_output = 0
        case_input: ClassVar[dict[str, int]] = {}
        case_output: ClassVar[dict[str, int]] = {}

        def set_provider(self, name: str) -> None:
            del name

        def case_totals(self, case_id: str) -> tuple[int, int]:
            del case_id
            return (0, 0)

        def case_scope(self, case_id: str) -> Any:
            del case_id

            class _Scope:
                def __enter__(self) -> None:
                    return None

                def __exit__(self, *args: object) -> None:
                    return None

            return _Scope()

    monkeypatch.setattr(runner_mod, "EvalCostTracker", lambda *a, **k: _AllOverBudget())
    run_dir = await run_suite(_config(), RunOptions(suite="burns-rotation", no_finalize=True))

    records = RunJournal(runner_mod.RUNS_DIR, run_dir.name).records()
    assert len(records) == CASE_COUNT, "an unrunnable case must still be journaled"
    assert all(r["status"] == "errored" for r in records)
    assert "over budget" in str(records[0]["error"])
