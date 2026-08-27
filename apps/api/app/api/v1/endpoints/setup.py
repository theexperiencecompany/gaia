"""Instance setup API — first-run status and provider configuration (self-host).

Owns the ``/setup`` surface from ``.agents/plans/selfhost-contracts.md`` (A4):
a status probe plus the display-only provider catalog for the web setup wizard
(public only under AUTH_MODE=local)
and instance-admin-gated
management of provider credentials — masked listing, upsert, delete, live
connectivity test, and setup-step completion tracking in instance settings.
Every route except ``GET /status`` requires the instance administrator (see
``require_instance_admin``). Credentials themselves live behind
``provider_credentials_service``; this module never stores or logs raw keys.

Caller-supplied and stored base_urls are SSRF-guarded at both save and probe
time: a URL is accepted only when every address its hostname resolves to is
public, with one exception — the ``ollama`` provider is expected to run
locally (``http://host.docker.internal:11434``, ``http://localhost:11434``,
etc.) so its base_url is allowed to be private/link-local and skips the
public-IP DNS check. ``OLLAMA_BASE_URL`` server-side env still works as a
fallback for deployments that prefer it.
"""

from typing import Annotated, Any, Literal
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request
import httpx
from pydantic import BaseModel, Field

from app.api.v1.dependencies.instance_admin import require_instance_admin
from app.api.v1.middleware.rate_limiter import limiter
from app.config.settings import settings
from app.constants.llm import OPENROUTER_MODELS_URL
from app.constants.providers import CREDENTIAL_PROVIDERS, PRESETS
from app.db.repositories.instance_settings import instance_settings_repository
from app.db.repositories.local_credentials import local_credentials_repository
from app.db.repositories.provider_credentials import provider_credentials_repository
from app.models.user_models import AuthenticatedUser
from app.services.providers.provider_credentials_service import (
    ProviderConfig,
    _env_fallback,
    delete as delete_provider_config,
    invalidate as invalidate_provider_cache,
    resolve as resolve_provider_config,
    upsert as upsert_provider_config,
)
from app.services.startup_validation import is_payment_setup
from app.utils.url_safety import assert_public_http_url, assert_safe_url_shape
from shared.py.wide_events import log

router = APIRouter(tags=["Setup"])

# Doc key under which wizard progress is persisted in instance settings.
SETUP_DOC_KEY = "setup"

# Providers that constitute a working LLM lane for ``needs_setup`` — NOT every
# credential provider: tavily (search) plus the composio/e2b/openai/resend/
# cloudinary/google_oauth/firecrawl tool & integration keys are configured
# here too but cannot serve chat.
_LLM_PROVIDER_KEYS = ("openrouter", "gemini", "ollama", "custom")

# Providers whose outbound traffic targets a caller-configurable base_url — the
# only stored base_urls the SSRF guard applies to (openrouter/gemini dial
# canonical endpoints; tavily is a tool key).
_BASE_URL_PROVIDERS = frozenset({"custom", "ollama"})

_PRESET_NAMES = Literal["opencode", "nous"]

_GEMINI_MODELS_URL = "https://generativelanguage.googleapis.com/v1beta/models"
_PROBE_TIMEOUT_SECONDS = 10.0

_PRIVATE_URL_HINT = (
    "This URL looks private or unreachable — use a public endpoint or set "
    "OLLAMA_BASE_URL in your .env for local Ollama"
)


class ProviderCredentialBody(BaseModel):
    """Provider payload shared by upsert and test.

    ``preset`` prefills the endpoint + default model server-side so configuring
    OpenCode/Nous is paste-an-API-key-only.
    """

    preset: _PRESET_NAMES | None = None
    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None


class SetupCompleteBody(BaseModel):
    step: str = Field(min_length=1)


@router.get("/status")
async def get_setup_status() -> dict[str, Any]:
    """First-run status for the web setup wizard and desktop CLI.

    Public only under AUTH_MODE=local (middleware conditionally excludes it
    there); in workos mode the route requires a session like any other.
    """
    log.set(operation="setup_status", auth_mode=settings.AUTH_MODE)
    has_admin_account = await local_credentials_repository.any_exists()
    configured = {p: await _is_usably_configured(p) for p in CREDENTIAL_PROVIDERS}
    return {
        "auth_mode": settings.AUTH_MODE,
        "has_admin_account": has_admin_account,
        "needs_setup": _needs_setup(has_admin_account, configured),
        "billing_enabled": settings.billing_enabled,
        "providers": {p: {"configured": c} for p, c in configured.items()},
        "plans_seeded": await is_payment_setup(),
    }


