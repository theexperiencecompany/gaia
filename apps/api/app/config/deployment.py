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


class InvalidDeploymentError(RuntimeError):
    """Raised for an ENV/AUTH_MODE/BLOB_STORE combination no deployment may run as."""


@dataclass(frozen=True, slots=True)
class DeploymentProfile:
    """What this deployment does, as capabilities rather than environment names.

    bills: payments are live (checkout, plan catalogue, paywall UI).
    enforces_plans: a user's plan gates access; off means everyone is top tier.
    enforces_usage_limits: rate, cost and cap walls block once exhausted.
    runtime_credentials: provider keys may be stored at runtime; off means env only.
    hosted_models: GAIA Cloud's per-role model routing and generators, not the instance's own.
    catalog_composio_auth_configs: the catalog's Composio auth config ids exist in
        this deployment's Composio project; off means the instance brings its own.
    local_code_sandbox: keyless code runs on the host Docker daemon (self-host opt-in).
    local_workspace: the workspace is a local volume, not a JuiceFS mount.
    blob_store: where files live (BLOB_STORE); never local in production.
    """

    kind: DeploymentKind
    local_auth: bool
    bills: bool
    enforces_plans: bool
    enforces_usage_limits: bool
    runtime_credentials: bool
    hosted_models: bool
    catalog_composio_auth_configs: bool
    local_code_sandbox: bool
    local_workspace: bool
    blob_store: BlobStoreKind


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
    )
