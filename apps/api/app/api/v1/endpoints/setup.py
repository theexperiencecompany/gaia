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
public, except that ``ollama`` (always) and any custom endpoint outside
production may be private (localhost, ``host.docker.internal``, a LAN host) —
metadata and link-local addresses stay refused. ``OLLAMA_BASE_URL``
server-side env still works as a fallback for deployments that prefer it.
"""

import ipaddress
import re
from typing import Annotated, Literal, TypedDict, cast
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request
import httpx
from pydantic import BaseModel, Field

from app.api.v1.dependencies.instance_admin import require_instance_admin
from app.api.v1.middleware.rate_limiter import limiter
from app.config.deployment import BlobStoreKind, DeploymentKind
from app.config.settings import settings
from app.constants.auth import RegistrationPolicy
from app.constants.llm import OPENAI_API_URL, OPENROUTER_API_URL, LLMProviderName
from app.constants.providers import (
    CREDENTIAL_PROVIDERS,
    LLM_MODEL_PROFILES,
    LLM_PROVIDER_PRIORITY,
    PRESETS,
    PROVIDER_FEATURES,
    CredentialProviderName,
    CredentialSource,
    FeatureSpec,
    ProviderFeature,
    ProviderPreset,
)
from app.db.repositories.local_credentials import local_credentials_repository
from app.models.user_models import AuthenticatedUser
from app.services.members_service import get_registration_policy
from app.services.providers.feature_status import FeatureStatus, feature_statuses
from app.services.providers.provider_credentials_service import (
    ProviderConfig,
    delete as delete_provider_config,
    inspect_credential,
    invalidate as invalidate_provider_cache,
    is_usable,
    resolve as resolve_provider_config,
    upsert as upsert_provider_config,
)
from app.services.setup_wizard_service import dismiss_setup_wizard, is_setup_wizard_dismissed
from app.services.startup_validation import is_payment_setup
from app.utils.url_safety import assert_public_http_url, assert_safe_url_shape
from shared.py.wide_events import log

router = APIRouter(tags=["Setup"])

# Providers that constitute a working LLM lane for needs_setup. The search,
# tool, and integration keys configured here too cannot serve chat.
_LLM_PROVIDER_KEYS: tuple[str, ...] = tuple(p.value for p in LLM_PROVIDER_PRIORITY)

# Providers whose outbound traffic targets a caller-configurable base_url — the
# only stored base_urls the SSRF guard applies to (openrouter/gemini dial
# canonical endpoints; the tool keys carry no endpoint).
_BASE_URL_PROVIDERS = frozenset({"custom", "ollama", "searxng"})

_PRESET_NAMES = Literal["opencode", "nous"]

_GEMINI_MODELS_URL = "https://generativelanguage.googleapis.com/v1beta/models"
_CANONICAL_API_URLS: dict[str, str] = {
    "openrouter": OPENROUTER_API_URL,
    "openai": OPENAI_API_URL,
}
_PROBE_TIMEOUT_SECONDS = 10.0
# OpenAI refuses a cap of 1 (400 "max_tokens ... reached"); reasoning models answer 200 at 16.
_PROBE_MAX_COMPLETION_TOKENS = 16
_PROBE_PROMPT = "Reply with OK."
_AUTH_REJECTED_STATUSES = frozenset({401, 403})
# OpenAI echoes a rejected key back in its error message.
_API_KEY_RE = re.compile(r"\bsk-[\w*.-]+")

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


class ProviderConfiguredState(BaseModel):
    """Per-provider readiness as the wizard reads it: "can this serve a request?"."""

    configured: bool = Field(description="Whether a usable credential or env fallback exists")
    source: CredentialSource = Field(
        description="Where the active credential comes from; a saved one overrides env"
    )
    env_shadowed: bool = Field(
        description="Whether the environment sets a different credential the saved one overrides"
    )


class DeploymentStatus(BaseModel):
    """The deployment profile's capabilities a client branches on."""

    kind: DeploymentKind = Field(description="Which kind of instance this is (ENV)")
    bills: bool = Field(description="Whether payments are live for this instance")
    local_code_sandbox: bool = Field(
        description="Whether code runs in the opt-in local Docker sandbox when no E2B key is saved"
    )
    blob_store: BlobStoreKind = Field(
        description="Where uploaded and generated files live (BLOB_STORE)"
    )
    gaia_support: bool = Field(
        description="Whether in-app support requests reach GAIA's support team"
    )
    instance_toolkits: bool = Field(
        description="Whether the admin may enable Composio toolkits beyond the built-in ones"
    )
    private_network_endpoints: bool = Field(
        description="Whether a configured endpoint such as an MCP server may be a private address"
    )


