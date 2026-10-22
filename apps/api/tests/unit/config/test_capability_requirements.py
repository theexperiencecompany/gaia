"""The capability table: what each deployment must set, pinned to what each one boots with today."""

import pytest

from app.config.capability_requirements import required_keys, unused_keys
from app.config.deployment import DeploymentKind, baseline_profile

# What a hosted production boot warns about when unset: every field
# ProductionSettings declared required, plus the WorkOS trio. Production boots
# without them, as it always has; only self-host refuses a missing key.
PRODUCTION_REQUIRED = frozenset(
    {
        "AGENT_SECRET", "BLOG_BEARER_TOKEN", "BOT_SESSION_TOKEN_SECRET", "CHROMADB_HOST",
        "CHROMADB_PORT", "CLOUDINARY_API_KEY", "CLOUDINARY_API_SECRET",
        "CLOUDINARY_CLOUD_NAME", "COMPOSIO_KEY", "COMPOSIO_WEBHOOK_SECRET",
        "DEEPGRAM_API_KEY", "DODO_PAYMENTS_API_KEY", "DODO_WEBHOOK_PAYMENTS_SECRET",
        "E2B_API_KEY", "E2B_DOMAIN", "E2B_TEMPLATE_ID", "ELEVENLABS_API_KEY",
        "ELEVENLABS_TTS_MODEL", "ELEVENLABS_VOICE_ID", "EMAIL_UNSUBSCRIBE_SECRET",
        "FIGMA_MCP_CLIENT_ID", "FIGMA_MCP_CLIENT_SECRET", "FIRECRAWL_API_KEY",
        "GAIA_BACKEND_URL", "GOOGLE_API_KEY", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET",
        "JUICEFS_META_URL_TEMPLATE", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET",
        "LIVEKIT_URL", "LLAMA_INDEX_KEY", "MCP_ENCRYPTION_KEY", "MONGO_DB",
        "NOTION_MCP_CLIENT_ID", "NOTION_MCP_CLIENT_SECRET", "OPENAI_API_KEY",
        "OPENROUTER_API_KEY", "OPENWEATHER_API_KEY", "POSTGRES_URL", "R2_ACCESS_KEY",
        "R2_ACCOUNT_ID", "R2_BUCKET", "R2_SECRET_KEY", "RABBITMQ_URL", "REDIS_URL",
        "RESEND_API_KEY", "RESEND_AUDIENCE_ID", "SENTRY_DSN", "SHARE_GRANT_SECRET",
        "TAVILY_API_KEY", "VERCEL_MCP_CLIENT_ID",
        "WORKOS_API_KEY", "WORKOS_CLIENT_ID", "WORKOS_COOKIE_PASSWORD",
    }
)  # fmt: skip

# What a self-host boot refuses to start without: infrastructure plus the CLI's machine secrets.
SELFHOST_REQUIRED = frozenset(
    {
        "AGENT_SECRET", "BOT_SESSION_TOKEN_SECRET", "CHROMADB_HOST", "CHROMADB_PORT",
        "EMAIL_UNSUBSCRIBE_SECRET", "MONGO_DB", "POSTGRES_URL", "RABBITMQ_URL", "REDIS_URL",
    }
)  # fmt: skip


def test_production_requires_exactly_what_it_always_has() -> None:
    assert required_keys(baseline_profile(DeploymentKind.PRODUCTION)) == PRODUCTION_REQUIRED


def test_selfhost_requires_exactly_what_it_always_has() -> None:
    assert required_keys(baseline_profile(DeploymentKind.SELFHOST)) == SELFHOST_REQUIRED


def test_a_selfhost_instance_that_stores_files_in_cloudinary_needs_its_credentials() -> None:
    from app.config.deployment import BlobStoreKind, deployment_profile

    profile = deployment_profile(
        DeploymentKind.SELFHOST,
        "local",
        unlimited_usage=False,
        local_code_sandbox=False,
        blob_store=BlobStoreKind.CLOUDINARY,
    )

    assert {"CLOUDINARY_CLOUD_NAME", "CLOUDINARY_API_KEY", "CLOUDINARY_API_SECRET"} <= (
        required_keys(profile)
    )


@pytest.mark.parametrize("kind", list(DeploymentKind))
def test_a_key_is_never_both_required_and_unused(kind: DeploymentKind) -> None:
    profile = baseline_profile(kind)

    assert required_keys(profile).isdisjoint(unused_keys(profile))
