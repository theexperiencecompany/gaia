"""Count every model call and every fallback to the default model by how it ended.

The alerts read these: a provider failing, or rate limiting us, is felt by users before any
latency histogram moves. provider is one of LLMProviderName, or unknown when the call's
lane cannot be read off its config or client. Series are created at zero when the API and
the worker start serving metrics, so the first failure after a restart is an increase.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from enum import StrEnum

from prometheus_client import Counter

from app.constants.llm import LLMProviderName
from app.services.llm_metering import classify_error_family
from app.services.storage.metrics import _register_once

UNKNOWN_PROVIDER = "unknown"


class LLMCallOutcome(StrEnum):
    """How one model call ended, after its own retries."""

    OK = "ok"
    RATE_LIMITED = "rate_limited"
    FAILED = "failed"


class LLMFallbackOutcome(StrEnum):
    """How a fallback to the default model ended."""

    RECOVERED = "recovered"
    EXHAUSTED = "exhausted"


LLM_CALL_TOTAL = _register_once(
    "gaia_llm_call_total",
    lambda: Counter(
        name="gaia_llm_call_total",
        documentation="Model calls by provider and outcome, after retries",
        labelnames=("provider", "outcome"),
    ),
)

LLM_FALLBACK_TOTAL = _register_once(
    "gaia_llm_fallback_total",
    lambda: Counter(
        name="gaia_llm_fallback_total",
        documentation="Fallbacks to the default model; exhausted is a call the fallback failed too",
        labelnames=("outcome",),
    ),
)


def create_llm_series() -> None:
    """Create every LLM series at zero, so its first increment is visible."""
    for provider in (*(p.value for p in LLMProviderName), UNKNOWN_PROVIDER):
        for outcome in LLMCallOutcome:
            LLM_CALL_TOTAL.labels(provider, outcome.value)
    for fallback_outcome in LLMFallbackOutcome:
        LLM_FALLBACK_TOTAL.labels(fallback_outcome.value)


def observe_llm_call_ok(provider: LLMProviderName | None) -> None:
    """Count a model call that returned."""
    _count_call(provider, LLMCallOutcome.OK)


def observe_llm_call_failed(provider: LLMProviderName | None, error: BaseException) -> None:
    """Count a model call that raised a provider failure, apart when the provider rate limited us."""
    rate_limited = classify_error_family(error) == "rate_limit"
    _count_call(provider, LLMCallOutcome.RATE_LIMITED if rate_limited else LLMCallOutcome.FAILED)


def observe_llm_fallback(outcome: LLMFallbackOutcome) -> None:
    """Count a fallback to the default model by how it ended."""
    LLM_FALLBACK_TOTAL.labels(outcome.value).inc()


@contextmanager
def fallback_leg() -> Iterator[None]:
    """Count the fallback call inside the block as recovered when it returns, exhausted when it raises."""
    try:
        yield
    except Exception:
        observe_llm_fallback(LLMFallbackOutcome.EXHAUSTED)
        raise
    observe_llm_fallback(LLMFallbackOutcome.RECOVERED)


def _count_call(provider: LLMProviderName | None, outcome: LLMCallOutcome) -> None:
    LLM_CALL_TOTAL.labels(provider.value if provider else UNKNOWN_PROVIDER, outcome.value).inc()