class InstanceBots(BaseModel):
    """The chat bots this instance runs, for the web Bots page; null where none is set up."""

    telegram_username: str | None = Field(description="The Telegram bot's @username")
    discord_client_id: str | None = Field(
        description="The Discord application id the bot's invite link names"
    )
    slack_workspace_url: str | None = Field(
        description="The Slack workspace the bot is installed in"
    )


class SetupStatusResponse(BaseModel):
    """``GET /setup/status`` — what the first-run wizard branches on."""

    auth_mode: Literal["workos", "local"] = Field(description="Active auth stack")
    has_admin_account: bool = Field(description="Whether the instance administrator exists")
    registration_policy: RegistrationPolicy = Field(
        description="Who may sign up once the administrator exists"
    )
    needs_setup: bool = Field(description="Whether an LLM lane still has to be configured")
    wizard_dismissed: bool = Field(
        description="Whether the administrator skipped the wizard, which then stops opening itself"
    )
    deployment: DeploymentStatus = Field(description="What this deployment does")
    providers: dict[str, ProviderConfiguredState] = Field(
        description="Readiness per credential-store provider"
    )
    features: dict[ProviderFeature, FeatureStatus] = Field(
        description="Whether each feature works and what it runs on"
    )
    plans_seeded: bool = Field(description="Whether the billing plans have been seeded")
    bots: InstanceBots = Field(description="The chat bots this instance runs")


class ProviderCatalogResponse(BaseModel):
    """``GET /setup/catalog`` — display metadata, partitioned by role.

    Each map holds ``app.constants.providers.PRESETS`` entries verbatim, so the
    wizard never ships its own copy of the catalog.
    """

    providers: dict[str, ProviderPreset] = Field(
        description="One entry per credential-store provider, in display order"
    )
    custom_presets: dict[str, ProviderPreset] = Field(
        description="OpenAI-compatible gateway presets for the custom lane's card"
    )
    llm_provider_keys: list[str] = Field(description="Which providers can serve chat")
    features: dict[ProviderFeature, FeatureSpec] = Field(
        description="What each feature does, what it runs on with no key, and its optional providers"
    )


class MaskedProvider(BaseModel):
    """One row of ``GET /setup/providers`` — a credential with the key masked."""

    provider: CredentialProviderName = Field(description="Provider name")
    configured: bool = Field(description="Whether a credential resolves for this provider")
    base_url: str | None = Field(None, description="Configured endpoint, if any")
    model: str | None = Field(None, description="Configured model, if any")
    api_key_hint: str | None = Field(
        None, description="Last four characters of the key; the key itself never leaves the server"
    )


class ProviderListResponse(BaseModel):
    providers: dict[str, MaskedProvider] = Field(description="Masked view per provider")


class SetupWizardResponse(BaseModel):
    """`POST /setup/wizard/dismiss` — the wizard state after the call."""

    wizard_dismissed: bool = Field(description="Whether the wizard stops opening itself")


class ProviderTestResponse(BaseModel):
    """``POST /setup/providers/{provider}/test`` — the live connectivity probe."""

    ok: bool = Field(description="Whether the provider answered the test request")
    detail: str = Field(description="Human-readable outcome; never contains credentials")
    models: list[str] = Field(
        description="Model ids the endpoint listed; empty for OpenAI-wire providers, "
        "which are probed with a chat completion"
    )


