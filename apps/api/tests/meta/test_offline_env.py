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


_API_DIR = Path(__file__).resolve().parents[2]


def test_the_settings_never_read_the_developers_env_file() -> None:
    """Regression: settings.py loaded apps/api/.env at import, before the fence, so a local OPENROUTER_API_KEY reached the suite."""
    assert os.environ["PYTHON_DOTENV_DISABLED"] == "1"
    assert not settings.OPENROUTER_API_KEY


def test_a_credential_exported_in_the_shell_never_reaches_the_settings() -> None:
    """The settings singleton binds at import, so the fence must run first or a shell key is already inside it."""
    probe = (
        "import tests.offline_env\n"
        "from app.config.settings import settings\n"
        "print(repr(settings.TAVILY_API_KEY))"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=_API_DIR,
        env={**os.environ, "TAVILY_API_KEY": "tvly-from-the-shell", "LOG_LEVEL": "CRITICAL"},
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip().splitlines()[-1] == "''"


def test_a_key_a_live_run_declares_reaches_the_settings() -> None:
    """A live-credential tier names its keys when it is started, and those alone come through."""
    probe = (
        "import tests.offline_env\n"
        "from app.config.settings import settings\n"
        "print(repr(settings.TAVILY_API_KEY), repr(settings.OPENROUTER_API_KEY))"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=_API_DIR,
        env={
            **os.environ,
            "HERMETIC_ALLOW_KEYS": "TAVILY_API_KEY",
            "TAVILY_API_KEY": "tvly-declared",
            "OPENROUTER_API_KEY": "sk-or-undeclared",
            "LOG_LEVEL": "CRITICAL",
        },
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip().splitlines()[-1] == "'tvly-declared' ''"
