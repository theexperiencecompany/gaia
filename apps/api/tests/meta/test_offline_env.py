"""The suite's import-time env fence: a developer .env must not reach tracing, telemetry or snapshots."""

import os

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
    "ENABLE_COMMS_OPENUI": "true",
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