class _WireErrorDetail(TypedDict, total=False):
    """OpenAI-wire ``{"error": {"message": ...}}`` body."""

    message: str


class _WireError(TypedDict, total=False):
    """An OpenAI-wire error body; the error is an object, or a bare string on a scope failure."""

    error: _WireErrorDetail | str


class _GeminiModel(TypedDict, total=False):
    """One entry of a name-keyed model list — ``{"name": "models/gemini-..."}``."""

    name: str


class _NamedModelList(TypedDict, total=False):
    """The ``{"models": [{"name": ...}]}`` envelope Gemini's listModels and
    Ollama's /api/tags both return."""

    models: list[_GeminiModel]


@router.get("/status")
async def get_setup_status() -> SetupStatusResponse:
    """First-run status for the web setup wizard and desktop CLI.

    Public only under AUTH_MODE=local (middleware conditionally excludes it
    there); in workos mode the route requires a session like any other.
    """
    log.set(operation="setup_status", auth_mode=settings.AUTH_MODE)
    has_admin_account = await local_credentials_repository.admin_exists()
    resolutions = {p: await inspect_credential(p) for p in CREDENTIAL_PROVIDERS}
    configured = {p: is_usable(p, r.config) for p, r in resolutions.items()}
    return SetupStatusResponse(
        auth_mode=settings.AUTH_MODE,
        has_admin_account=has_admin_account,
        registration_policy=await get_registration_policy(),
        needs_setup=_needs_setup(has_admin_account, configured),
        wizard_dismissed=await is_setup_wizard_dismissed(),
        deployment=DeploymentStatus(
            kind=settings.deployment.kind,
            bills=settings.deployment.bills,
            local_code_sandbox=settings.deployment.local_code_sandbox,
            blob_store=settings.deployment.blob_store,
            gaia_support=settings.deployment.gaia_support,
            instance_toolkits=settings.deployment.instance_toolkits,
            private_network_endpoints=settings.deployment.private_network_endpoints,
        ),
        providers={
            p: ProviderConfiguredState(
                configured=configured[p], source=r.source, env_shadowed=r.shadows_env
            )
            for p, r in resolutions.items()
        },
        features=await feature_statuses(),
        plans_seeded=await is_payment_setup(),
        bots=InstanceBots(
            telegram_username=settings.telegram_bot_username,
            discord_client_id=settings.DISCORD_CLIENT_ID,
            slack_workspace_url=settings.SLACK_WORKSPACE_URL,
        ),
    )


@router.get("/catalog")
async def get_provider_catalog() -> ProviderCatalogResponse:
    """The provider catalog the setup wizard and Settings render from.

    Serves ``app.constants.providers.PRESETS`` — display metadata only (no
    secrets, no configuration state) — partitioned by role so clients can
    render every card without shipping their own copy of the catalog:

    - ``providers``: one entry per credential-store provider, in display order
      (``CREDENTIAL_PROVIDERS``),
    - ``custom_presets``: OpenAI-compatible gateway presets offered inside the
      custom lane's card (``opencode`` / ``nous``),
    - ``llm_provider_keys``: which providers can serve chat (the wizard's
      readiness rule mirrors ``_needs_setup``),
    - ``features``: the providers grouped by what they are for, with what each
      feature runs on when no key is set.

    Adding or renaming a provider becomes a Python-only change; the UI picks
    it up here. Public under local auth like ``/status`` — the wizard renders
    cards before an admin session exists.
    """
    log.set(operation="setup_catalog", auth_mode=settings.AUTH_MODE)
    return ProviderCatalogResponse(
        providers={name: PRESETS[name] for name in CREDENTIAL_PROVIDERS},
        custom_presets={name: PRESETS[name] for name in ("opencode", "nous")},
        llm_provider_keys=list(_LLM_PROVIDER_KEYS),
        features=PROVIDER_FEATURES,
    )


def _needs_setup(has_admin_account: bool, configured: dict[str, bool]) -> bool:
    """Setup is owed while no LLM lane works, or (local auth) no admin exists."""
    llm_ready = any(configured[p] for p in _LLM_PROVIDER_KEYS)
    if not llm_ready:
        return True
    return settings.deployment.local_auth and not has_admin_account


