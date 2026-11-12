"""Transport for the JEV Decisions API, shared by every question asked of it (HIL, trigger gates).

One POST per call, validated where received. Failure raises — each caller
decides its own degradation (LLM fallback, ask, leave pending), never this
module.
"""

from collections.abc import Mapping

import httpx

from app.constants.hil import (
    HIL_JEV_MODEL_NAME,
    HIL_JEV_TIMEOUT_SECONDS,
    HIL_JEV_URL,
    JevFailure,
)
from app.constants.providers import CredentialProviderName
from app.models.jev_models import JevDecisionsResponse
from app.services.providers.provider_credentials_service import ProviderConfig, resolve


class JevUnconfiguredError(RuntimeError):
    """No OpenRouter key is saved or set, so JEV cannot be asked at all (a self-host without one)."""


# First match wins; anything else is an error, so it is alerted on.
_FAILURES: tuple[tuple[type[Exception] | tuple[type[Exception], ...], JevFailure], ...] = (
    (JevUnconfiguredError, JevFailure.UNCONFIGURED),
    ((TimeoutError, httpx.TimeoutException), JevFailure.TIMEOUT),
    # Pydantic's ValidationError and a body that is not JSON are both ValueErrors.
    (ValueError, JevFailure.MALFORMED),
)


# Built at import, so a caller's deadline never pays first-use setup (lazy transport imports,
# the CA bundle load) synchronously on the event loop; it also keeps the TLS connection pooled.
jev_http_client = httpx.AsyncClient(timeout=HIL_JEV_TIMEOUT_SECONDS)


def jev_failure(error: Exception) -> JevFailure:
    """Name why a JEV call, or the read of its answer, gave nothing usable; anything unforeseen is ERROR."""
    return next(
        (failure for kinds, failure in _FAILURES if isinstance(error, kinds)), JevFailure.ERROR
    )


async def post_decisions(
    state: Mapping[str, object], questions: Mapping[str, Mapping[str, object]]
) -> JevDecisionsResponse:
    """One Decisions call on the saved or env OpenRouter key; raises on a missing key, transport failure, or a malformed body."""
    config: ProviderConfig | None = await resolve(CredentialProviderName.OPENROUTER)
    key = config.api_key if config else None
    if not key:
        raise JevUnconfiguredError("No OpenRouter key saved or set; cannot reach the JEV judge")
    resp = await jev_http_client.post(
        HIL_JEV_URL,
        json={"model": HIL_JEV_MODEL_NAME, "state": state, "questions": questions},
        headers={"Authorization": f"Bearer {key}"},
    )
    resp.raise_for_status()
    return JevDecisionsResponse.model_validate(resp.json())