@router.get("/catalog")
async def get_provider_catalog() -> dict[str, Any]:
    """The provider catalog the setup wizard and Settings render from.

    Serves ``app.constants.providers.PRESETS`` — display metadata only (no
    secrets, no configuration state) — partitioned by role so clients can
    render every card without shipping their own copy of the catalog:

    - ``providers``: one entry per credential-store provider, in display order
      (``CREDENTIAL_PROVIDERS``),
    - ``custom_presets``: OpenAI-compatible gateway presets offered inside the
      custom lane's card (``opencode`` / ``nous``),
    - ``llm_provider_keys``: which providers can serve chat (the wizard's
      readiness rule mirrors ``_needs_setup``).

    Adding or renaming a provider becomes a Python-only change; the UI picks
    it up here. Public under local auth like ``/status`` — the wizard renders
    cards before an admin session exists.
    """
    log.set(operation="setup_catalog", auth_mode=settings.AUTH_MODE)
    return {
        "providers": {name: PRESETS[name] for name in CREDENTIAL_PROVIDERS},
        "custom_presets": {name: PRESETS[name] for name in ("opencode", "nous")},
        "llm_provider_keys": list(_LLM_PROVIDER_KEYS),
    }


async def stored_credential_exists(provider: str) -> bool:
    """Module-level seam (tests rebind it): is a credential stored for this?"""
    return await provider_credentials_repository.exists(provider)


async def _is_usably_configured(provider: str) -> bool:
    """Whether ``provider`` can actually serve a request.

    A stored credential always counts. Env fallbacks count only when the env
    var was EXPLICITLY set — Ollama's ``OLLAMA_BASE_URL`` has a code default,
    and counting that default as 'configured' made brand-new instances report
    needs_setup=false and bounce off the wizard with no working LLM.
    """
    if await stored_credential_exists(provider):
        return True
    # Env-fallback semantics live in ONE place (the credential service) so
    # this endpoint can never disagree with what the LLM/search layers
    # actually resolve (e.g. Ollama's code-default URL is not "configured").
    return _env_fallback(provider) is not None


def _needs_setup(has_admin_account: bool, configured: dict[str, bool]) -> bool:
    """Setup is owed while no LLM lane works, or (local auth) no admin exists."""
    llm_ready = any(configured[p] for p in _LLM_PROVIDER_KEYS)
    if not llm_ready:
        return True
    return settings.AUTH_MODE == "local" and not has_admin_account


@router.get("/providers")
async def list_providers(
    user: Annotated[AuthenticatedUser, Depends(require_instance_admin)],
) -> dict[str, dict[str, Any]]:
    """Masked per-provider view for the settings UI. Never returns raw keys.

    Admin-only: the listing reveals configured base_urls and models.
    """
    log.set(user={"id": user["user_id"]})
    masked: dict[str, dict[str, Any]] = {}
    for provider in CREDENTIAL_PROVIDERS:
        config = await resolve_provider_config(provider)
        api_key = config.get("api_key") if config else None
        masked[provider] = {
            "provider": provider,
            "configured": config is not None,
            "base_url": config.get("base_url") if config else None,
            "model": config.get("model") if config else None,
            "api_key_hint": f"...{api_key[-4:]}" if api_key else None,
        }
    return {"providers": masked}


@router.put("/providers/{provider}")
@limiter.limit("20/minute")
async def put_provider(
    request: Request,  # noqa: ARG001 -- slowapi's @limiter.limit requires request in the handler signature
    provider: str,
    body: ProviderCredentialBody,
    user: Annotated[AuthenticatedUser, Depends(require_instance_admin)],
) -> dict[str, bool]:
    """Store (or replace) one provider's credential. Presets prefill server-side.

    Admin-only: rewriting a provider's endpoint redirects every LLM call the
    instance makes. Stored base_urls must be public (see ``_assert_url_safe``)
    except for ``ollama`` which is expected to be local
    (``host.docker.internal`` / ``localhost``) and skips the public-IP check.
    """
    log.set(user={"id": user["user_id"]})
    _ensure_known_provider(provider)
    if (
        body.preset is None
        and body.api_key is None
        and body.base_url is None
        and body.model is None
    ):
        raise HTTPException(status_code=422, detail="No fields to update")
    stored = await resolve_provider_config(provider)
    # Merge omitted fields with stored config — a partial PUT (e.g. base_url
    # only) must not erase the existing api_key. None means "not provided",
    # not "clear".
    api_key = (
        body.api_key if body.api_key is not None else (stored.get("api_key") if stored else None)
    )
    base_url_raw, model_raw = _apply_preset(body.preset, body.base_url, body.model)
    if base_url_raw is None and stored is not None:
        base_url_raw = stored.get("base_url")
    if model_raw is None and stored is not None:
        model_raw = stored.get("model")
    preset = body.preset if body.preset is not None else (stored.get("preset") if stored else None)
    base_url = base_url_raw
    model = model_raw
    if provider in _BASE_URL_PROVIDERS:
        # Only these providers' endpoints drive outbound traffic; openrouter and
        # gemini dial canonical URLs and ignore whatever is stored.
        await _assert_url_safe(base_url, allow_private=provider == "ollama")
    await upsert_provider_config(
        provider,
        api_key=api_key,
        base_url=base_url,
        model=model,
        preset=preset,
    )
    await invalidate_provider_cache(provider)
    return {"ok": True}


