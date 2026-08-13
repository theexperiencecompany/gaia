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

from typing import Any

import pytest

from app.agents.llm.client import (
    _build_default_llm,
    _sim_llm,
    init_openrouter_llm,
)
from app.agents.llm.types import LLMProviderKey
from app.constants.llm import LLM_RETRY_MAX_ATTEMPTS
from app.core.lazy_loader import providers


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
        init_openrouter_llm()
        assert _retries(_resolve(LLMProviderKey.OPENROUTER)) is False

    # The custom dev endpoint (init_custom_llm) carries the same setting, but its
    # @lazy_provider registration is gated on DEV_LLM_* keys read at import time,
    # which the hermetic conftest blanks — so it cannot be resolved here. Under
    # GAIA_SIM_MODE it returns _sim_llm(), which the case above covers.

    def test_the_app_still_retries(self) -> None:
        """Disabling SDK retry must not leave the system with no retry at all."""
        assert LLM_RETRY_MAX_ATTEMPTS > 1


def _resolve(key: LLMProviderKey) -> Any:
    """The concrete chat model a registered provider resolves to, unwrapping the
    ``configurable_fields`` runnable the factories return."""
    instance = providers.get(key)
    return getattr(instance, "default", instance)


def _retries(llm: Any) -> bool:
    """Whether the SDK client will run its own retry loop.

    Asserted on the config the SDK actually reads at request time, not on
    ``max_retries``: that kwarg cannot express "off" — setting it to 0 only stops
    langchain passing a config, and the SDK then applies its own one-hour default.
    """
    config = llm.client.sdk_configuration.retry_config
    return getattr(config, "strategy", None) == "backoff"
