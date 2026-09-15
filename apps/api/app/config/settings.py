"""Application settings: load from env, validate, and expose typed access.

Flow
- .env loaded first, then external secrets via inject_infisical_secrets().
- Pick settings class by ENV (production/development).
- Pydantic builds the object; settings_validator logs missing groups.
- get_settings() memoizes the instance for fast imports.

Add env vars
1) Add fields to CommonSettings/ProductionSettings/DevelopmentSettings.
2) Use Optional[...] in dev if it’s not required there.
3) If you want warnings, register a group in config/settings_validator.py.
4) Read values via from app.config.settings import settings.
"""

from functools import lru_cache
import os
import time
from typing import Any, Literal, Self

from dotenv import load_dotenv
from pydantic import computed_field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.config.secrets import inject_infisical_secrets
from app.config.settings_validator import settings_validator
from app.constants.log_tags import LogTag
from app.constants.search import (
    CRAWL4AI_DEFAULT_MAX_BROWSERS,
    CRAWL4AI_MIN_MAX_BROWSERS,
)
from shared.py.wide_events import log

load_dotenv()


class BaseAppSettings(BaseSettings):
    """Base configuration settings for the application."""

    ENV: Literal["production", "development"] = "production"

    SHOW_MISSING_KEY_WARNINGS: bool = True

    model_config = SettingsConfigDict(
        extra="allow",
        env_file_encoding="utf-8",
        validate_default=False,  # Skip validation of default values
    )

    # For handling both normal env var loading and dict constructor
    @classmethod
    def from_env(cls, **kwargs: Any) -> Self:  # noqa: ANN401 -- framework contract
        """Create settings from environment variables."""
        try:
            return cls(**kwargs)
        except Exception as e:
            log.warning(
                f"{LogTag.STARTUP} Error creating settings",
                error=str(e),
                error_type=type(e).__name__,
            )
            # Create a minimal instance with empty strings for required fields,
            # but skip fields that already have env vars set or have defaults.
            fields = cls.model_fields
            defaults: dict[str, Any] = {}
            for field_name, field_info in fields.items():
                if field_name in kwargs:
                    continue
                if os.getenv(field_name) is not None:
                    continue
                if field_info.default is not None:
                    continue
                if "str" in str(field_info.annotation):
                    defaults[field_name] = ""
            return cls(**defaults, **kwargs)


