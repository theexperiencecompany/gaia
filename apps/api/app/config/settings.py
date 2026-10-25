"""Application settings: one class, validated against the deployment's capabilities.

.env loads first, then Infisical secrets; Settings reads ENV and the rest, and
refuses to boot a real deployment missing a key its profile needs. Add a field
as optional here, and if a capability needs it, add it to
app/config/capability_requirements.py.
"""

from functools import lru_cache
import time
from typing import Literal, Self, TypedDict, cast

from dotenv import load_dotenv
from pydantic import Field, ValidationInfo, computed_field, field_validator, model_validator
from pydantic_settings import SettingsConfigDict

from app.config.browser_host_settings import BrowserHostSettings
from app.config.capability_requirements import required_keys
from app.config.deployment import (
    BlobStoreKind,
    DeploymentKind,
    DeploymentProfile,
    deployment_profile,
)
from app.config.secrets import inject_infisical_secrets
from app.config.settings_validator import settings_validator
from app.constants.bot import GAIA_CLOUD_TELEGRAM_BOT_USERNAME
from app.constants.browser import BrowserAgentEffort
from app.constants.execute import SANDBOX_EXECUTE_TOKEN_SECRET_MIN_CHARS
from app.constants.files import S3AddressingStyle
from app.constants.llm import DevLLMApi
from app.constants.log_tags import LogTag
from app.constants.search import (
    CRAWL4AI_DEFAULT_MAX_BROWSERS,
    CRAWL4AI_MIN_MAX_BROWSERS,
)
from shared.py.wide_events import log

load_dotenv()


class _DeploymentSelection(TypedDict, total=False):
    """The fields validators read off pydantic's plain field-name-to-value mapping."""

    ENV: str
    AUTH_MODE: str