@router.post("/wizard/dismiss")
async def dismiss_wizard(
    user: Annotated[AuthenticatedUser, Depends(require_instance_admin)],
) -> SetupWizardResponse:
    """Stop the setup wizard opening itself; the chat setup banner nudges instead."""
    log.set(user={"id": user.user_id}, operation="setup_wizard_dismiss")
    await dismiss_setup_wizard()
    return SetupWizardResponse(wizard_dismissed=True)


@router.get("/providers")
async def list_providers(
    user: Annotated[AuthenticatedUser, Depends(require_instance_admin)],
) -> ProviderListResponse:
    """Masked per-provider view for the settings UI. Never returns raw keys.

    Admin-only: the listing reveals configured base_urls and models.
    """
    log.set(user={"id": user.user_id})
    masked: dict[str, MaskedProvider] = {}
    for provider in CREDENTIAL_PROVIDERS:
        config: ProviderConfig | None = await resolve_provider_config(provider)
        api_key = config.get("api_key") if config else None
        masked[provider] = MaskedProvider(
            provider=CredentialProviderName(provider),
            configured=is_usable(provider, config),
            base_url=config.get("base_url") if config else None,
            model=config.get("model") if config else None,
            api_key_hint=f"...{api_key[-4:]}" if api_key else None,
        )
    return ProviderListResponse(providers=masked)


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
    log.set(user={"id": user.user_id})
    _ensure_known_provider(provider)
    if (
        body.preset is None
        and body.api_key is None
        and body.base_url is None
        and body.model is None
    ):
        raise HTTPException(status_code=422, detail="No fields to update")
    stored: ProviderConfig | None = await resolve_provider_config(provider)
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
        await _assert_url_safe(base_url, allow_private=_allows_private_endpoint(provider))
    await upsert_provider_config(
        provider,
        api_key=api_key,
        base_url=base_url,
        model=model,
        preset=preset,
    )
    await invalidate_provider_cache(provider)
    log.audit(
        "provider credential saved",
        actor=user.user_id,
        provider=provider,
        api_key_changed=body.api_key is not None,
    )
    return {"ok": True}


@router.delete("/providers/{provider}")
@limiter.limit("20/minute")
async def remove_provider(
    request: Request,  # noqa: ARG001 -- slowapi's @limiter.limit requires request in the handler signature
    provider: str,
    user: Annotated[AuthenticatedUser, Depends(require_instance_admin)],
) -> dict[str, bool]:
    """Drop one provider's stored credential."""
    log.set(user={"id": user.user_id})
    _ensure_known_provider(provider)
    await delete_provider_config(provider)
    await invalidate_provider_cache(provider)
    log.audit("provider credential removed", actor=user.user_id, provider=provider)
    return {"ok": True}


@router.post("/providers/{provider}/test")
@limiter.limit("5/minute")
async def test_provider(
    request: Request,  # noqa: ARG001 -- slowapi's @limiter.limit requires request in the handler signature
    provider: str,
    body: ProviderCredentialBody,
    user: Annotated[AuthenticatedUser, Depends(require_instance_admin)],
) -> ProviderTestResponse:
    """Live-connectivity probe with strict credential binding.

    Contract (H1): once a credential is stored for ``provider`` — including an
    environment-fallback config — the probe uses the STORED ``base_url`` and
    api_key exclusively; body values are ignored, so a caller-supplied URL can
    never be paired with a server-held key. Body values (preset / base_url /
    api_key / model) are honored only for first-time validation before
    anything has been saved. Non-public endpoints are refused outright with a
    422 by the SSRF guard inside ``_probe``.
    """
    log.set(user={"id": user.user_id})
    _ensure_known_provider(provider)
    if provider not in _LLM_PROVIDER_KEYS:
        raise HTTPException(
            status_code=422, detail=f"Only chat providers can be connection-tested, not {provider}"
        )

    stored: ProviderConfig | None = await resolve_provider_config(provider)
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
    return ProviderTestResponse(ok=ok, detail=detail, models=models)