class CommonSettings(BaseAppSettings):
    """Common settings required for all environments."""

    # Dev-only overrides, declared on the COMMON base so production code can
    # safely read them (app/agents/llm/client.py evaluates GAIA_SIM_MODE at
    # import time). get_settings() refuses to start in production if set.
    GAIA_SIM_MODE: bool = False  # every LLM factory resolves to the local scripted stub
    # Where the scripted stub lives when sim mode is on; consumed only by
    # _sim_llm (defaults to SIM_STUB_BASE_URL when unset).
    OPENROUTER_BASE_URL: str | None = None
    # Comma-separated OpenRouter provider slugs to PREFER for the default-model
    # lane — fallbacks stay enabled. Set from the per-provider cache-hit table;
    # see _provider_order_kwargs in agents/llm/client.py.
    OPENROUTER_PROVIDER_ORDER: str | None = None
    # Dev-only: lift every per-user rate limit. Eval harnesses drive thousands
    # of requests/day against a free-plan dev user, which 429s at 200/day
    # otherwise. get_settings() refuses production boot when set.
    DEV_UNLIMITED_RATE_LIMITS: bool = False

    # ----------------------------------------------
    # Database Connections
    # ----------------------------------------------
    MONGO_DB: str
    REDIS_URL: str

    # ----------------------------------------------
    # Authentication & OAuth
    # ----------------------------------------------
    WORKOS_API_KEY: str
    WORKOS_CLIENT_ID: str
    WORKOS_COOKIE_PASSWORD: str

    # ----------------------------------------------
    # Environment & Deployment
    # ----------------------------------------------
    HOST: str = "https://api.heygaia.io"
    FRONTEND_URL: str = "https://heygaia.io"
    DUMMY_IP: str = "8.8.8.8"
    WORKER_TYPE: str = "unknown"
    ENABLE_LAZY_LOADING: bool = True

    @field_validator("HOST", "FRONTEND_URL", mode="after")
    @classmethod
    def _strip_trailing_slash(cls, v: str) -> str:
        return v.rstrip("/") if isinstance(v, str) else v

    # Key into the provider registry in app/services/email/providers.
    EMAIL_PROVIDER: str = "resend"

    # Optional coupon surfaced alongside the checkout link in every 402
    # "subscription required" response. Unset means no code is advertised.
    PAYWALL_DISCOUNT_CODE: str | None = None

    # ----------------------------------------------
    # Observability
    # ----------------------------------------------
    POSTHOG_PROJECT_TOKEN: str | None = None
    POSTHOG_HOST: str | None = None

    # Secret token Prometheus sends as "Authorization: Bearer <token>" when
    # scraping /metrics. Generate with: openssl rand -hex 32
    METRICS_TOKEN: str | None = None

    # Langfuse — opt-in self-hosted LLM observability. Traces ship only when
    # all three are set; missing any one is a silent no-op in every env.
    LANGFUSE_PUBLIC_KEY: str | None = None
    LANGFUSE_SECRET_KEY: str | None = None
    LANGFUSE_HOST: str | None = None

    # ----------------------------------------------
    # Profiling & Performance Monitoring
    # ----------------------------------------------
    ENABLE_PROFILING: bool = False  # Must be explicitly enabled via .env
    PROFILING_SAMPLE_RATE: float = 1.0  # 100% of requests by default

    # Concurrent jobs PER WORKER; sized via Little's Law (mean task 10.9s at
    # 0.72 tasks/s needs ~8). Fleet ceiling is 10 x M workers — scale this DOWN
    # (~ceil(8/M)) per worker added, since pools sum to 35 conns vs max 100.
    ARQ_MAX_JOBS: int = 10

    # Process-wide cap on concurrent Chromium instances (see constants/search.py).
    # Falls back to the default on non-integer input; clamped to at least
    # CRAWL4AI_MIN_MAX_BROWSERS so a 0/negative value can't deadlock all crawler access.
    CRAWL4AI_MAX_BROWSERS: int = CRAWL4AI_DEFAULT_MAX_BROWSERS

    @field_validator("CRAWL4AI_MAX_BROWSERS", mode="before")
    @classmethod
    def _normalize_crawl4ai_max_browsers(cls, value: int | str | None) -> int:
        if value is None:
            return CRAWL4AI_DEFAULT_MAX_BROWSERS
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return CRAWL4AI_DEFAULT_MAX_BROWSERS
        return max(CRAWL4AI_MIN_MAX_BROWSERS, parsed)

    # Custom OpenRouter/OpenAI-compatible endpoint for cheap bulk dev/test usage.
    # All three must be set; the "custom" provider is registered exclusively in
    # development (see register_llm_providers), so these have no effect in production.
    DEV_LLM_BASE_URL: str | None = None
    DEV_LLM_API_KEY: str | None = None
    DEV_LLM_MODEL: str | None = None
    # Default model for every dev request that doesn't pick one in the chat-header
    # selector — any DEV_MODEL_OPTIONS key from app/constants/llm.py ("custom" =
    # the endpoint above). An explicit selector choice still wins.
    DEV_DEFAULT_MODEL: str | None = None

    # Deletes a workflow conversation's LangGraph checkpoint threads before every
    # run, so run N stops replaying runs 1..N-1 (one production workflow held
    # 1.39 MB across three threads). Kill switch: set false to disable without a deploy.
    WORKFLOW_THREAD_RESET_ENABLED: bool = True

    # Optional GitHub token (no scopes needed): 5,000 API requests/hour vs
    # 60/hour without, for discovering and installing skills from GitHub.
    GITHUB_TOKEN: str | None = None

    # check_fields=False: E2B_DOMAIN is declared per-environment in the subclasses.
    # Rejected rather than stripped because the e2b SDK reads os.environ verbatim —
    # "" there silently falls back to the US cluster, padding yields a broken URL.
    @field_validator("E2B_DOMAIN", mode="after", check_fields=False)
    @classmethod
    def _reject_unusable_e2b_domain(cls, v: str | None) -> str | None:
        if v is not None and (not v or v != v.strip()):
            raise ValueError("E2B_DOMAIN must be non-empty and free of surrounding whitespace")
        return v

    # ----------------------------------------------
    # Computed Properties
    # ----------------------------------------------

    # OAuth Callback URLs
    @computed_field  # type: ignore[prop-decorator]  # pydantic’s computed_field over @property trips mypy’s prop-decorator check
    @property
    def WORKOS_REDIRECT_URI(self) -> str:
        """WorkOS OAuth callback URL."""
        return f"{self.HOST}/api/v1/oauth/workos/callback"

    @computed_field  # type: ignore[prop-decorator]  # pydantic’s computed_field over @property trips mypy’s prop-decorator check
    @property
    def WORKOS_DESKTOP_REDIRECT_URI(self) -> str:
        """WorkOS OAuth callback URL for desktop app."""
        return f"{self.HOST}/api/v1/oauth/workos/desktop/callback"

    @computed_field  # type: ignore[prop-decorator]  # pydantic’s computed_field over @property trips mypy’s prop-decorator check
    @property
    def WORKOS_MOBILE_REDIRECT_URI(self) -> str:
        """WorkOS OAuth callback URL for mobile app."""
        return f"{self.HOST}/api/v1/oauth/workos/mobile/callback"

    @computed_field  # type: ignore[prop-decorator]  # pydantic’s computed_field over @property trips mypy’s prop-decorator check
    @property
    def COMPOSIO_REDIRECT_URI(self) -> str:
        """Composio OAuth callback URL."""
        return f"{self.HOST}/api/v1/oauth/composio/callback"

    @computed_field  # type: ignore[prop-decorator]  # pydantic’s computed_field over @property trips mypy’s prop-decorator check
    @property
    def GOOGLE_CALLBACK_URL(self) -> str:
        """Google OAuth callback URL."""
        return f"{self.HOST}/api/v1/oauth/google/callback"

    @computed_field  # type: ignore[prop-decorator]  # pydantic’s computed_field over @property trips mypy’s prop-decorator check
    @property
    def DISCORD_OAUTH_REDIRECT_URI(self) -> str:
        """Discord OAuth callback URL."""
        return f"{self.HOST}/api/v1/platform-auth/discord/callback"

    @computed_field  # type: ignore[prop-decorator]  # pydantic’s computed_field over @property trips mypy’s prop-decorator check
    @property
    def SLACK_OAUTH_REDIRECT_URI(self) -> str:
        """Slack OAuth callback URL."""
        return f"{self.HOST}/api/v1/platform-auth/slack/callback"

    model_config = SettingsConfigDict(
        env_file_encoding="utf-8",
        extra="allow",
        validate_default=False,
        arbitrary_types_allowed=True,
    )


