"""The app owns the LLM retry policy — the provider SDK must not retry too.

Found by driving one failing turn against a provider returning 500: it produced
**40** upstream requests and took four minutes to surface an error.

``langchain-openrouter`` defaults ``max_retries=2``, which hands the OpenRouter
SDK a backoff window of ``max_retries * 150_000`` ms — 300 seconds of internal
retrying *inside a single* ``ainvoke``. That nests under ``with_llm_retry``
(3 attempts) and then repeats for the fallback model, so the real budget was
never 3 attempts; the 120 s ``asyncio.timeout`` in ``ainvoke_llm`` was the only
thing stopping it, and it fired twice.

``with_llm_retry`` documents itself as "the single, canonical LLM retry". These
pin that claim: exactly one layer retries, so the attempt count and the timeout
mean what they say.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from app.agents.llm.client import (
    _build_default_llm,
    _sim_llm,
    init_custom_llm,
    init_openrouter_llm,
)
from app.constants.llm import LLM_RETRY_MAX_ATTEMPTS


@pytest.fixture(autouse=True)
def _openrouter_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """The hermetic conftest blanks credentials; these factories need a key."""
    from app.config.settings import settings

    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "test-key", raising=False)
    monkeypatch.setattr(settings, "DEV_LLM_API_KEY", "test-key", raising=False)
    monkeypatch.setattr(settings, "DEV_LLM_BASE_URL", "http://localhost:1", raising=False)
    monkeypatch.setattr(settings, "DEV_LLM_MODEL", "test/model", raising=False)
    _build_default_llm.cache_clear()
    _sim_llm.cache_clear()


@pytest.mark.unit
class TestLLMRetryBudget:
    def test_default_model_client_delegates_retry_to_the_app(self) -> None:
        assert _retries(_build_default_llm(0.0)) is False

    def test_sim_stub_client_delegates_retry_to_the_app(self) -> None:
        assert _retries(_sim_llm()) is False

    def test_primary_openrouter_client_delegates_retry_to_the_app(self) -> None:
        assert _retries(_construct(init_openrouter_llm)) is False

    def test_custom_dev_client_delegates_retry_to_the_app(self) -> None:
        assert _retries(_construct(init_custom_llm)) is False

    def test_the_app_still_retries(self) -> None:
        """Disabling SDK retry must not leave the system with no retry at all."""
        assert LLM_RETRY_MAX_ATTEMPTS > 1


def _construct(factory: Callable[[], Any]) -> Any:
    """Run a ``@lazy_provider`` factory's real body and unwrap the chat model.

    Via ``loader_func`` rather than resolving through the registry: registration
    is gated on credentials read at IMPORT time, which the hermetic fence blanks,
    so a registry lookup returns None in CI while passing for anyone whose local
    ``.env`` happened to hold a key.
    """
    llm = factory().loader_func()
    return getattr(llm, "default", llm)


def _retries(llm: Any) -> bool:
    """Whether the SDK client will run its own retry loop.

    Two SDKs answer this differently. The OpenRouter SDK ignores ``max_retries=0``
    (it then applies a one-hour default), so its truth lives in ``retry_config``,
    which ``without_sdk_retry`` sets to a non-backoff strategy. The OpenAI SDK
    (the custom dev lane runs ``ChatOpenAI``) has no such config and *does* honor
    ``max_retries=0`` — there the count is the honest signal.
    """
    sdk_config = getattr(getattr(llm, "client", None), "sdk_configuration", None)
    if sdk_config is not None:
        return getattr(sdk_config.retry_config, "strategy", None) == "backoff"
    return getattr(llm, "max_retries", None) not in (0, None)
