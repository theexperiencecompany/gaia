"""Instance setup API — first-run status and provider configuration (self-host).

Owns the ``/setup`` surface from ``.agents/plans/selfhost-contracts.md`` (A4):
a PUBLIC status probe for the web setup wizard and instance-admin-gated
management of provider credentials — masked listing, upsert, delete, live
connectivity test, and setup-step completion tracking in instance settings.
Every route except ``GET /status`` requires the instance administrator (see
``require_instance_admin``). Credentials themselves live behind
``provider_credentials_service``; this module never stores or logs raw keys.
"""

import os
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException
import httpx
from pydantic import BaseModel, Field

from app.api.v1.dependencies.instance_admin import require_instance_admin
from app.config.settings import settings
from app.constants.llm import OPENROUTER_MODELS_URL
from app.constants.providers import CREDENTIAL_PROVIDERS, PRESETS
from app.db.repositories.instance_settings import instance_settings_repository
from app.db.repositories.local_credentials import local_credentials_repository
from app.db.repositories.provider_credentials import provider_credentials_repository
from app.models.user_models import AuthenticatedUser
from app.services.providers.provider_credentials_service import (
    ProviderConfig,
    delete as delete_provider_config,
    invalidate as invalidate_provider_cache,
    resolve as resolve_provider_config,
    upsert as upsert_provider_config,
)
from app.services.startup_validation import are_models_seeded, is_payment_setup
from shared.py.wide_events import log

router = APIRouter(tags=["Setup"])

# Doc key under which wizard progress is persisted in instance settings.
SETUP_DOC_KEY = "setup"

# Providers that constitute a working LLM lane for ``needs_setup`` — every
# credential provider except Tavily (a tool key, not an LLM).
_LLM_PROVIDER_KEYS = ("openrouter", "gemini", "ollama", "custom")

_PRESET_NAMES = Literal["opencode", "nous"]

_GEMINI_MODELS_URL = "https://generativelanguage.googleapis.com/v1beta/models"
_PROBE_TIMEOUT_SECONDS = 10.0


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
    """PUBLIC first-run status for the web setup wizard and desktop CLI."""
    has_admin_account = await local_credentials_repository.any_exists()
    configured = {p: await _is_usably_configured(p) for p in CREDENTIAL_PROVIDERS}
    return {
        "auth_mode": settings.AUTH_MODE,
        "has_admin_account": has_admin_account,
        "needs_setup": _needs_setup(has_admin_account, configured),
        "billing_enabled": settings.ENV != "selfhost",
        "providers": {p: {"configured": c} for p, c in configured.items()},
        "models_seeded": await are_models_seeded(),
        "plans_seeded": await is_payment_setup(),
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
    match provider:
        case "ollama":
            return bool(os.getenv("OLLAMA_BASE_URL"))
        case "openrouter":
            return bool(settings.OPENROUTER_API_KEY)
        case "gemini":
            return bool(settings.GOOGLE_API_KEY)
        case "tavily":
            return bool(settings.TAVILY_API_KEY)
        case "custom":
            return bool(settings.ENV == "development" and settings.DEV_LLM_API_KEY)
    return False


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
async def put_provider(
    provider: str,
    body: ProviderCredentialBody,
    user: Annotated[AuthenticatedUser, Depends(require_instance_admin)],
) -> dict[str, bool]:
    """Store (or replace) one provider's credential. Presets prefill server-side.

    Admin-only: rewriting a provider's endpoint redirects every LLM call the
    instance makes.
    """
    log.set(user={"id": user["user_id"]})
    _ensure_known_provider(provider)
    base_url, model = _apply_preset(body.preset, body.base_url, body.model)
    await upsert_provider_config(
        provider,
        api_key=body.api_key,
        base_url=base_url,
        model=model,
        preset=body.preset,
    )
    await invalidate_provider_cache(provider)
    return {"ok": True}


@router.delete("/providers/{provider}")
async def remove_provider(
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
async def test_provider(
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
    anything has been saved.
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


async def _probe(provider: str, config: ProviderConfig) -> tuple[bool, str, list[str]]:
    """Probe one provider endpoint and return (ok, human detail, sorted models).

    Never includes credentials in ``detail`` — only URLs without query strings.
    """
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
async def complete_setup_step(
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