def _allows_private_endpoint(provider: str) -> bool:
    """Whether a provider's base_url may be a private address.

    Ollama always may; where the deployment allows private-network endpoints any
    admin-configured one may too, so a LAN vLLM or LM Studio server works.
    """
    return provider == "ollama" or settings.deployment.private_network_endpoints


def _is_link_local(hostname: str) -> bool:
    """Whether hostname is a literal link-local IP (169.254/16, fe80::/10), the cloud-metadata range."""
    try:
        return ipaddress.ip_address(hostname).is_link_local
    except ValueError:
        return False


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

    ``allow_private`` (see ``_allows_private_endpoint``): the URL may point at
    a private address such as ``host.docker.internal``, ``localhost`` or a LAN
    host — only the scheme/host/credential/metadata/link-local checks are
    enforced, and the public-IP DNS validation is skipped.
    """
    if not base_url:
        return
    parsed = urlparse(base_url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise HTTPException(status_code=422, detail="base_url must be an http(s) URL")
    if parsed.username or parsed.password or (parsed.port and parsed.port in (0, 1)):
        raise HTTPException(status_code=422, detail="base_url must not embed credentials")
    if parsed.hostname in ("169.254.169.254", "metadata.google.internal") or _is_link_local(
        parsed.hostname
    ):
        raise HTTPException(
            status_code=422,
            detail=f"{_PRIVATE_URL_HINT} (refusing metadata address {parsed.hostname})",
        )

    if allow_private:
        # Scheme, host, credential and metadata checks above still apply.
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
        await _assert_url_safe(config["base_url"], allow_private=_allows_private_endpoint(provider))
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
    """Run the one call GAIA makes on this lane: a tiny chat completion on its model.

    Listing models is not it: a restricted OpenAI key lacks api.model.read yet chats fine.
    """
    preset: ProviderPreset = PRESETS[provider]
    label = preset["label"]
    # OpenRouter and OpenAI need no configurable endpoint — their API roots are
    # canonical; every other OpenAI-wire provider probes its configured base URL.
    if canonical_url := _CANONICAL_API_URLS.get(provider):
        if not config["api_key"]:
            return False, f"No {label} API key configured", []
        api_url = canonical_url
    else:
        if not config["base_url"]:
            return False, f"No base URL configured for {label}", []
        api_url = config["base_url"].rstrip("/")
    model = config["model"] or LLM_MODEL_PROFILES[LLMProviderName(provider)].chat
    if not model:
        return False, f"No model configured for {label}", []
    headers = {"Authorization": f"Bearer {config['api_key']}"} if config["api_key"] else {}
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
        return True, f"Connected to {label}", []
    reason = _wire_error_reason(response, config["api_key"])
    if response.status_code in _AUTH_REJECTED_STATUSES:
        return False, f"{label} rejected the key: {reason}", []
    return False, f"{label} refused the test request: {reason}", []


def _wire_error_reason(response: httpx.Response, api_key: str | None) -> str:
    """The provider's own error message with any key redacted, else the HTTP status."""
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
) -> tuple[bool, str, list[str]]:
    if not api_key:
        return False, "No Gemini API key configured", []
    response = await client.get(_GEMINI_MODELS_URL, params={"key": api_key})
    if response.status_code != 200:
        return False, f"Gemini returned HTTP {response.status_code}", []
    payload: _NamedModelList = cast(_NamedModelList, response.json())
    listed: list[_GeminiModel] = payload.get("models", [])
    names = (str(m["name"]).removeprefix("models/") for m in listed if m.get("name"))
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
    payload: _NamedModelList = cast(_NamedModelList, response.json())
    listed: list[_GeminiModel] = payload.get("models", [])
    models = sorted(str(m["name"]) for m in listed if m.get("name"))
    return True, "Connected to Ollama", models


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
    spec: ProviderPreset = PRESETS[preset]
    return base_url or (spec["base_url"] or None), model or (spec["default_model"] or None)
