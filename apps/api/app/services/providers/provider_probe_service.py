"""Live-connectivity probe for a chat provider credential, before anything trusts it.

The setup API's test route and the CLI's first-boot save (app/scripts/save_provider.py)
both call probe_provider, so gaia up refuses exactly the keys the wizard refuses.
Details never carry credentials: provider error messages are redacted, URLs carry no query.
"""

from dataclasses import dataclass, field
import re
from typing import TypedDict, cast

import httpx

from app.constants.llm import OPENAI_API_URL, OPENROUTER_API_URL, LLMProviderName
from app.constants.providers import (
    LLM_MODEL_PROFILES,
    CredentialProviderName,
    ProviderTestFailure,
)
from app.services.providers.provider_registry import PROVIDER_SPECS
from app.services.providers.provider_setup_service import (
    allows_private_endpoint,
    assert_endpoint_safe,
)

_GEMINI_MODELS_URL = "https://generativelanguage.googleapis.com/v1beta/models"
_CANONICAL_API_URLS: dict[CredentialProviderName, str] = {
    CredentialProviderName.OPENROUTER: OPENROUTER_API_URL,
    CredentialProviderName.OPENAI: OPENAI_API_URL,
}
_PROBE_TIMEOUT_SECONDS = 10.0
# OpenAI refuses a cap of 1 (400 "max_tokens ... reached"); reasoning models answer 200 at 16.
_PROBE_MAX_COMPLETION_TOKENS = 16
_PROBE_PROMPT = "Reply with OK."
_AUTH_REJECTED_STATUSES = frozenset({401, 403})
_RATE_LIMITED_STATUS = 429
# OpenAI echoes a rejected key back in its error message.
_API_KEY_RE = re.compile(r"\bsk-[\w*.-]+")


@dataclass(frozen=True)
class ProbeResult:
    """One probe's outcome; the detail never carries credentials."""

    ok: bool
    detail: str
    failure: ProviderTestFailure | None = None
    models: list[str] = field(default_factory=list)


def _not_configured(detail: str) -> ProbeResult:
    return ProbeResult(ok=False, detail=detail, failure=ProviderTestFailure.NOT_CONFIGURED)


def _http_failure(status_code: int) -> ProviderTestFailure:
    if status_code in _AUTH_REJECTED_STATUSES:
        return ProviderTestFailure.AUTH_REJECTED
    if status_code == _RATE_LIMITED_STATUS:
        return ProviderTestFailure.RATE_LIMITED
    return ProviderTestFailure.REFUSED


class _WireErrorDetail(TypedDict, total=False):
    """The object form of an OpenAI-wire error: {"error": {"message": ...}}."""

    message: str


class _WireError(TypedDict, total=False):
    """An OpenAI-wire error body; the error is an object, or a bare string on a scope failure."""

    error: _WireErrorDetail | str


class _GeminiModel(TypedDict, total=False):
    """One entry of a name-keyed model list, e.g. {"name": "models/gemini-..."}."""

    name: str


class _NamedModelList(TypedDict, total=False):
    """The {"models": [{"name": ...}]} envelope Gemini's listModels and Ollama's /api/tags return."""

    models: list[_GeminiModel]


async def probe_provider(
    provider: CredentialProviderName,
    *,
    api_key: str | None,
    base_url: str | None,
    model: str | None,
) -> ProbeResult:
    """Probe one provider endpoint; its listed models come back sorted.

    A base-url provider whose endpoint fails the SSRF guard raises a 422 instead
    of a soft failure; ollama may be private.
    """
    if PROVIDER_SPECS[provider].preset.needs_base_url:
        await assert_endpoint_safe(base_url, allow_private=allows_private_endpoint(provider))
    try:
        async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT_SECONDS) as client:
            if provider == CredentialProviderName.GEMINI:
                return await _probe_gemini(client, api_key)
            if provider == CredentialProviderName.OLLAMA:
                return await _probe_ollama(client, base_url)
            return await _probe_openai_wire(
                provider, client, api_key=api_key, base_url=base_url, model=model
            )
    except httpx.HTTPError as e:
        failure = (
            ProviderTestFailure.TIMEOUT
            if isinstance(e, httpx.TimeoutException)
            else ProviderTestFailure.UNREACHABLE
        )
        return ProbeResult(
            ok=False, detail=f"Could not reach {provider}: {type(e).__name__}", failure=failure
        )


