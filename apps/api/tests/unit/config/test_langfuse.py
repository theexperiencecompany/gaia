"""The Langfuse export budget, which is the whole of this module's tuning."""

import os
from types import SimpleNamespace

from app.config import langfuse as langfuse_config
from app.config.langfuse import (
    LANGFUSE_EXPORT_TIMEOUT_SECONDS,
    LANGFUSE_FLUSH_AT,
    LANGFUSE_FLUSH_AT_ENV,
)


def test_the_export_budget_fits_the_collector() -> None:
    """Five seconds was shared by serialization and six retries; 512 spans overflowed the ingress."""
    assert LANGFUSE_EXPORT_TIMEOUT_SECONDS == 10
    assert LANGFUSE_FLUSH_AT == 128


def test_the_batch_size_is_set_through_the_variable_the_sdk_reads(monkeypatch) -> None:
    """The SDK ignores flush_at when the env var is unset, so the variable is the real knob."""
    monkeypatch.delenv(LANGFUSE_FLUSH_AT_ENV, raising=False)
    try:
        langfuse_config._configure_export_env()

        assert os.environ[LANGFUSE_FLUSH_AT_ENV] == "128"
    finally:
        os.environ.pop(LANGFUSE_FLUSH_AT_ENV, None)


def test_the_client_is_initialized_before_a_handler_is_built(monkeypatch) -> None:
    """The handler resolves the singleton by key; building one first would take SDK defaults."""
    calls: list[str] = []
    monkeypatch.setattr(langfuse_config, "_langfuse_configured", lambda: True)
    monkeypatch.setattr(
        langfuse_config, "providers", SimpleNamespace(get=lambda name: calls.append(name))
    )
    monkeypatch.setattr(langfuse_config, "CallbackHandler", lambda: calls.append("handler"))

    langfuse_config.build_langfuse_callback()

    assert calls == ["langfuse", "handler"]
