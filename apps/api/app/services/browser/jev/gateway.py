"""Decisions-protocol transport for Jev, served by OpenRouter or Vercel AI Gateway.

Jev answers structured questions instead of producing text, so it is refused by
chat/completions and served by a decisions endpoint: {model, state, questions}
in, {answers, usage} back. Both gateways speak that shape; only the URL, the
model id, and the credential differ, so one client covers both.
"""

from __future__ import annotations

import asyncio
import json
from time import monotonic, perf_counter
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field

from app.config.settings import settings
from app.constants.browser import (
    JEV_GATEWAY_MAX_ATTEMPTS,
    JEV_GATEWAY_TIMEOUT_SECONDS,
    JEV_OUT_OF_CREDIT_SECONDS,
)
from app.constants.log_tags import LogTag
from app.services.browser.exceptions import BrowserAutomationError, BrowserUnavailableError
from shared.py.wide_events import log

# A criterion or instruction: TypeSafe accepts a string or structured JSON.
JsonInput = str | dict[str, object] | list[object]

_RETRY_STATUSES = frozenset({429, 503, 529})
_PAYMENT_REQUIRED = 402
_VERCEL = "vercel"


class JevGatewayError(BrowserAutomationError):
    """The gateway refused or failed the evaluation; no action was executed."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class _GatewayErrorDetail(BaseModel):
    """One error object in a failed decisions response, read only for its message."""

    model_config = ConfigDict(extra="ignore")

    message: str | None = None
    type: str | None = None


class _GatewayErrorBody(BaseModel):
    """A failed decisions response, read only for the error it carries."""

    model_config = ConfigDict(extra="ignore")

    error: _GatewayErrorDetail | None = None


class JevQuestion(BaseModel):
    """One ``choice`` question: pick an option name from ``criteria``."""

    type: Literal["choice"] = "choice"
    instructions: JsonInput
    criteria: dict[str, JsonInput]


class JevEvaluationRequest(BaseModel):
    state: dict[str, object]
    questions: dict[str, JevQuestion]


class JevChoiceAnswer(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: Literal["choice"]
    choice: str
    probabilities: dict[str, float] = Field(default_factory=dict)
    # Jev always returns a confidence; absent means the answer is malformed, which
    # decision.py rejects rather than defaulting away.
    confidence: float | None = None


class JevUsage(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    input_tokens: int = Field(default=0, alias="inputTokens")
    output_tokens: int = Field(default=0, alias="outputTokens")
    #: OpenRouter reports what the evaluation cost; Vercel reports it in provider metadata.
    cost: float | None = None


class _GatewayCostMeta(BaseModel):
    """The gateway's own cost report for one evaluation, when it sends one."""

    model_config = ConfigDict(extra="ignore")

    cost: str | float | int | None = None


class _ProviderMetadata(BaseModel):
    """Provider-specific envelope around an evaluation (Vercel gateway metadata)."""

    model_config = ConfigDict(extra="ignore")

    gateway: _GatewayCostMeta | None = None


class JevEvaluation(BaseModel):
    """The gateway's answer set plus what it cost and how long it took."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    answers: dict[str, JevChoiceAnswer]
    usage: JevUsage | None = None
    latency_ms: int = 0
    #: Which gateway served this answer; set by the client, so a failed-over
    #: decision is attributed to the gateway that actually answered.
    provider: str = ""
    provider_metadata: _ProviderMetadata | None = Field(default=None, alias="providerMetadata")

    @property
    def gateway_cost_usd(self) -> float | None:
        """What the gateway says this evaluation cost, or None when unreported."""
        if self.usage is not None and self.usage.cost is not None:
            return self.usage.cost
        if self.provider_metadata is None or self.provider_metadata.gateway is None:
            return None
        try:
            return float(self.provider_metadata.gateway.cost)
        except (TypeError, ValueError):
            return None


class JevGatewayClient:
    """Async client for one credential and model; safe to share across a run."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        url: str,
        provider: str,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.model = model
        self.provider = provider
        self._url = url
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._client = client or httpx.AsyncClient(timeout=JEV_GATEWAY_TIMEOUT_SECONDS)

    async def evaluate(self, request: JevEvaluationRequest) -> JevEvaluation:
        """POST the questions; retries transient 429/503/529 with backoff."""
        # The state is JSON-native already; json mode only guards a future field.
        body = {"model": self.model, **request.model_dump(mode="json")}
        request_bytes = len(json.dumps(body))
        started = perf_counter()
        for attempt in range(JEV_GATEWAY_MAX_ATTEMPTS):
            attempt_started = perf_counter()
            try:
                response = await self._client.post(self._url, json=body, headers=self._headers)
            except httpx.HTTPError as exc:
                log.warning(
                    f"{LogTag.BROWSER} Jev gateway request failed",
                    provider=self.provider,
                    attempt=attempt + 1,
                    max_attempts=JEV_GATEWAY_MAX_ATTEMPTS,
                    request_bytes=request_bytes,
                    latency_ms=_elapsed_ms(attempt_started),
                    error_type=type(exc).__name__,
                )
                raise JevGatewayError(
                    f"Jev decisions request failed: {exc} ({self.provider}); no action executed."
                ) from exc
            if response.is_error:
                log.warning(
                    f"{LogTag.BROWSER} Jev gateway refused",
                    provider=self.provider,
                    status_code=response.status_code,
                    error=_error_message(response),
                    attempt=attempt + 1,
                    max_attempts=JEV_GATEWAY_MAX_ATTEMPTS,
                    request_bytes=request_bytes,
                    latency_ms=_elapsed_ms(attempt_started),
                )
            if response.status_code in _RETRY_STATUSES and attempt < JEV_GATEWAY_MAX_ATTEMPTS - 1:
                await asyncio.sleep(0.5 * 2**attempt)
                continue
            if response.is_error:
                raise JevGatewayError(
                    f"Jev decisions returned HTTP {response.status_code}: "
                    f"{_error_message(response)}; no action executed.",
                    status_code=response.status_code,
                )
            evaluation = JevEvaluation.model_validate(response.json())
            evaluation.latency_ms = _elapsed_ms(started)
            evaluation.provider = self.provider
            return evaluation
        # Unreachable: the last attempt returns or raises. Here for the type checker.
        raise JevGatewayError(  # pragma: no mutate
            f"Jev decisions unavailable ({self.provider}); no action executed."  # pragma: no mutate
        )

    async def aclose(self) -> None:
        await self._client.aclose()