async def _probe_openai_wire(
    provider: CredentialProviderName,
    client: httpx.AsyncClient,
    *,
    api_key: str | None,
    base_url: str | None,
    model: str | None,
) -> ProbeResult:
    """Run the one call GAIA makes on this lane: a tiny chat completion on its model.

    Listing models is not it: a restricted OpenAI key lacks api.model.read yet chats fine.
    """
    label = PROVIDER_SPECS[provider].preset.label
    # OpenRouter and OpenAI need no configurable endpoint — their API roots are
    # canonical; every other OpenAI-wire provider probes its configured base URL.
    if canonical_url := _CANONICAL_API_URLS.get(provider):
        if not api_key:
            return _not_configured(f"No {label} API key configured")
        api_url = canonical_url
    else:
        if not base_url:
            return _not_configured(f"No base URL configured for {label}")
        api_url = base_url.rstrip("/")
    model = model or LLM_MODEL_PROFILES[LLMProviderName(provider)].chat
    if not model:
        return _not_configured(f"No model configured for {label}")
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    response = await client.post(
        f"{api_url}/chat/completions",
        headers=headers,
        json={
            "model": model,
            "messages": [{"role": "user", "content": _PROBE_PROMPT}],
            "max_completion_tokens": _PROBE_MAX_COMPLETION_TOKENS,
        },
    )
    if response.is_success:
        return ProbeResult(ok=True, detail=f"Connected to {label}")
    reason = _wire_error_reason(response, api_key)
    failure = _http_failure(response.status_code)
    if failure is ProviderTestFailure.AUTH_REJECTED:
        return ProbeResult(ok=False, detail=f"{label} rejected the key: {reason}", failure=failure)
    return ProbeResult(
        ok=False, detail=f"{label} refused the test request: {reason}", failure=failure
    )


def _wire_error_reason(response: httpx.Response, api_key: str | None) -> str:
    """Return the provider's own error message with any key redacted, else the HTTP status."""
    fallback = f"HTTP {response.status_code}"
    try:
        body = response.json()
    except ValueError:
        return fallback
    if not isinstance(body, dict):
        return fallback
    payload: _WireError = cast(_WireError, body)
    error = payload.get("error")
    if isinstance(error, dict):
        detail: _WireErrorDetail = error
        message = detail.get("message")
    else:
        message = error
    if not message:
        return fallback
    if api_key:
        message = message.replace(api_key, "[redacted]")
    return _API_KEY_RE.sub("[redacted]", message)


async def _probe_gemini(
    client: httpx.AsyncClient,
    api_key: str | None,
) -> ProbeResult:
    if not api_key:
        return _not_configured("No Gemini API key configured")
    response = await client.get(_GEMINI_MODELS_URL, params={"key": api_key})
    if response.status_code != 200:
        return ProbeResult(
            ok=False,
            detail=f"Gemini returned HTTP {response.status_code}",
            failure=_http_failure(response.status_code),
        )
    payload: _NamedModelList = cast(_NamedModelList, response.json())
    listed: list[_GeminiModel] = payload.get("models", [])
    names = (str(m["name"]).removeprefix("models/") for m in listed if m.get("name"))
    return ProbeResult(ok=True, detail="Connected to Google Gemini", models=sorted(names))


async def _probe_ollama(
    client: httpx.AsyncClient,
    base_url: str | None,
) -> ProbeResult:
    if not base_url:
        return _not_configured("No Ollama base URL configured")
    response = await client.get(f"{base_url.rstrip('/')}/api/tags")
    if response.status_code != 200:
        return ProbeResult(
            ok=False,
            detail=f"Ollama returned HTTP {response.status_code}",
            failure=_http_failure(response.status_code),
        )
    payload: _NamedModelList = cast(_NamedModelList, response.json())
    listed: list[_GeminiModel] = payload.get("models", [])
    models = sorted(str(m["name"]) for m in listed if m.get("name"))
    return ProbeResult(ok=True, detail="Connected to Ollama", models=models)