class ProductionSettings(CommonSettings):
    """Strict settings required for production environment."""

    # ----------------------------------------------
    # Database & Message Queue Connections
    # ----------------------------------------------
    CHROMADB_HOST: str
    CHROMADB_PORT: int
    POSTGRES_URL: str
    RABBITMQ_URL: str

    # ----------------------------------------------
    # Authentication & OAuth
    # ----------------------------------------------
    GOOGLE_TOKEN_URL: str = "https://oauth2.googleapis.com/token"
    GOOGLE_CLIENT_ID: str
    GOOGLE_CLIENT_SECRET: str

    # ----------------------------------------------
    # External API Integration Keys
    # ----------------------------------------------
    TAVILY_API_KEY: str
    LLAMA_INDEX_KEY: str

    # AI & Machine Learning
    OPENAI_API_KEY: str
    GOOGLE_API_KEY: str
    OPENROUTER_API_KEY: str

    # Weather Services
    OPENWEATHER_API_KEY: str

    # Email & Communication
    RESEND_API_KEY: str
    RESEND_AUDIENCE_ID: str
    EMAIL_UNSUBSCRIBE_SECRET: str
    # Signs single-purpose file-share grants (fetched by Composio during tool
    # execution). Dedicated secret so share tokens are domain-separated from
    # unsubscribe links.
    SHARE_GRANT_SECRET: str

    # Media Storage
    CLOUDINARY_CLOUD_NAME: str
    CLOUDINARY_API_KEY: str
    CLOUDINARY_API_SECRET: str

    # External Service Integration
    COMPOSIO_KEY: str
    FIRECRAWL_API_KEY: str

    # Multi-provider failover, all optional. Exa is the primary free workhorse
    # (20k/mo free); SearXNG is the self-hosted unlimited floor; Brave is a budget-capped booster.
    EXA_API_KEY: str | None = None
    BRAVE_API_KEY: str | None = None
    SEARXNG_BASE_URL: str | None = None

    # Voice Agent Configuration
    LIVEKIT_URL: str
    LIVEKIT_API_KEY: str
    LIVEKIT_API_SECRET: str
    AGENT_SECRET: str
    DEEPGRAM_API_KEY: str
    ELEVENLABS_API_KEY: str
    ELEVENLABS_TTS_MODEL: str
    GAIA_BACKEND_URL: str
    ELEVENLABS_VOICE_ID: str
    # URL the SHARED voice agent uses to reach THIS backend. Unset keeps the
    # agent on its boot-time GAIA_BACKEND_URL — set in multi-backend deployments
    # (one agent, many preview APIs).
    VOICE_AGENT_BACKEND_URL: str | None = None

    # ----------------------------------------------
    # Webhook Secrets & Security
    # ----------------------------------------------
    COMPOSIO_WEBHOOK_SECRET: str
    DODO_WEBHOOK_PAYMENTS_SECRET: str

    # ----------------------------------------------
    # Content Management
    # ----------------------------------------------
    BLOG_BEARER_TOKEN: str  # Bearer token for blog management operations

    # ----------------------------------------------
    # Code Execution Environment
    # ----------------------------------------------
    E2B_API_KEY: str
    E2B_TEMPLATE_ID: str  # gaia-coder template ID (run scripts/build_e2b_template.py)
    E2B_DOMAIN: str
    # A paused sandbox pays a full JuiceFS remount on resume. 60s paused too
    # eagerly between turns; trade-off vs live-sandbox count is the E2B quota
    # (scalable fix: the warm pool, E2B_WARM_POOL_TARGET_RATIO).
    E2B_SANDBOX_IDLE_PAUSE_SECONDS: int = 300
    E2B_DEFAULT_BASH_TIMEOUT: int = 120
    E2B_SANDBOX_EVICT_DAYS: int = 14
    E2B_WARM_POOL_TARGET_RATIO: float = 2.0  # Phase 2
    # Artifact detection mechanism — decided empirically by
    # scripts/probe_artifact_detection.py (Phase 0). "watch_dir" uses E2B
    # envd's native recursive watch; "accesslog" tails JuiceFS .accesslog.
    ARTIFACT_DETECTION_MODE: Literal["watch_dir", "accesslog"] = "watch_dir"
    ARTIFACT_WATCHER_INODE_CACHE_SIZE: int = 4096  # accesslog mode only

    # ----------------------------------------------
    # Persistent Workspace Storage (R2 + JuiceFS)
    # ----------------------------------------------
    R2_ACCOUNT_ID: str
    R2_BUCKET: str  # e.g. "gaia-workspaces"
    R2_ACCESS_KEY: str
    R2_SECRET_KEY: str
    # Templated metadata URL, {shard} substituted at mount time, e.g.
    # "rediss://:pass@jfs-meta.heygaia.io:6380/{shard}". Password is split out
    # into META_PASSWORD before reaching the sandbox (_split_meta_url in services/sandbox/lifecycle.py).
    JUICEFS_META_URL_TEMPLATE: str
    JUICEFS_NUM_SHARDS: int = 1  # Phase 1: 1, Phase 2: 16
    # JuiceFS RSA-4096 private key (PEM), written to disk by the entrypoint on
    # boot. Optional — leave empty to skip client-side encryption (R2 at-rest
    # encryption still applies).
    JFS_ENCRYPTION_KEY: str | None = None
    JUICEFS_HOST_MOUNT_PATH: str = "/mnt/jfs"  # API container's sidecar mount
    # JuiceFS bootstrap supervisor (tune per env without a code change):
    JUICEFS_MOUNT_READY_TIMEOUT: int = 90  # secs to wait for mount readiness
    JUICEFS_BOOTSTRAP_MAX_ATTEMPTS: int = 20  # retries on transient meta errors
    JUICEFS_BOOTSTRAP_RETRY_BACKOFF: int = 3  # base secs, exponential, cap 15
    SESSION_RETENTION_DAYS: int = 30  # prune sessions after this inactivity
    SESSION_PRUNE_BATCH_LIMIT: int = 1000  # safety cap per prune task run

    # ----------------------------------------------
    # Payment Processing
    # ----------------------------------------------
    DODO_PAYMENTS_API_KEY: str
    DODO_PAYMENTS_BASE_URL: str | None = None

    # ----------------------------------------------
    # Monitoring & Analytics
    # ----------------------------------------------
    SENTRY_DSN: str

    # ----------------------------------------------
    # MCP OAuth Credentials
    # ----------------------------------------------
    MCP_ENCRYPTION_KEY: str
    VERCEL_MCP_CLIENT_ID: str
    NOTION_MCP_CLIENT_ID: str
    NOTION_MCP_CLIENT_SECRET: str
    FIGMA_MCP_CLIENT_ID: str
    FIGMA_MCP_CLIENT_SECRET: str

    # ----------------------------------------------
    # Eval / Skills Test Config (used by tests/skills via tests/conftest.py)
    # ----------------------------------------------
    EVAL_USER_ID: str | None = None
    EVAL_USER_EMAIL: str | None = None
    EVAL_USER_NAME: str | None = None

    # ----------------------------------------------
    # Debug Config
    # ----------------------------------------------
    DEBUG_EMAIL_PROCESSING: bool = False

    # ----------------------------------------------
    # Bot Configuration
    # ----------------------------------------------
    GAIA_BOT_API_KEY: str | None = None
    DISCORD_BOT_TOKEN: str | None = None
    DISCORD_CLIENT_ID: str | None = None
    SLACK_BOT_TOKEN: str | None = None
    SLACK_SIGNING_SECRET: str | None = None
    SLACK_APP_TOKEN: str | None = None
    TELEGRAM_BOT_TOKEN: str | None = None
    KAPSO_API_KEY: str | None = None
    KAPSO_PHONE_NUMBER_ID: str | None = None
    WHATSAPP_PHONE_NUMBER: str | None = (
        None  # E.164 without +, e.g. "15551234567" — used for wa.me links
    )
    SPECTRUM_PROJECT_ID: str | None = None
    SPECTRUM_PROJECT_SECRET: str | None = None

    # ----------------------------------------------
    # Bot OAuth Configuration (Optional)
    # ----------------------------------------------
    DISCORD_OAUTH_CLIENT_ID: str | None = None
    DISCORD_OAUTH_CLIENT_SECRET: str | None = None
    SLACK_OAUTH_CLIENT_ID: str | None = None
    SLACK_OAUTH_CLIENT_SECRET: str | None = None
    TELEGRAM_BOT_USERNAME: str | None = "heygaia_bot"

    # ----------------------------------------------
    # Bot Session Token Configuration
    # ----------------------------------------------
    BOT_SESSION_TOKEN_SECRET: str  # Required: min 32 chars - DO NOT reuse GAIA_BOT_API_KEY
    BOT_SESSION_TOKEN_EXPIRY_MINUTES: int = 15

    @field_validator("DODO_PAYMENTS_BASE_URL", mode="after")
    @classmethod
    def _dodo_base_url_must_be_https(cls, v: str | None) -> str | None:
        """Production must not send the Dodo API key over plain HTTP.

        The override exists for pointing the Dodo client at a local stub or
        sandbox mirror — a dev/test concern. Production traffic must use TLS,
        so reject an explicit http:// override rather than silently leaking
        the bearer token in cleartext. Unset (None) stays allowed.
        """
        if v is not None and v and not v.startswith("https://"):
            raise ValueError("DODO_PAYMENTS_BASE_URL must use https:// in production")
        return v

    model_config = SettingsConfigDict(
        env_file_encoding="utf-8",
        extra="allow",
    )


