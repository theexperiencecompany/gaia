"""What each deployment capability needs from the environment.

The one table the boot check, the settings validator's warnings and the CLI's
config schema (scripts/dump_config_schema.py) all derive from.
"""

from collections.abc import Callable
from dataclasses import dataclass

from app.config.deployment import BlobStoreKind, DeploymentKind, DeploymentProfile


@dataclass(frozen=True, slots=True)
class CapabilityRequirement:
    """Settings keys a deployment must set whenever the capability applies to its profile."""

    capability: str
    applies: Callable[[DeploymentProfile], bool]
    keys: tuple[str, ...]
    # The keys do nothing while the capability is off, so a missing one is not worth a warning.
    unused_otherwise: bool = False


CAPABILITY_REQUIREMENTS: tuple[CapabilityRequirement, ...] = (
    CapabilityRequirement(
        capability="every deployment",
        applies=lambda _profile: True,
        keys=("MONGO_DB", "REDIS_URL"),
    ),
    CapabilityRequirement(
        capability="fail_fast: the full infrastructure and the machine secrets",
        applies=lambda profile: profile.fail_fast,
        keys=(
            "CHROMADB_HOST",
            "CHROMADB_PORT",
            "POSTGRES_URL",
            "RABBITMQ_URL",
            "AGENT_SECRET",
            "BOT_SESSION_TOKEN_SECRET",
            "EMAIL_UNSUBSCRIBE_SECRET",
        ),
    ),
    CapabilityRequirement(
        capability="not local_auth: WorkOS signs users in",
        applies=lambda profile: not profile.local_auth,
        keys=("WORKOS_API_KEY", "WORKOS_CLIENT_ID", "WORKOS_COOKIE_PASSWORD"),
        unused_otherwise=True,
    ),
    CapabilityRequirement(
        capability="bills",
        applies=lambda profile: profile.bills,
        keys=("DODO_PAYMENTS_API_KEY", "DODO_WEBHOOK_PAYMENTS_SECRET"),
        unused_otherwise=True,
    ),
    CapabilityRequirement(
        capability="blob_store=cloudinary",
        applies=lambda profile: profile.blob_store is BlobStoreKind.CLOUDINARY,
        keys=("CLOUDINARY_CLOUD_NAME", "CLOUDINARY_API_KEY", "CLOUDINARY_API_SECRET"),
        unused_otherwise=True,
    ),
    CapabilityRequirement(
        capability="not local_workspace: R2 + JuiceFS workspaces in E2B sandboxes",
        applies=lambda profile: not profile.local_workspace,
        keys=(
            "R2_ACCOUNT_ID",
            "R2_BUCKET",
            "R2_ACCESS_KEY",
            "R2_SECRET_KEY",
            "JUICEFS_META_URL_TEMPLATE",
            "E2B_API_KEY",
            "E2B_TEMPLATE_ID",
            "E2B_DOMAIN",
        ),
    ),
    CapabilityRequirement(
        capability="hosted_models",
        applies=lambda profile: profile.hosted_models,
        keys=("OPENROUTER_API_KEY", "GOOGLE_API_KEY", "OPENAI_API_KEY"),
    ),
    CapabilityRequirement(
        capability="catalog_composio_auth_configs: the catalog's Composio project",
        applies=lambda profile: profile.catalog_composio_auth_configs,
        keys=("COMPOSIO_KEY", "COMPOSIO_WEBHOOK_SECRET"),
    ),
    CapabilityRequirement(
        capability="GAIA Cloud's own integrations, voice and operations",
        applies=lambda profile: profile.kind is DeploymentKind.PRODUCTION,
        keys=(
            "GOOGLE_CLIENT_ID",
            "GOOGLE_CLIENT_SECRET",
            "TAVILY_API_KEY",
            "FIRECRAWL_API_KEY",
            "LLAMA_INDEX_KEY",
            "OPENWEATHER_API_KEY",
            "RESEND_API_KEY",
            "RESEND_AUDIENCE_ID",
            "SHARE_GRANT_SECRET",
            "LIVEKIT_URL",
            "LIVEKIT_API_KEY",
            "LIVEKIT_API_SECRET",
            "DEEPGRAM_API_KEY",
            "ELEVENLABS_API_KEY",
            "ELEVENLABS_TTS_MODEL",
            "ELEVENLABS_VOICE_ID",
            "GAIA_BACKEND_URL",
            "BLOG_BEARER_TOKEN",
            "SENTRY_DSN",
            "MCP_ENCRYPTION_KEY",
            "VERCEL_MCP_CLIENT_ID",
            "NOTION_MCP_CLIENT_ID",
            "NOTION_MCP_CLIENT_SECRET",
            "FIGMA_MCP_CLIENT_ID",
            "FIGMA_MCP_CLIENT_SECRET",
        ),
    ),
)


def required_keys(profile: DeploymentProfile) -> frozenset[str]:
    """Every settings key the profile's capabilities need set."""
    return frozenset(
        key
        for requirement in CAPABILITY_REQUIREMENTS
        if requirement.applies(profile)
        for key in requirement.keys
    )


def unused_keys(profile: DeploymentProfile) -> frozenset[str]:
    """Keys that do nothing under the profile because their capability is off."""
    return frozenset(
        key
        for requirement in CAPABILITY_REQUIREMENTS
        if requirement.unused_otherwise and not requirement.applies(profile)
        for key in requirement.keys
    )