class Settings(BrowserHostSettings):
    """The one settings class: optional integrations, required by the capability table.

    What a deployment must set follows its profile (app/config/capability_requirements.py);
    a real deployment refuses to boot without it, development only warns.
    """

    SHOW_MISSING_KEY_WARNINGS: bool = True

    # Authentication & OAuth: workos (default, hosted/dev) or local (self-host
    # email+password sessions; the default under ENV=selfhost).
    AUTH_MODE: Literal["workos", "local"] = "workos"

    # Dev-only overrides; production code reads them (app/agents/llm/client.py
    # evaluates GAIA_SIM_MODE at import time), and a real deployment refuses to boot with one set.
    GAIA_SIM_MODE: bool = False  # every LLM factory resolves to the local scripted stub
    # Where the scripted stub lives when sim mode is on; consumed only by
    # _sim_llm (defaults to SIM_STUB_BASE_URL when unset).
    OPENROUTER_BASE_URL: str | None = None
    # Every request authenticates as this Mongo user with no WorkOS session.
    DEV_AUTH_BYPASS_EMAIL: str | None = None
    # Comma-separated OpenRouter provider slugs to PREFER for the default-model
    # lane — fallbacks stay enabled. Set from the per-provider cache-hit table;
    # see _provider_order_kwargs in agents/llm/client.py.
    OPENROUTER_PROVIDER_ORDER: str | None = None
    # Dev-only: lift every per-user rate limit. Eval harnesses drive thousands
    # of requests/day against a free-plan dev user, which 429s at 200/day
    # otherwise. get_settings() refuses production boot when set.
    DEV_UNLIMITED_RATE_LIMITS: bool = False
    # Self-host opt-in for the local Docker-exec coding sandbox. Set only by the
    # docker-compose.sandbox.yml override (`gaia up --code-sandbox`), which is
    # also what mounts the Docker socket it needs.
    LOCAL_CODE_SANDBOX: bool = False
    # Where files live; unset is the deployment's default (see deployment_profile).
    BLOB_STORE: BlobStoreKind | None = None
    # Where blobs live under BLOB_STORE=local; the self-host compose mounts the
    # gaia-selfhost_files volume here.
    LOCAL_FILE_STORAGE_PATH: str = "/var/lib/gaia/files"
    # The bucket under BLOB_STORE=s3; on Railway, reference the bucket's
    # ENDPOINT, BUCKET, ACCESS_KEY_ID, SECRET_ACCESS_KEY and REGION variables.
    S3_ENDPOINT_URL: str | None = None
    S3_BUCKET: str | None = None
    S3_ACCESS_KEY_ID: str | None = None
    S3_SECRET_ACCESS_KEY: str | None = None
    # Unset signs requests for us-east-1, which MinIO and most S3-compatible services accept.
    S3_REGION: str | None = None
    S3_ADDRESSING_STYLE: S3AddressingStyle = S3AddressingStyle.VIRTUAL
    # The bots' HMAC key for hashed platform ids in logs; the same value here
    # makes the API's user_hash join the bots'. Unset falls back like the bots.
    BOT_LOG_HASH_SECRET: str | None = None

    # ----------------------------------------------
    # Database Connections
    # ----------------------------------------------
    MONGO_DB: str
    REDIS_URL: str

    # WorkOS credentials only required in workos mode (see the AUTH_MODE
    # validator on the base).
    WORKOS_API_KEY: str | None = None
    WORKOS_CLIENT_ID: str | None = None
    WORKOS_COOKIE_PASSWORD: str | None = None

    @field_validator("WORKOS_API_KEY", "WORKOS_CLIENT_ID", "WORKOS_COOKIE_PASSWORD")
    @classmethod
    def _require_workos_credentials_when_selected(
        cls, v: str | None, info: ValidationInfo
    ) -> str | None:
        selection: _DeploymentSelection = cast(_DeploymentSelection, info.data)
        if selection.get("AUTH_MODE") == "workos" and not v:
            raise ValueError(f"{info.field_name} is required when AUTH_MODE=workos")
        return v

    # Instance-wide secret. Env wins; otherwise generated once and persisted in
    # Mongo by the secrets store (survives container recreation). Signs local
    # sessions and derives Fernet keys for stored provider credentials.
    INSTANCE_SECRET: str | None = None

    # Ollama endpoint as seen from THIS process; unset means no Ollama lane.
    # Inside Docker the host is http://host.docker.internal:11434.
    OLLAMA_BASE_URL: str | None = None

    # Hostname that reaches the machine GAIA runs on from inside its container
    # (host.docker.internal under the self-host compose). When set, a custom MCP
    # server added as localhost/127.0.0.1 is dialed through it instead.
    LOOPBACK_HOST_ALIAS: str | None = None

    # ----------------------------------------------
    # Environment & Deployment
    # ----------------------------------------------
    HOST: str = "https://api.heygaia.io"
    FRONTEND_URL: str = "https://heygaia.io"
    DUMMY_IP: str = "8.8.8.8"
    WORKER_TYPE: str = "unknown"
    ENABLE_LAZY_LOADING: bool = True
    # Code mode — bash-injected `gaia.execute` client letting sandbox scripts
    # call GAIA tools back server-side. On by default; off mints no token
    # (bash itself still runs; scripts just get no GAIA_EXECUTE_* env).
    ENABLE_CODE_MODE: bool = True
    # Inline each integration tool's return shape in the retrieve_tools doc so a
    # script can be written without a get_tool_schema call. App-wide, not per user.
    # Off by default: discovery docs carry args only and never read the observed-shape store.
    ENABLE_INLINE_TOOL_RETURNS: bool = False
    # Executor-free HIL ledger — gated calls register PENDING and return
    # instead of parking the run on an interrupt. On by default; off keeps the
    # interrupt-and-resume barrier.
    ENABLE_HIL_LEDGER: bool = True
    # JEV choice judge for auto mode — a structured decision call classifies first
    # (49/50 on the calibration set, zero dangerous accepts), LLM intent judge as
    # the transport-failure fallback. On by default; a JEV outage never opens the gate.
    ENABLE_HIL_JEV_JUDGE: bool = True
    # JEV reply classifier for bot users' chat answers to pending approvals —
    # one structured decision call per reply (hil-reply calibration: 0 dangerous
    # approves vs the LLM's 2), LLM classifier as the transport-failure fallback.
    ENABLE_HIL_JEV_REPLY: bool = True
    # Private agent lab — Claude Code / OpenCode CLIs inside the
    # per-user E2B sandbox, controllable from chat. Off by default; PostHog
    # targeting enables it for specific users.
    ENABLE_AGENT_LAB: bool = False

    @field_validator("HOST", "FRONTEND_URL", mode="after")
    @classmethod
    def _strip_trailing_slash(cls, v: str) -> str:
        return v.rstrip("/") if isinstance(v, str) else v

    @property
    def deployment(self) -> DeploymentProfile:
        """Return the instance's capabilities; every deployment difference reads from here."""
        return deployment_profile(
            DeploymentKind(self.ENV),
            self.AUTH_MODE,
            unlimited_usage=self.DEV_UNLIMITED_RATE_LIMITS,
            local_code_sandbox=self.LOCAL_CODE_SANDBOX,
            blob_store=self.BLOB_STORE,
        )

    @property
    def telegram_bot_username(self) -> str | None:
        """Return this instance's Telegram bot, GAIA Cloud's own when the deployment runs on it."""
        if self.TELEGRAM_BOT_USERNAME:
            return self.TELEGRAM_BOT_USERNAME
        return GAIA_CLOUD_TELEGRAM_BOT_USERNAME if self.deployment.hosted_bots else None

    # Outbound Email. EMAIL_PROVIDER keys the registry in
    # app/services/email/providers.
    EMAIL_PROVIDER: str = "resend"

    # Optional coupon surfaced alongside the checkout link in every 402
    # "subscription required" response. Unset means no code is advertised.
    PAYWALL_DISCOUNT_CODE: str | None = None
    # Coupon the founder's letter offers. Unset means the letter carries no offer.
    FOUNDER_LETTER_DISCOUNT_CODE: str | None = None

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

    # --- Browser-Use (autonomous browser automation) ---
    # Always on in every environment; an unreachable host fails loudly at task time.

    # Cloudflare R2, the fast edge store for browser step screenshots; Cloudinary
    # stays the durable store for arbitrary user files. Optional: any unset field
    # falls back to inline data URLs. Use a custom domain in prod, r2.dev is rate-limited.
    CLOUDFLARE_ACCOUNT_ID: str | None = None
    R2_ACCESS_KEY_ID: str | None = None
    R2_SECRET_ACCESS_KEY: str | None = None
    R2_PUBLIC_BASE_URL: str | None = None
    # Jev "System One" decision policy (TypeSafe AI): each step's decision is a
    # single Jev evaluation over the page's indexed element table, not a
    # generative chat completion. Screenshots are never sent to Jev.
    BROWSER_USE_JEV_MODEL: str = "~typesafe/jev-latest"
    # Which gateway serves Jev decisions: "openrouter" (default) or "vercel"
    # (Vercel AI Gateway). Hot-swappable at boot: both speak the same
    # {model, state, questions} decisions shape.
    BROWSER_JEV_PROVIDER: Literal["openrouter", "vercel"] = "openrouter"
    # Vercel AI Gateway key + model, read only when BROWSER_JEV_PROVIDER=vercel.
    BROWSER_JEV_VERCEL_API_KEY: str | None = None
    BROWSER_JEV_VERCEL_MODEL: str = "typesafe-ai/jev"
    # Text helper for the loop, called only when a decision needs a typed value.
    # deepseek-v4-flash answers a URL/value prompt in ~1.5-5s with minimal
    # reasoning (measured 2026-09-22); forcing reasoning off made it return null.
    BROWSER_USE_JEV_TEXT_MODEL: str = "deepseek/deepseek-v4-flash-0731"
    # The browser agent's model, the same for every user whatever their chat lane: it
    # steers and signs off while Jev does the stepping. Served by OpenRouter.
    BROWSER_AGENT_MODEL: str = "deepseek/deepseek-v4-flash-0731"
    BROWSER_AGENT_REASONING_EFFORT: BrowserAgentEffort = "low"
    # Browser-Use's flash mode: the agent writes only its memory and actions, no thinking.
    BROWSER_AGENT_FLASH_MODE: bool = True

    # Hard limits — everything is bounded so no browser task can run away. The
    # agent's step count is only Browser-Use's required backstop: a run ends on
    # the agent's finish or its time and cost budgets.
    BROWSER_USE_MAX_STEPS: int = 100
    BROWSER_USE_MAX_ACTIONS_PER_STEP: int = 5
    BROWSER_USE_TASK_TIMEOUT_SECONDS: int = 600
    # How long a paused run waits for the user's handoff step (a login, a CAPTCHA).
    # The one source: the job deadline, its TTLs and the relay's wait all derive
    # from it (job_lifetime.py); resolving sooner resumes at once.
    BROWSER_USE_HANDOFF_TIMEOUT_SECONDS: int = 600
    # Active work budget for a single step. A handoff waits after its step ends,
    # outside this budget, so a step is never killed while the user completes one.
    BROWSER_USE_STEP_TIMEOUT_SECONDS: int = 180
    # Stream per-step screenshots into the chat card / bot messages.
    BROWSER_USE_STREAM_SCREENSHOTS: bool = True

    # There is no automatic CAPTCHA solver: when set, the agent gets an action to
    # hand a CAPTCHA to the user, who solves it in live-view before it continues.
    BROWSER_USE_SOLVE_CAPTCHA: bool = True

    # --- Browser host (gaia-browser-host, our own low-RAM Chromium host) ---

    # One long-lived Chromium, one isolated context per session, proxied over
    # CDP with an authenticated screencast live view. Reached internally by
    # service name; override locally to http://localhost:8930.

    # The Chromium host when BROWSER_HOST_URL runs Obscura: every default user's run
    # opens here and Obscura runs fall back here. It runs BROWSER_ENGINE=chromium with
    # its OWN address as BROWSER_HOST_URL, since a host builds its CDP/live URLs from it.
    BROWSER_FALLBACK_HOST_URL: str | None = None

    # Fernet key (32 url-safe base64 bytes) encrypting each user's saved browser
    # login (storage_state) at rest in Mongo. Infisical-provided in production;
    # persistence fails loud if a save/load is attempted while it's unset.
    BROWSER_STATE_ENCRYPTION_KEY: str | None = None
    # HMAC secret (>=32 chars) for the short-lived live-view takeover JWT handed
    # to a user's own bot channel so they can take over a handoff without a web login.
    BROWSER_TAKEOVER_TOKEN_SECRET: str | None = None
    # When false, a session's login is never persisted or restored (per-deployment
    # opt-out of "log in once, reuse next time").
    BROWSER_PERSIST_LOGINS: bool = True
    # Public base URL for the recap and step-screenshot links a user is sent, e.g.
    # https://browser.heygaia.io where a vhost reverse-proxies to this api service.
    # When unset, those links fall back to HOST.
    BROWSER_LIVE_VIEW_BASE_URL: str | None = None

    # Custom OpenRouter/OpenAI-compatible endpoint for cheap bulk dev/test usage.
    # All three must be set; the "custom" provider is registered exclusively in
    # development (see register_llm_providers), so these have no effect in production.
    DEV_LLM_BASE_URL: str | None = None
    DEV_LLM_API_KEY: str | None = None
    DEV_LLM_MODEL: str | None = None
    # Which API the endpoint is called through. OpenAI's reasoning models need
    # "responses": their chat completions reject function tools with reasoning on.
    DEV_LLM_API: DevLLMApi = DevLLMApi.CHAT_COMPLETIONS
    # Default model for every dev request that doesn't pick one in the chat-header
    # selector — any DEV_MODEL_OPTIONS key from app/constants/llm.py ("custom" =
    # the endpoint above). An explicit selector choice still wins.
    DEV_DEFAULT_MODEL: str | None = None
    # Integration id -> auth config id, as JSON, for a Composio project other than
    # production's, whose auth config ids the integration catalog hardcodes.
    COMPOSIO_AUTH_CONFIG_OVERRIDES: dict[str, str] = Field(default_factory=dict)

    # Deletes a workflow conversation's LangGraph checkpoint threads before every
    # run, so run N stops replaying runs 1..N-1 (one production workflow held
    # 1.39 MB across three threads). Kill switch: set false to disable without a deploy.
    WORKFLOW_THREAD_RESET_ENABLED: bool = True

    # Optional GitHub token (no scopes needed): 5,000 API requests/hour vs
    # 60/hour without, for discovering and installing skills from GitHub.
    GITHUB_TOKEN: str | None = None

    # Rejected rather than stripped because the e2b SDK reads os.environ verbatim —
    # "" there silently falls back to the US cluster, padding yields a broken URL.
    @field_validator("E2B_DOMAIN", mode="after")
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
        """Slack OAuth callback URL; development goes through the redirectmeto proxy to localhost."""
        if self.deployment.dev_tools:
            return (
                "https://redirectmeto.com/http://localhost:8000/api/v1/platform-auth/slack/callback"
            )
        return f"{self.HOST}/api/v1/platform-auth/slack/callback"

    # Code mode (sandbox scripts calling GAIA tools via /sandbox/execute).
    # Both unset = code mode ships dark: bash injects no execute token. The callback
    # URL must be reachable FROM the E2B sandbox (public API base in prod).
    SANDBOX_EXECUTE_TOKEN_SECRET: str | None = None
    SANDBOX_EXECUTE_CALLBACK_URL: str | None = None
    # Sandbox run events (hooks POSTing to /api/v1/lab/events); must be reachable
    # from the E2B sandbox, so the public API base in prod. Unset = bash
    # run_todo_id refuses to launch, since the run could never report back.
    SANDBOX_LAB_EVENTS_CALLBACK_URL: str | None = None
    # Template for users with the AGENT_LAB flag: the default one's 1GB OOM-kills
    # coding-agent CLIs. Built with build_e2b_template.py --memory-mb 8192.
    E2B_AGENT_LAB_TEMPLATE_ID: str | None = None
    # Lab sandbox lifetime, at most the E2B team's cap: a create asking more is
    # rejected (dev/staging team: 1h). Production's Pro team allows 12h (43200).
    E2B_AGENT_LAB_LIFETIME_SECONDS: int = 3600

    # Rejected at startup rather than at mint time: the token's user_id is a
    # claim nothing else binds, so a guessable secret means running any user's
    # tools. A deploy that sets a short one must not boot.
    @field_validator("SANDBOX_EXECUTE_TOKEN_SECRET", mode="after")
    @classmethod
    def _reject_weak_sandbox_execute_secret(cls, v: str | None) -> str | None:
        # A blank value is how a templated deploy (compose, Infisical, k8s) spells
        # "unset" — code mode then ships dark. Only a SHORT but present secret is
        # worth refusing to boot for; failing on "" took the whole API down once.
        if not v:
            return None
        if len(v) < SANDBOX_EXECUTE_TOKEN_SECRET_MIN_CHARS:
            raise ValueError(
                "SANDBOX_EXECUTE_TOKEN_SECRET must be at least "
                f"{SANDBOX_EXECUTE_TOKEN_SECRET_MIN_CHARS} characters"
            )
        return v

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
    GOOGLE_TOKEN_URL: str = "https://oauth2.googleapis.com/token"
    GOOGLE_CLIENT_ID: str | None = None
    GOOGLE_CLIENT_SECRET: str | None = None

    # ----------------------------------------------
    # External API Integration Keys
    # ----------------------------------------------
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
    # Signs single-purpose file-share grants (fetched by Composio during tool
    # execution). Dedicated secret so share tokens are domain-separated from
    # unsubscribe links.
    SHARE_GRANT_SECRET: str | None = None

    # Media Storage
    CLOUDINARY_CLOUD_NAME: str | None = None
    CLOUDINARY_API_KEY: str | None = None
    CLOUDINARY_API_SECRET: str | None = None

    # External Service Integration
    COMPOSIO_KEY: str | None = None
    FIRECRAWL_API_KEY: str | None = None

    # Multi-provider failover, all optional. Exa is the primary free workhorse
    # (20k/mo free); SearXNG is the self-hosted unlimited floor; Brave is a budget-capped booster.
    EXA_API_KEY: str | None = None
    BRAVE_API_KEY: str | None = None
    SEARXNG_BASE_URL: str | None = None

    # Voice Agent Configuration
    LIVEKIT_URL: str | None = None
    LIVEKIT_API_KEY: str | None = None
    LIVEKIT_API_SECRET: str | None = None
    AGENT_SECRET: str | None = None
    DEEPGRAM_API_KEY: str | None = None
    ELEVENLABS_API_KEY: str | None = None
    ELEVENLABS_TTS_MODEL: str | None = None
    GAIA_BACKEND_URL: str | None = None
    ELEVENLABS_VOICE_ID: str | None = None
    # URL the SHARED voice agent uses to reach THIS backend. Unset keeps the
    # agent on its boot-time GAIA_BACKEND_URL — set in multi-backend deployments
    # (one agent, many preview APIs).
    VOICE_AGENT_BACKEND_URL: str | None = None

    # ----------------------------------------------
    # Webhook Secrets & Security
    # ----------------------------------------------
    COMPOSIO_WEBHOOK_SECRET: str | None = None
    DODO_WEBHOOK_PAYMENTS_SECRET: str | None = None

    # ----------------------------------------------
    # Content Management
    # ----------------------------------------------
    BLOG_BEARER_TOKEN: str | None = None  # Bearer token for blog management operations

    # ----------------------------------------------
    # Code Execution Environment
    # ----------------------------------------------
    E2B_API_KEY: str | None = None
    E2B_TEMPLATE_ID: str | None = None  # gaia-coder template ID (run scripts/build_e2b_template.py)
    E2B_DOMAIN: str | None = None
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
    R2_ACCOUNT_ID: str | None = None
    R2_BUCKET: str | None = None  # e.g. "gaia-workspaces"
    R2_ACCESS_KEY: str | None = None
    R2_SECRET_KEY: str | None = None
    # Templated metadata URL, {shard} substituted at mount time, e.g.
    # "rediss://:pass@jfs-meta.heygaia.io:6380/{shard}". Password is split out
    # into META_PASSWORD before reaching the sandbox (_split_meta_url in services/sandbox/lifecycle.py).
    JUICEFS_META_URL_TEMPLATE: str | None = None
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
    # The workspace a self-hosted instance's Slack bot is installed in (set by `gaia bots add slack`).
    SLACK_WORKSPACE_URL: str | None = None
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
    TELEGRAM_BOT_USERNAME: str | None = None

    # ----------------------------------------------
    # Bot Session Token Configuration
    # ----------------------------------------------
    BOT_SESSION_TOKEN_SECRET: str | None = None  # min 32 chars - DO NOT reuse GAIA_BOT_API_KEY
    BOT_SESSION_TOKEN_EXPIRY_MINUTES: int = 15

    @model_validator(mode="before")
    @classmethod
    def _selfhost_signs_in_locally_by_default(cls, data: object) -> object:
        """Default AUTH_MODE to local under ENV=selfhost; WorkOS would leave no way to sign in."""
        if not isinstance(data, dict):
            return data
        selection: _DeploymentSelection = cast(_DeploymentSelection, data)
        if selection.get("AUTH_MODE") or selection.get("ENV") != DeploymentKind.SELFHOST:
            return data
        log.info(f"{LogTag.STARTUP} AUTH_MODE unset under ENV=selfhost - defaulting to local")
        return {**data, "AUTH_MODE": "local"}

    @model_validator(mode="after")
    def _refuse_what_the_deployment_must_not_run(self) -> Self:
        """Refuse a real deployment that sets a development override, or a self-host missing a required key.

        Raises RuntimeError rather than ValueError so pydantic does not fold a
        boot refusal into a field ValidationError. Building the profile refuses
        an invalid ENV/AUTH_MODE/BLOB_STORE combination first.
        """
        profile = self.deployment
        if not profile.dev_tools:
            for name, is_set in self._development_overrides().items():
                if is_set:
                    raise RuntimeError(
                        f"{name} is set but ENV is not 'development' — "
                        "development overrides must never run in a real deployment."
                    )
        if profile.kind is DeploymentKind.PRODUCTION:
            if self.COMPOSIO_AUTH_CONFIG_OVERRIDES:
                raise RuntimeError(
                    "COMPOSIO_AUTH_CONFIG_OVERRIDES is set but ENV=production — "
                    "it points integrations at a non-production Composio project."
                )
            if self.DODO_PAYMENTS_BASE_URL and not self.DODO_PAYMENTS_BASE_URL.startswith(
                "https://"
            ):
                # A ValueError: a malformed value, reported as a field error.
                raise ValueError("DODO_PAYMENTS_BASE_URL must use https:// in production")
        if profile.requires_complete_config:
            missing = sorted(key for key in required_keys(profile) if getattr(self, key) is None)
            if missing:
                raise RuntimeError(
                    f"{', '.join(missing)} must be set for ENV={profile.kind} "
                    f"with AUTH_MODE={self.AUTH_MODE} — see app/config/capability_requirements.py."
                )
        return self

    def _development_overrides(self) -> dict[str, bool]:
        """Each development-only override and whether it is switched on."""
        return {
            "DEV_AUTH_BYPASS_EMAIL": bool(self.DEV_AUTH_BYPASS_EMAIL),
            "DEV_UNLIMITED_RATE_LIMITS": self.DEV_UNLIMITED_RATE_LIMITS,
            "OPENROUTER_BASE_URL": bool(self.OPENROUTER_BASE_URL),
            "GAIA_SIM_MODE": self.GAIA_SIM_MODE,
        }

    model_config = SettingsConfigDict(
        env_file_encoding="utf-8",
        extra="allow",
        validate_default=False,
        arbitrary_types_allowed=True,
    )