class DevelopmentSettings(CommonSettings):
    """Looser settings for development environment with defaults."""

    # ----------------------------------------------
    # Database & Message Queue Connections
    # ----------------------------------------------
    CHROMADB_HOST: str | None = None
    CHROMADB_PORT: int | None = None
    POSTGRES_URL: str | None = None
    RABBITMQ_URL: str | None = None

    # ----------------------------------------------
    # Authentication & OAuth
    # ----------------------------------------------
    GOOGLE_CLIENT_ID: str | None = None
    GOOGLE_CLIENT_SECRET: str | None = None
    ENABLE_PUBSUB_JWT_VERIFICATION: bool = False
    GOOGLE_USERINFO_URL: str = "https://www.googleapis.com/oauth2/v2/userinfo"
    GOOGLE_TOKEN_URL: str = "https://oauth2.googleapis.com/token"

    # Search & Data Services
    TAVILY_API_KEY: str | None = None
    LLAMA_INDEX_KEY: str | None = None

    # AI & Machine Learning
    OPENAI_API_KEY: str | None = None
    GOOGLE_API_KEY: str | None = None
    OPENROUTER_API_KEY: str | None = None

    # Weather Services
    OPENWEATHER_API_KEY: str | None = None

    # Email & Communication
    RESEND_API_KEY: str | None = None
    RESEND_AUDIENCE_ID: str | None = None
    EMAIL_UNSUBSCRIBE_SECRET: str | None = None
    SHARE_GRANT_SECRET: str | None = None

    # Media Storage
    CLOUDINARY_CLOUD_NAME: str | None = None
    CLOUDINARY_API_KEY: str | None = None
    CLOUDINARY_API_SECRET: str | None = None

    # External Service Integration
    COMPOSIO_KEY: str | None = None
    FIRECRAWL_API_KEY: str | None = None

    # Search providers (multi-provider failover; all optional)
    EXA_API_KEY: str | None = None
    BRAVE_API_KEY: str | None = None
    SEARXNG_BASE_URL: str | None = None

    # ----------------------------------------------
    # Webhook Secrets & Security
    # ----------------------------------------------
    COMPOSIO_WEBHOOK_SECRET: str | None = None
    DODO_WEBHOOK_PAYMENTS_SECRET: str | None = None

    # Voice Agent Configuration
    LIVEKIT_URL: str | None = None
    LIVEKIT_API_KEY: str | None = None
    LIVEKIT_API_SECRET: str | None = None
    AGENT_SECRET: str | None = None
    DEEPGRAM_API_KEY: str | None = None
    ELEVENLABS_API_KEY: str | None = None
    ELEVENLABS_TTS_MODEL: str | None = None
    GAIA_BACKEND_URL: str | None = "http://host.docker.internal:8000"
    ELEVENLABS_VOICE_ID: str | None = None
    VOICE_AGENT_BACKEND_URL: str | None = None

    # ----------------------------------------------
    # Content Management
    # ----------------------------------------------
    BLOG_BEARER_TOKEN: str | None = None  # Bearer token for blog management operations

    # ----------------------------------------------
    # Code Execution Environment
    # ----------------------------------------------
    E2B_API_KEY: str | None = None
    E2B_TEMPLATE_ID: str | None = None
    E2B_DOMAIN: str | None = None
    # A paused sandbox pays a full JuiceFS remount on resume. 60s paused too
    # eagerly between turns; trade-off vs live-sandbox count is the E2B quota
    # (scalable fix: the warm pool, E2B_WARM_POOL_TARGET_RATIO).
    E2B_SANDBOX_IDLE_PAUSE_SECONDS: int = 300
    E2B_DEFAULT_BASH_TIMEOUT: int = 120
    E2B_SANDBOX_EVICT_DAYS: int = 14
    E2B_WARM_POOL_TARGET_RATIO: float = 2.0
    ARTIFACT_DETECTION_MODE: Literal["watch_dir", "accesslog"] = "watch_dir"
    ARTIFACT_WATCHER_INODE_CACHE_SIZE: int = 4096

    # ----------------------------------------------
    # Persistent Workspace Storage (R2 + JuiceFS)
    # ----------------------------------------------
    R2_ACCOUNT_ID: str | None = None
    R2_BUCKET: str | None = None
    R2_ACCESS_KEY: str | None = None
    R2_SECRET_KEY: str | None = None
    JUICEFS_META_URL_TEMPLATE: str | None = None
    JUICEFS_NUM_SHARDS: int = 1
    JFS_ENCRYPTION_KEY: str | None = None
    JUICEFS_HOST_MOUNT_PATH: str = "/mnt/jfs"
    JUICEFS_MOUNT_READY_TIMEOUT: int = 90
    JUICEFS_BOOTSTRAP_MAX_ATTEMPTS: int = 20
    JUICEFS_BOOTSTRAP_RETRY_BACKOFF: int = 3
    SESSION_RETENTION_DAYS: int = 30
    SESSION_PRUNE_BATCH_LIMIT: int = 1000

    # ----------------------------------------------
    # Payment Processing
    # ----------------------------------------------
    DODO_PAYMENTS_API_KEY: str | None = None
    DODO_PAYMENTS_BASE_URL: str | None = None

    # ----------------------------------------------
    # Monitoring & Analytics
    # ----------------------------------------------
    SENTRY_DSN: str | None = None

    # ----------------------------------------------
    # MCP OAuth Credentials
    # ----------------------------------------------
    MCP_ENCRYPTION_KEY: str | None = None
    VERCEL_MCP_CLIENT_ID: str | None = None
    NOTION_MCP_CLIENT_ID: str | None = None
    NOTION_MCP_CLIENT_SECRET: str | None = None
    FIGMA_MCP_CLIENT_ID: str | None = None
    FIGMA_MCP_CLIENT_SECRET: str | None = None

    # ----------------------------------------------
    # Eval / Skills Test Config (used by tests/skills via tests/conftest.py)
    # ----------------------------------------------
    EVAL_USER_ID: str | None = None
    EVAL_USER_EMAIL: str | None = None
    EVAL_USER_NAME: str | None = None

    # ----------------------------------------------
    # Environment Configuration
    # ----------------------------------------------
    ENV: Literal["production", "development"] = "development"

    # ----------------------------------------------
    # Debug Config
    # ----------------------------------------------
    DEBUG_EMAIL_PROCESSING: bool = False

    # Every request authenticates as this Mongo user with no WorkOS session;
    # get_settings() refuses to start in production when this is set.
    DEV_AUTH_BYPASS_EMAIL: str | None = None

    # GAIA_SIM_MODE and OPENROUTER_BASE_URL are declared on CommonSettings (the
    # production import path reads them) — see the note there.

    # Default to show warnings in development environment
    SHOW_MISSING_KEY_WARNINGS: bool = True

    # ----------------------------------------------
    # Bot Configuration
    # ----------------------------------------------
    GAIA_BOT_API_KEY: str | None = None
    DISCORD_BOT_TOKEN: str | None = None
    DISCORD_CLIENT_ID: str | None = None
    SLACK_BOT_TOKEN: str | None = None
    SLACK_SIGNING_SECRET: str | None = None
    SLACK_APP_TOKEN: str | None = None
    TELEGRAM_BOT_TOKEN: str | None = None
    KAPSO_API_KEY: str | None = None
    KAPSO_PHONE_NUMBER_ID: str | None = None
    WHATSAPP_PHONE_NUMBER: str | None = (
        None  # E.164 without +, e.g. "15551234567" — used for wa.me links
    )
    SPECTRUM_PROJECT_ID: str | None = None
    SPECTRUM_PROJECT_SECRET: str | None = None

    # ----------------------------------------------
    # Bot OAuth Configuration (Optional)
    # ----------------------------------------------
    DISCORD_OAUTH_CLIENT_ID: str | None = None
    DISCORD_OAUTH_CLIENT_SECRET: str | None = None
    SLACK_OAUTH_CLIENT_ID: str | None = None
    SLACK_OAUTH_CLIENT_SECRET: str | None = None
    TELEGRAM_BOT_USERNAME: str | None = "heygaia_bot"

    # ----------------------------------------------
    # Bot Session Token Configuration
    # ----------------------------------------------
    BOT_SESSION_TOKEN_SECRET: str | None = None  # Falls back to GAIA_BOT_API_KEY
    BOT_SESSION_TOKEN_EXPIRY_MINUTES: int = 15

    @computed_field  # type: ignore[prop-decorator]  # pydantic’s computed_field over @property trips mypy’s prop-decorator check
    @property
    def SLACK_OAUTH_REDIRECT_URI(self) -> str:
        """Slack OAuth callback URL using redirectmeto proxy for local development."""
        return "https://redirectmeto.com/http://localhost:8000/api/v1/platform-auth/slack/callback"

    model_config = SettingsConfigDict(
        env_file_encoding="utf-8",
        extra="allow",
    )


