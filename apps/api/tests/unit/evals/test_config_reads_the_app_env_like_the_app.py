"""The eval config seeds the process from apps/api/.env the way the app does, so a test run never reads it.

Regression: load_config parsed apps/api/.env by hand into os.environ, past the
suite's fence, so every eval unit test put a developer's real keys (OpenRouter,
GitHub, Infisical) into the test process.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from scripts.evals.core import providers

PROBE = "GAIA_EVAL_ENV_PROBE"


@pytest.fixture(autouse=True)
def app_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the config at a throwaway env file, and restore PROBE whatever a test sets."""
    env_file = tmp_path / ".env"
    env_file.write_text(f'{PROBE}="from-the-env-file"\n')
    monkeypatch.setattr(providers, "APP_ENV_PATH", env_file)
    monkeypatch.setenv(PROBE, "")
    monkeypatch.delenv(PROBE)
    return env_file


def test_a_test_run_never_seeds_the_process_from_the_env_file() -> None:
    providers.load_config()

    assert PROBE not in os.environ


def test_an_eval_run_seeds_the_process_from_the_env_file(monkeypatch: pytest.MonkeyPatch) -> None:
    """Outside the suite, where dotenv is enabled, the keys arrive with quotes stripped as dotenv does."""
    monkeypatch.delenv("PYTHON_DOTENV_DISABLED")

    providers.load_config()

    assert os.environ[PROBE] == "from-the-env-file"
