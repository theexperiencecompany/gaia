"""The suite's import-time env fence: a developer .env must not reach tracing, telemetry or snapshots."""

import os
from pathlib import Path
import subprocess
import sys

import pytest

from app.config.settings import settings

_FORCED_ENV = {
    "LANGSMITH_TRACING": "false",
    "LANGCHAIN_TRACING": "false",
    "LANGCHAIN_TRACING_V2": "false",
    "LANGFUSE_PUBLIC_KEY": "",
    "LANGFUSE_SECRET_KEY": "",
    "LANGFUSE_HOST": "",
    "ANONYMIZED_TELEMETRY": "false",
    "no_proxy": "*",
    "NO_PROXY": "*",
    "HOST": "http://localhost:8000",
    "POSTHOG_PROJECT_TOKEN": "",
    "POSTHOG_HOST": "",
    "ENABLE_CODE_MODE": "false",
    "ENABLE_HIL_LEDGER": "true",
}


@pytest.mark.parametrize(("name", "value"), sorted(_FORCED_ENV.items()))
def test_the_fence_forces_the_offline_value(name: str, value: str) -> None:
    assert os.environ.get(name) == value


def test_the_settings_singleton_was_built_behind_the_fence() -> None:
    """Settings bind at import, so a fence that runs after the first app import is too late."""
    assert settings.HOST == "http://localhost:8000"
    assert not settings.POSTHOG_PROJECT_TOKEN
    assert not settings.LANGFUSE_PUBLIC_KEY


def test_the_app_and_the_fixtures_share_one_test_database() -> None:
    """Regression: the fixtures read DATABASE_URL and the app POSTGRES_URL, so a local run setting one had no app engine."""
    assert os.environ["DATABASE_URL"]
    assert os.environ["DATABASE_URL"] == settings.POSTGRES_URL


_TEST_DB = "postgresql://gaia:gaia@localhost:5432/gaia_test"  # pragma: allowlist secret
_DEV_DB = "postgresql://gaia:gaia@localhost:5432/gaia_dev"  # pragma: allowlist secret


def _import_fence(**urls: str) -> subprocess.CompletedProcess[str]:
    """Import the fence in a fresh interpreter whose env sets only the given database URLs."""
    env = {k: v for k, v in os.environ.items() if k not in ("DATABASE_URL", "POSTGRES_URL")}
    return subprocess.run(
        [
            sys.executable,
            "-c",
            "import os, tests.offline_env; print(os.environ['DATABASE_URL'], os.environ['POSTGRES_URL'])",
        ],
        cwd=Path(__file__).resolve().parents[2],
        env={**env, **urls},
        capture_output=True,
        text=True,
        check=False,
    )


def test_a_second_test_database_fails_the_import_instead_of_being_overwritten() -> None:
    """A POSTGRES_URL naming another database than DATABASE_URL would point the app away from the fixtures."""
    result = _import_fence(DATABASE_URL=_TEST_DB, POSTGRES_URL=_DEV_DB)

    assert result.returncode != 0
    assert "POSTGRES_URL" in result.stderr


def test_a_lone_postgres_url_names_the_fixtures_database_too() -> None:
    """selfhost-smoke exports only POSTGRES_URL; the fixtures must follow it, not the CI container."""
    result = _import_fence(POSTGRES_URL=_DEV_DB)

    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == [_DEV_DB, _DEV_DB]