@router.delete("/providers/{provider}")
@limiter.limit("20/minute")
async def remove_provider(
    request: Request,  # noqa: ARG001 -- slowapi's @limiter.limit requires request in the handler signature
    provider: str,
    user: Annotated[AuthenticatedUser, Depends(require_instance_admin)],
) -> dict[str, bool]:
    """Drop one provider's stored credential."""
    log.set(user={"id": user["user_id"]})
    _ensure_known_provider(provider)
    await delete_provider_config(provider)
    await invalidate_provider_cache(provider)
    return {"ok": True}


@router.post("/providers/{provider}/test")
@limiter.limit("5/minute")
async def test_provider(
    request: Request,  # noqa: ARG001 -- slowapi's @limiter.limit requires request in the handler signature
    provider: str,
    body: ProviderCredentialBody,
    user: Annotated[AuthenticatedUser, Depends(require_instance_admin)],
) -> dict[str, Any]:
    """Live-connectivity probe with strict credential binding.

    Contract (H1): once a credential is stored for ``provider`` — including an
    environment-fallback config — the probe uses the STORED ``base_url`` and
    api_key exclusively; body values are ignored, so a caller-supplied URL can
    never be paired with a server-held key. Body values (preset / base_url /
    api_key / model) are honored only for first-time validation before
    anything has been saved. Non-public endpoints are refused outright with a
    422 by the SSRF guard inside ``_probe``.
    """
    log.set(user={"id": user["user_id"]})
    if provider == "tavily":
        raise HTTPException(status_code=422, detail="Tavily keys cannot be connection-tested")
    _ensure_known_provider(provider)

    stored = await resolve_provider_config(provider)
    if stored is not None:
        config = stored
    else:
        base_url, model = _apply_preset(body.preset, body.base_url, body.model)
        config = ProviderConfig(
            api_key=body.api_key,
            base_url=base_url,
            model=model,
            preset=body.preset,
        )
    ok, detail, models = await _probe(provider, config)
    log.info("Provider connectivity tested", provider=provider, ok=ok)
    return {"ok": ok, "detail": detail, "models": models}


async def _assert_url_safe(base_url: str | None, *, allow_private: bool = False) -> None:
    """Refuse ``base_url`` values this router must not send requests to (SSRF).

    Applied wherever an outbound provider URL enters the system: at save time
    (only public endpoints get stored) and again in ``_probe`` right before
    anything is dialed — which also covers credentials saved before save-time
    validation existed, and env-fallback configs. The string checks below are
    the cheap fast-fails; the actual allow/deny policy delegates to
    ``app.utils.url_safety`` (``assert_safe_url_shape`` then
    ``assert_public_http_url``), the repo's single SSRF source of truth: it
    rejects literal private-IP hosts without a lookup, resolves DNS off the
    event loop, and validates EVERY resolved address, so decimal IP shorthands
    (``http://2130706433/``, ``http://127.1/``) that no string check sees as
    private, and public-looking names answering with private addresses
    (``127.0.0.1.nip.io``), are all rejected. Unresolvable hosts fail closed.

    ``allow_private``: when True (the ``ollama`` provider) the URL may point at
    a private/link-local address such as ``host.docker.internal`` or
    ``localhost`` — only the scheme/host/credential/metadata checks are
    enforced, and the public-IP DNS validation is skipped. Every other
    provider (``custom``) still requires a public endpoint — expose it behind a
    public URL or set ``OLLAMA_BASE_URL`` server-side for trusted env config
    that never passes through this guard.
    """
    if not base_url:
        return
    parsed = urlparse(base_url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise HTTPException(status_code=422, detail="base_url must be an http(s) URL")
    if parsed.username or parsed.password or (parsed.port and parsed.port in (0, 1)):
        raise HTTPException(status_code=422, detail="base_url must not embed credentials")
    if parsed.hostname in ("169.254.169.254", "metadata.google.internal"):
        raise HTTPException(
            status_code=422,
            detail=f"{_PRIVATE_URL_HINT} (refusing metadata address {parsed.hostname})",
        )

    if allow_private:
        # Local Ollama is expected to run on the host or loopback; skip the
        # public-IP DNS check that would reject host.docker.internal /
        # localhost / 192.168.x.x. The scheme/host/credential checks above are
        # still enforced, so malformed or metadata URLs are still rejected.
        return

    try:
        # Literal private IPs are rejected here without a DNS round-trip;
        # hostnames are resolved and every answer validated off the event loop.
        assert_safe_url_shape(base_url)
        await assert_public_http_url(base_url)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=f"{_PRIVATE_URL_HINT} ({e})") from e


