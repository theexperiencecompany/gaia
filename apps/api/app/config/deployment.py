"""The one place a deployment's capabilities are decided.

Every behaviour that differs between hosted production, development and a
self-hosted instance reads a capability off settings.deployment instead of
comparing ENV or AUTH_MODE itself.
"""

from dataclasses import dataclass
from enum import StrEnum
from functools import cache
from typing import Literal


class DeploymentKind(StrEnum):
    """Which kind of instance this is; the value is the ENV it boots under."""

    PRODUCTION = "production"
    DEVELOPMENT = "development"
    SELFHOST = "selfhost"


AuthMode = Literal["workos", "local"]


class BlobStoreKind(StrEnum):
    """Where uploaded and generated files live; the value is the BLOB_STORE setting."""

    LOCAL = "local"
    CLOUDINARY = "cloudinary"


class OriginPolicy(StrEnum):
    """Which browser origins may call the API cross-origin."""

    # FRONTEND_URL, GAIA's own domains and the desktop app's embedded server.
    GAIA_CLOUD = "gaia_cloud"
    # FRONTEND_URL plus any localhost origin, for dev servers on arbitrary ports.
    LOCAL_DEVELOPMENT = "local_development"
    # FRONTEND_URL only: a self-hosted instance's own domain.
    INSTANCE = "instance"


class InvalidDeploymentError(RuntimeError):
    """Raised for an ENV/AUTH_MODE/BLOB_STORE combination no deployment may run as."""


@dataclass(frozen=True, slots=True)
class DeploymentProfile:
    """What this deployment does, as capabilities rather than environment names."""

    kind: DeploymentKind
    local_auth: bool
    # Payments are live (checkout, plan catalogue, paywall UI).
    bills: bool
    # A user's plan gates access; off means everyone is top tier.
    enforces_plans: bool
    # Rate, cost and cap walls block once exhausted.
    enforces_usage_limits: bool
    # Provider keys may be stored at runtime; off means env only.
    runtime_credentials: bool
    # GAIA Cloud's per-role model routing and generators, not the instance's own.
    hosted_models: bool
    # The catalog's Composio auth configs are this project's.
    catalog_composio_auth_configs: bool
    # Keyless code runs on the host Docker daemon (self-host opt-in).
    local_code_sandbox: bool
    # The workspace is a local volume, not a JuiceFS mount.
    local_workspace: bool
    # Where files live (BLOB_STORE); never local in production.
    blob_store: BlobStoreKind
    # In-app support requests go to GAIA's support team.
    gaia_support: bool
    # GAIA Cloud's own chat bots (@heygaia_bot) serve this deployment's users.
    hosted_bots: bool
    # GAIA Cloud's own PostHog project receives this instance's product analytics.
    product_analytics: bool
    # Unreachable infrastructure stops the boot; off only in development.
    fail_fast: bool
    # A key the capability table needs refuses the boot. Self-host only: its
    # .env is CLI-written, while GAIA Cloud warns and degrades the one feature.
    requires_complete_config: bool
    # GET /health/ready answers anyone; on GAIA Cloud only the METRICS_TOKEN scraper.
    public_readiness: bool
    trusted_origins: OriginPolicy
    # Every client reaches it over https: session cookies are always Secure and
    # share links refuse a plain-http HOST.
    https_only: bool
    # A provider endpoint the admin configures may be a private-network address.
    private_network_endpoints: bool
    # The auth bypass, dev router, open API docs, model selector and custom lane.
    dev_tools: bool


def baseline_profile(kind: DeploymentKind) -> DeploymentProfile:
    """Return the profile a kind boots with when nothing optional is set (self-host signs in locally)."""
    return deployment_profile(
        kind,
        "local"
        if kind is DeploymentKind.SELFHOST
        else "workos",  # pragma: no mutate — only == "local" is read
        unlimited_usage=False,
        local_code_sandbox=False,
        blob_store=None,
    )


_TRUSTED_ORIGINS = {
    DeploymentKind.PRODUCTION: OriginPolicy.GAIA_CLOUD,
    DeploymentKind.DEVELOPMENT: OriginPolicy.LOCAL_DEVELOPMENT,
    DeploymentKind.SELFHOST: OriginPolicy.INSTANCE,
}


@cache
def deployment_profile(
    kind: DeploymentKind,
    auth_mode: AuthMode,
    *,
    unlimited_usage: bool,
    local_code_sandbox: bool,
    blob_store: BlobStoreKind | None,
) -> DeploymentProfile:
    """Build the profile for one ENV/AUTH_MODE pair; raise on a pair that must never run.

    unlimited_usage is the development-only DEV_UNLIMITED_RATE_LIMITS switch;
    local_code_sandbox is the self-host LOCAL_CODE_SANDBOX opt-in; blob_store
    is BLOB_STORE, None when unset.
    """
    local_auth = auth_mode == "local"
    if kind is DeploymentKind.PRODUCTION and local_auth:
        raise InvalidDeploymentError(
            "AUTH_MODE=local is set but ENV=production — local username/password "
            "auth is a self-host feature and must never run against production. "
            "Use ENV=selfhost for local auth."
        )
    if kind is DeploymentKind.PRODUCTION and blob_store is BlobStoreKind.LOCAL:
        raise InvalidDeploymentError(
            "BLOB_STORE=local is set but ENV=production — hosted files are served "
            "from Cloudinary and must never land on a container's local disk."
        )
    enforces_plans = kind is not DeploymentKind.SELFHOST
    return DeploymentProfile(
        kind=kind,
        local_auth=local_auth,
        bills=kind is DeploymentKind.PRODUCTION,
        enforces_plans=enforces_plans,
        enforces_usage_limits=enforces_plans and not unlimited_usage,
        runtime_credentials=kind is DeploymentKind.SELFHOST or local_auth,
        hosted_models=kind is DeploymentKind.PRODUCTION,
        catalog_composio_auth_configs=kind is not DeploymentKind.SELFHOST,
        local_code_sandbox=kind is DeploymentKind.SELFHOST and local_code_sandbox,
        local_workspace=kind is DeploymentKind.SELFHOST,
        blob_store=blob_store
        or (BlobStoreKind.LOCAL if kind is DeploymentKind.SELFHOST else BlobStoreKind.CLOUDINARY),
        gaia_support=kind is not DeploymentKind.SELFHOST,
        hosted_bots=kind is not DeploymentKind.SELFHOST,
        product_analytics=kind is DeploymentKind.PRODUCTION,
        fail_fast=kind is not DeploymentKind.DEVELOPMENT,
        requires_complete_config=kind is DeploymentKind.SELFHOST,
        public_readiness=kind is not DeploymentKind.PRODUCTION,
        trusted_origins=_TRUSTED_ORIGINS[kind],
        https_only=kind is DeploymentKind.PRODUCTION,
        private_network_endpoints=kind is not DeploymentKind.PRODUCTION,
        dev_tools=kind is DeploymentKind.DEVELOPMENT,
    )