class JevFailoverClient:
    """A primary gateway with a second one behind it for the decisions the primary cannot serve.

    Both gateways answer the same {model, state, questions} shape, so when the
    primary exhausts its retries (rate limit, outage, transport failure) the
    same request goes to the fallback instead of costing the run a step. The
    provider flag still picks the primary; the fallback is whichever other
    gateway has a key configured.
    """

    def __init__(self, *, primary: JevGatewayClient, fallback: JevGatewayClient) -> None:
        self.primary = primary
        self.fallback = fallback
        self.model = primary.model
        #: Until when the primary is skipped: it refused on credit (402).
        self._primary_skipped_until = 0.0

    async def evaluate(self, request: JevEvaluationRequest) -> JevEvaluation:
        if self._primary_skipped_until > monotonic():
            return await self.fallback.evaluate(request)
        try:
            return await self.primary.evaluate(request)
        except JevGatewayError as exc:
            if exc.status_code == _PAYMENT_REQUIRED:
                # Every request would be refused the same way until the account is topped up.
                self._primary_skipped_until = monotonic() + JEV_OUT_OF_CREDIT_SECONDS
            log.warning(
                f"{LogTag.BROWSER} Jev decision failed over",
                provider=self.primary.provider,
                fallback_provider=self.fallback.provider,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            return await self.fallback.evaluate(request)

    async def aclose(self) -> None:
        await self.primary.aclose()
        await self.fallback.aclose()


#: What the policy asks for a decision: one gateway, or one with a fallback behind it.
JevDecisionsClient = JevGatewayClient | JevFailoverClient


def _elapsed_ms(since: float) -> int:
    return round((perf_counter() - since) * 1000)


def _error_message(response: httpx.Response) -> str:
    try:
        error = _GatewayErrorBody.model_validate(response.json()).error
    except ValueError:
        return response.text[:200]
    if error is None:
        return response.text[:200]
    return str(error.message or error.type or response.text[:200])


_OPENROUTER_DECISIONS_URL = "https://openrouter.ai/api/alpha/decisions"
# Vercel AI Gateway evaluation endpoint: same {model, state, questions} body
# and {answers, usage} response as the OpenRouter decisions route.
_VERCEL_EVALUATE_URL = "https://ai-gateway.vercel.sh/v1/evaluate"


def build_jev_client() -> JevDecisionsClient:
    """Return the configured decisions gateway, with the other one behind it when it has a key.

    BROWSER_JEV_PROVIDER picks the primary. Raises BrowserUnavailableError when
    the primary's key is not configured.
    """
    gateways: dict[str, JevGatewayClient] = {}
    if settings.OPENROUTER_API_KEY:
        gateways["openrouter"] = JevGatewayClient(
            api_key=settings.OPENROUTER_API_KEY,
            model=settings.BROWSER_USE_JEV_MODEL,
            url=_OPENROUTER_DECISIONS_URL,
            provider="openrouter",
        )
    if settings.BROWSER_JEV_VERCEL_API_KEY:
        gateways[_VERCEL] = JevGatewayClient(
            api_key=settings.BROWSER_JEV_VERCEL_API_KEY,
            model=settings.BROWSER_JEV_VERCEL_MODEL,
            url=_VERCEL_EVALUATE_URL,
            provider=_VERCEL,
        )
    provider = settings.BROWSER_JEV_PROVIDER
    primary = gateways.pop(provider, None)
    if primary is None:
        raise BrowserUnavailableError(f"Jev's {provider} gateway has no API key configured.")
    fallback = next(iter(gateways.values()), None)
    return JevFailoverClient(primary=primary, fallback=fallback) if fallback else primary