async def _probe(provider: str, config: ProviderConfig) -> tuple[bool, str, list[str]]:
    """Probe one provider endpoint and return (ok, human detail, sorted models).

    Never includes credentials in ``detail`` — only URLs without query strings.
    Refuses with a 422 rather than a soft failure when the configured endpoint
    of a base-url-driven provider is not public (SSRF guard; also catches
    stored configs from before save-time validation existed). The ``ollama``
    provider is exempt from the public-IP check (see ``_assert_url_safe``).
    """
    if provider in _BASE_URL_PROVIDERS:
        await _assert_url_safe(config["base_url"], allow_private=provider == "ollama")
    try:
        async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT_SECONDS) as client:
            if provider == "gemini":
                return await _probe_gemini(client, config["api_key"])
            if provider == "ollama":
                return await _probe_ollama(client, config["base_url"])
            return await _probe_openai_wire(provider, client, config)
    except httpx.HTTPError as e:
        return False, f"Could not reach {provider}: {type(e).__name__}", []


async def _probe_openai_wire(
    provider: str,
    client: httpx.AsyncClient,
    config: ProviderConfig,
) -> tuple[bool, str, list[str]]:
    # OpenRouter needs no configurable endpoint — its models URL is canonical;
    # every other OpenAI-wire provider probes its configured base URL.
    if provider == "openrouter":
        if not config["api_key"]:
            return False, "No OpenRouter API key configured", []
        url = OPENROUTER_MODELS_URL
    else:
        base_url = config["base_url"]
        if not base_url:
            return False, f"No base URL configured for {provider}", []
        url = f"{base_url.rstrip('/')}/models"
    headers = {"Authorization": f"Bearer {config['api_key']}"} if config["api_key"] else {}
    response = await client.get(url, headers=headers)
    if response.status_code != 200:
        return False, f"{provider} returned HTTP {response.status_code}", []
    models = sorted(str(m["id"]) for m in response.json().get("data", []) if m.get("id"))
    return True, f"Connected to {provider}", models


async def _probe_gemini(
    client: httpx.AsyncClient,
    api_key: str | None,
) -> tuple[bool, str, list[str]]:
    if not api_key:
        return False, "No Gemini API key configured", []
    response = await client.get(_GEMINI_MODELS_URL, params={"key": api_key})
    if response.status_code != 200:
        return False, f"Gemini returned HTTP {response.status_code}", []
    names = (
        str(m["name"]).removeprefix("models/")
        for m in response.json().get("models", [])
        if m.get("name")
    )
    return True, "Connected to Google Gemini", sorted(names)


async def _probe_ollama(
    client: httpx.AsyncClient,
    base_url: str | None,
) -> tuple[bool, str, list[str]]:
    if not base_url:
        return False, "No Ollama base URL configured", []
    response = await client.get(f"{base_url.rstrip('/')}/api/tags")
    if response.status_code != 200:
        return False, f"Ollama returned HTTP {response.status_code}", []
    models = sorted(str(m["name"]) for m in response.json().get("models", []) if m.get("name"))
    return True, "Connected to Ollama", models


@router.post("/complete")
@limiter.limit("20/minute")
async def complete_setup_step(
    request: Request,  # noqa: ARG001 -- slowapi's @limiter.limit requires request in the handler signature
    body: SetupCompleteBody,
    user: Annotated[AuthenticatedUser, Depends(require_instance_admin)],
) -> dict[str, bool]:
    """Mark one wizard step done in the instance-settings ``setup`` doc.

    Mutates shared instance state — admin-only like the rest of the surface.
    """
    log.set(user={"id": user["user_id"]})
    record = await instance_settings_repository.find_by_key(SETUP_DOC_KEY)
    value: dict[str, Any] = dict(record.value) if record is not None else {}
    steps: dict[str, bool] = {**value.get("steps", {}), body.step: True}
    await instance_settings_repository.upsert_value(SETUP_DOC_KEY, {**value, "steps": steps})
    return {"ok": True}


def _ensure_known_provider(provider: str) -> None:
    if provider not in CREDENTIAL_PROVIDERS:
        raise HTTPException(status_code=404, detail=f"Unknown provider: {provider}")


def _apply_preset(
    preset: Literal["opencode", "nous"] | None,
    base_url: str | None,
    model: str | None,
) -> tuple[str | None, str | None]:
    """Explicit values win; a preset fills whatever the caller omitted."""
    if preset is None:
        return base_url, model
    spec = PRESETS[preset]
    return base_url or (spec["base_url"] or None), model or (spec["default_model"] or None)
