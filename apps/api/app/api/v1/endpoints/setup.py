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

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.api.v1.dependencies.instance_admin import require_instance_admin
from app.api.v1.middleware.rate_limiter import limiter
from app.config.deployment import BlobStoreKind, DeploymentKind
from app.config.settings import settings
from app.constants.auth import RegistrationPolicy
from app.constants.providers import (
    CUSTOM_PRESETS,
    LLM_PROVIDER_PRIORITY,
    PROVIDER_FEATURES,
    CredentialProviderName,
    CredentialSource,
    FeatureSpec,
    PresetName,
    ProviderFeature,
    ProviderPreset,
)
from app.db.repositories.local_credentials import local_credentials_repository
from app.models.user_models import AuthenticatedUser
from app.schemas.providers import ProviderCredentialBody
from app.services.members_service import get_registration_policy
from app.services.providers.feature_status import FeatureStatus, feature_statuses
from app.services.providers.provider_credentials_service import (
    ProviderConfig,
    delete as delete_provider_config,
    inspect_credential,
    invalidate as invalidate_provider_cache,
    is_usable,
    resolve as resolve_provider_config,
)
from app.services.providers.provider_probe_service import probe_provider
from app.services.providers.provider_registry import PROVIDER_SPECS
from app.services.providers.provider_setup_service import (
    apply_preset,
    save_provider_credential,
)
from app.services.setup_wizard_service import dismiss_setup_wizard, is_setup_wizard_dismissed
from app.services.startup_validation import is_payment_setup
from shared.py.wide_events import log

router = APIRouter(tags=["Setup"])


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
    providers: dict[CredentialProviderName, ProviderConfiguredState] = Field(
        description="Readiness per credential-store provider"
    )
    features: dict[ProviderFeature, FeatureStatus] = Field(
        description="Whether each feature works and what it runs on"
    )
    plans_seeded: bool = Field(description="Whether the billing plans have been seeded")
    bots: InstanceBots = Field(description="The chat bots this instance runs")


class ProviderCatalogResponse(BaseModel):
    """``GET /setup/catalog`` — display metadata, partitioned by role.

    Each map holds catalog presets verbatim, so the wizard never ships its own
    copy of the catalog.
    """

    providers: dict[CredentialProviderName, ProviderPreset] = Field(
        description="One entry per credential-store provider, in display order"
    )
    custom_presets: dict[PresetName, ProviderPreset] = Field(
        description="OpenAI-compatible gateway presets for the custom lane's card"
    )
    llm_provider_keys: list[CredentialProviderName] = Field(
        description="Which providers can serve chat"
    )
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
    account_id: str | None = Field(
        None, description="The non-secret account half, e.g. Cloudinary's cloud name"
    )
    api_secret_hint: str | None = Field(
        None, description="Last four characters of the second secret, e.g. Cloudinary's API secret"
    )


class ProviderListResponse(BaseModel):
    providers: dict[CredentialProviderName, MaskedProvider] = Field(
        description="Masked view per provider"
    )


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


@router.get("/status")
async def get_setup_status() -> SetupStatusResponse:
    """First-run status for the web setup wizard and desktop CLI.

    Public only under AUTH_MODE=local (middleware conditionally excludes it
    there); in workos mode the route requires a session like any other.
    """
    log.set(operation="setup_status", auth_mode=settings.AUTH_MODE)
    has_admin_account = await local_credentials_repository.admin_exists()
    resolutions = {p: await inspect_credential(p) for p in CredentialProviderName}
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

    Serves each provider spec's preset — display metadata only (no secrets, no
    configuration state) — partitioned by role so clients can render every
    card without shipping their own copy of the catalog:

    - ``providers``: one entry per credential-store provider, in display order
      (``CredentialProviderName``),
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
        providers={name: PROVIDER_SPECS[name].preset for name in CredentialProviderName},
        custom_presets=CUSTOM_PRESETS,
        llm_provider_keys=[CredentialProviderName(p) for p in LLM_PROVIDER_PRIORITY],
        features=PROVIDER_FEATURES,
    )


def _needs_setup(has_admin_account: bool, configured: dict[CredentialProviderName, bool]) -> bool:
    """Setup is owed while no LLM lane works, or (local auth) no admin exists."""
    llm_ready = any(configured[CredentialProviderName(p)] for p in LLM_PROVIDER_PRIORITY)
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
    masked: dict[CredentialProviderName, MaskedProvider] = {}
    for provider in CredentialProviderName:
        config: ProviderConfig | None = await resolve_provider_config(provider)
        masked[provider] = MaskedProvider(
            provider=provider,
            configured=is_usable(provider, config),
            base_url=config.base_url if config else None,
            model=config.model if config else None,
            api_key_hint=_hint(config.api_key if config else None),
            account_id=config.account_id if config else None,
            api_secret_hint=_hint(config.api_secret if config else None),
        )
    return ProviderListResponse(providers=masked)


@router.put("/providers/{provider}")
@limiter.limit("20/minute")
async def put_provider(
    request: Request,  # noqa: ARG001 -- slowapi's @limiter.limit requires request in the handler signature
    provider: CredentialProviderName,
    body: ProviderCredentialBody,
    user: Annotated[AuthenticatedUser, Depends(require_instance_admin)],
) -> dict[str, bool]:
    """Store (or replace) one provider's credential. Presets prefill server-side.

    Admin-only: rewriting a provider's endpoint redirects every LLM call the
    instance makes. Validation and the merge live in save_provider_credential.
    """
    log.set(user={"id": user.user_id})
    await save_provider_credential(provider, body)
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
    provider: CredentialProviderName,
    user: Annotated[AuthenticatedUser, Depends(require_instance_admin)],
) -> dict[str, bool]:
    """Drop one provider's stored credential."""
    log.set(user={"id": user.user_id})
    await delete_provider_config(provider)
    await invalidate_provider_cache(provider)
    log.audit("provider credential removed", actor=user.user_id, provider=provider)
    return {"ok": True}


@router.post("/providers/{provider}/test")
@limiter.limit("5/minute")
async def test_provider(
    request: Request,  # noqa: ARG001 -- slowapi's @limiter.limit requires request in the handler signature
    provider: CredentialProviderName,
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
    422 by the SSRF guard inside ``probe_provider``.
    """
    log.set(user={"id": user.user_id})
    if not PROVIDER_SPECS[provider].preset.takes_model:
        raise HTTPException(
            status_code=422, detail=f"Only chat providers can be connection-tested, not {provider}"
        )

    stored: ProviderConfig | None = await resolve_provider_config(provider)
    if stored is not None:
        api_key, base_url, model = stored.api_key, stored.base_url, stored.model
    else:
        api_key = body.api_key
        base_url, model = apply_preset(body.preset, body.base_url, body.model)
    ok, detail, models = await probe_provider(
        provider, api_key=api_key, base_url=base_url, model=model
    )
    log.info("Provider connectivity tested", provider=provider, ok=ok)
    return ProviderTestResponse(ok=ok, detail=detail, models=models)


def _hint(secret: str | None) -> str | None:
    return f"...{secret[-4:]}" if secret else None
