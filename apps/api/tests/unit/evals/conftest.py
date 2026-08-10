"""Shared isolation for tests that drive the real eval run loop.

``run_suite`` writes journals, pins provider settings and talks to Opik. Every
test that exercises it needs the same four things neutralised, so they live here
once rather than being re-monkeypatched per test.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from scripts.evals.core import runner as runner_mod
from scripts.evals.core.providers import EvalConfig, ProviderConfig
from scripts.evals.core.runner import Suite
from scripts.evals.core.types import ProviderHealth


def eval_config() -> EvalConfig:
    """A single fake provider on a dead port — nothing here may reach a network."""
    provider = ProviderConfig(
        name="fake",
        lane="custom",
        base_url="http://localhost:9",
        api_key="test-key",
        model="fake-model",
        budget_usd=1.0,
        price_in_per_1m=0.0,
        price_out_per_1m=0.0,
    )
    return EvalConfig(
        providers={"fake": provider},
        rotation_order=["fake"],
        default_max_usd=1.0,
        judge={"base_url_env": "X", "api_key_env": "Y"},
    )


@pytest.fixture
def register_suite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Callable[[str, Suite], Suite]:
    """Register a suite against a temp runs dir, with no network and no Opik."""

    def _register(name: str, suite: Suite) -> Suite:
        monkeypatch.setattr(runner_mod, "RUNS_DIR", tmp_path / "runs")
        monkeypatch.setattr(runner_mod, "health_check", lambda p: ProviderHealth(True))
        monkeypatch.setattr(runner_mod, "pin_settings", lambda p: None)
        monkeypatch.setattr(runner_mod, "_log_trace", lambda *a, **k: None)
        monkeypatch.setattr(runner_mod, "_flush_traces", lambda *a, **k: None)
        monkeypatch.setitem(runner_mod.SUITE_REGISTRY, name, lambda cfg: suite)
        return suite

    return _register