_infisical_secrets_loaded = False


def _ensure_infisical_loaded() -> None:
    """Ensure Infisical secrets are loaded exactly once."""
    global _infisical_secrets_loaded
    if _infisical_secrets_loaded:
        return
    infisical_start = time.time()
    inject_infisical_secrets()
    log.info(
        f"{LogTag.STARTUP} Infisical secrets loaded",
        duration_seconds=round(time.time() - infisical_start, 3),
    )
    _infisical_secrets_loaded = True


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached settings instance, built once from the environment."""
    log.info(f"{LogTag.STARTUP} Starting settings initialization...")
    _ensure_infisical_loaded()
    try:
        settings_obj = Settings()  # type: ignore[call-arg]  # pydantic-settings fills MONGO_DB/REDIS_URL from env; mypy sees only the init signature
    except Exception as e:
        log.error(
            f"{LogTag.STARTUP} Error initializing settings",
            error=str(e),
            error_type=type(e).__name__,
        )
        raise
    log.info(f"{LogTag.STARTUP} Settings initialized", deployment_kind=str(settings_obj.ENV))

    settings_validator.configure(settings_obj.SHOW_MISSING_KEY_WARNINGS, settings_obj.deployment)
    settings_validator.validate_settings(settings_obj)
    if settings_obj.SHOW_MISSING_KEY_WARNINGS:
        settings_validator.log_validation_results()
    return settings_obj


settings = get_settings()