_infisical_secrets_loaded = False


def _ensure_infisical_loaded() -> None:
    """Ensure Infisical secrets are loaded exactly once."""
    global _infisical_secrets_loaded
    if not _infisical_secrets_loaded:
        infisical_start = time.time()
        inject_infisical_secrets()
        log.info(
            f"{LogTag.STARTUP} Infisical secrets loaded",
            duration_seconds=round(time.time() - infisical_start, 3),
        )
        _infisical_secrets_loaded = True


@lru_cache(maxsize=1)
def get_settings() -> Any:  # noqa: ANN401 -- framework contract
    """Return the cached settings instance for the current environment.

    The return stays Any: narrowing to CommonSettings produced 129 mypy errors
    plus 4 more from from_env(**kwargs) — fixing that is a settings-model
    redesign, not a typing fix.
    """
    log.info(f"{LogTag.STARTUP} Starting settings initialization...")

    _ensure_infisical_loaded()

    env = os.getenv("ENV", "production")

    try:
        # Initialize settings based on environment
        settings_obj: ProductionSettings | DevelopmentSettings
        if env == "development":
            settings_obj = DevelopmentSettings.from_env()
        else:
            # Hard block, not a warning — checked via os.getenv because
            # from_env() downgrades pydantic validation errors to warnings.
            if os.getenv("DEV_AUTH_BYPASS_EMAIL"):
                raise RuntimeError(
                    "DEV_AUTH_BYPASS_EMAIL is set but ENV=production — "
                    "the dev auth bypass must never be enabled in production."
                )
            if os.getenv("DEV_UNLIMITED_RATE_LIMITS", "").strip().lower() not in (
                "",
                "0",
                "false",
                "no",
                "off",
            ):
                raise RuntimeError(
                    "DEV_UNLIMITED_RATE_LIMITS is set but ENV=production — "
                    "lifting rate limits in production is never allowed."
                )
            # Same policy as the auth bypass: OPENROUTER_BASE_URL redirects the
            # model to a local scripted stub, which must never run in production.
            if os.getenv("OPENROUTER_BASE_URL"):
                raise RuntimeError(
                    "OPENROUTER_BASE_URL is set but ENV=production — "
                    "the OpenRouter base-URL override is a development-only stub hook."
                )
            # Boolean-semantic var: an explicit "false"/"0"/"no"/"off" is a
            # legitimate way to DISABLE sim mode and must not trip the guard
            # (unlike the string-valued overrides above, where set == enabled).
            if os.getenv("GAIA_SIM_MODE", "").strip().lower() not in (
                "",
                "0",
                "false",
                "no",
                "off",
            ):
                raise RuntimeError(
                    "GAIA_SIM_MODE is set but ENV=production — "
                    "sim mode routes every model call to a local scripted stub."
                )
            settings_obj = ProductionSettings.from_env()
            log.info(f"{LogTag.STARTUP} Production settings initialized")

        # Validate settings after full initialization
        settings_validator.configure(
            settings_obj.SHOW_MISSING_KEY_WARNINGS,
            is_production=settings_obj.ENV == "production",
        )

        settings_validator.validate_settings(settings_obj)
        if settings_obj.SHOW_MISSING_KEY_WARNINGS:
            settings_validator.log_validation_results()

        return settings_obj

    except Exception as e:
        log.error(
            f"{LogTag.STARTUP} Error initializing settings",
            error=str(e),
            error_type=type(e).__name__,
        )
        # In case of error, we still need to return a settings object
        # Use development settings with defaults as fallback
        if env == "development":
            return DevelopmentSettings.from_env(SHOW_MISSING_KEY_WARNINGS=True)
        log.critical(f"{LogTag.STARTUP} Critical error initializing production settings!")
        raise


settings = get_settings()
