"""Decisions-protocol transport for Jev, served by OpenRouter or Vercel AI Gateway.

Jev answers structured questions instead of producing text, so it is refused by
chat/completions and served by a decisions endpoint: {model, state, questions}
in, {answers, usage} back. Both gateways speak that shape; only the URL, the
model id, and the credential differ, so one client covers both.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import json
from time import perf_counter
from typing import Literal, Protocol
from urllib.parse import urljoin

import httpx
from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError

from app.config.settings import settings
from app.constants.browser import JEV_GATEWAY_MAX_ATTEMPTS, JEV_GATEWAY_TIMEOUT_SECONDS
from app.constants.log_tags import LogTag
from app.services.browser.exceptions import BrowserAutomationError, BrowserUnavailableError
from shared.py.wide_events import log

# A criterion or instruction: TypeSafe accepts a string or structured JSON.
JsonInput = str | dict[str, object] | list[object]

_RETRY_STATUSES = frozenset({429, 503, 529})
_VERCEL = "vercel"


class JevGatewayError(BrowserAutomationError):
    """The gateway refused or failed the evaluation; no action was executed."""


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

    #: Each question's answer as sent: only the one a decision reads is validated, as a JevChoiceAnswer.
    answers: dict[str, JsonValue]
    usage: JevUsage | None = None
    latency_ms: int = 0
    #: Which gateway served this answer; set by the client.
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
    """One credential and model on an HTTP client it borrows; open_jev_client owns and closes it."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        url: str,
        provider: str,
        client: httpx.AsyncClient,
    ) -> None:
        self.model = model
        self.provider = provider
        self._url = url
        # Header names are case-insensitive: a change of case is an equivalent mutant.
        self._headers = {"Authorization": f"Bearer {api_key}"}  # pragma: no mutate
        self._client = client

    async def evaluate(self, request: JevEvaluationRequest) -> JevEvaluation:
        """POST the questions; retries transient 429/503/529 with backoff."""
        body = {"model": self.model, **request.model_dump()}
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
                    f"{_error_message(response)}; no action executed."
                )
            try:
                evaluation = JevEvaluation.model_validate_json(response.content)
            except ValidationError as exc:
                log.warning(
                    f"{LogTag.BROWSER} Jev gateway sent an unreadable answer",
                    provider=self.provider,
                    request_bytes=request_bytes,
                    latency_ms=_elapsed_ms(attempt_started),
                    error_type=type(exc).__name__,
                )
                raise JevGatewayError(
                    f"Jev decisions sent an unreadable answer ({self.provider}): "
                    f"{response.text[:200]}; no action executed."
                ) from exc
            evaluation.latency_ms = _elapsed_ms(started)
            evaluation.provider = self.provider
            return evaluation
        # Unreachable: the last attempt returns or raises. Here for the type checker.
        raise JevGatewayError(  # pragma: no mutate
            f"Jev decisions unavailable ({self.provider}); no action executed."  # pragma: no mutate
        )


class JevDecider(Protocol):
    """What a decision needs of a gateway: the model it names, and one evaluation."""

    model: str

    async def evaluate(self, request: JevEvaluationRequest) -> JevEvaluation: ...


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


_OPENROUTER_API_URL = "https://openrouter.ai/api/v1"
# Vercel AI Gateway evaluation endpoint: same {model, state, questions} body
# and {answers, usage} response as the OpenRouter decisions route.
_VERCEL_EVALUATE_URL = "https://ai-gateway.vercel.sh/v1/evaluate"


def _openrouter_decisions_url() -> str:
    """Return OpenRouter's decisions route, which sits beside v1 under /api.

    A development OPENROUTER_BASE_URL (a test stack's model server) moves it with
    the rest of OpenRouter; production refuses to boot with that override set.
    """
    base = settings.OPENROUTER_BASE_URL or _OPENROUTER_API_URL
    # A base given with its trailing slash resolves the same: "v1//" + "../" still lands on /api.
    return urljoin(f"{base}/", "../alpha/decisions")


def _build_jev_client(http: httpx.AsyncClient) -> JevGatewayClient:
    """Return the decisions gateway BROWSER_JEV_PROVIDER names, on http.

    The one gateway serves every decision; one it fails, after its own retries,
    fails the step. Raises BrowserUnavailableError when its key is not configured.
    """
    provider = settings.BROWSER_JEV_PROVIDER
    if provider == _VERCEL:
        api_key, model, url = (
            settings.BROWSER_JEV_VERCEL_API_KEY,
            settings.BROWSER_JEV_VERCEL_MODEL,
            _VERCEL_EVALUATE_URL,
        )
    else:
        api_key, model, url = (
            settings.OPENROUTER_API_KEY,
            settings.BROWSER_USE_JEV_MODEL,
            _openrouter_decisions_url(),
        )
    if not api_key:
        raise BrowserUnavailableError(f"Jev's {provider} gateway has no API key configured.")
    return JevGatewayClient(api_key=api_key, model=model, url=url, provider=provider, client=http)


@asynccontextmanager
async def open_jev_client() -> AsyncIterator[JevGatewayClient]:
    """Open a run's decisions gateway on one HTTP client closed when the run ends."""
    async with httpx.AsyncClient(timeout=JEV_GATEWAY_TIMEOUT_SECONDS) as http:
        yield _build_jev_client(http)
