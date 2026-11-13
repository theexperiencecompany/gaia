"""Validate presence of env-backed settings, grouped by feature.

Which groups a deployment requires comes from the capability table
(app/config/capability_requirements.py); scripts/dump_config_schema.py imports
both to build the CLI's config schema.
"""

from dataclasses import dataclass

from app.config.capability_requirements import required_keys, unused_keys
from app.config.deployment import DeploymentKind, DeploymentProfile, baseline_profile
from app.constants.log_tags import LogTag
from shared.py.wide_events import log


@dataclass(frozen=True, slots=True)
class SettingsGroup:
    """One group of related config keys, and what breaks without them.

    all_required False means any one key in the group suffices;
    alternative_group names a mutually exclusive group that can stand in;
    selfhost_setup False keeps a group out of the CLI's self-host setup prompts.
    """

    name: str
    keys: list[str]
    description: str
    affected_features: str
    all_required: bool = True
    docs_url: str | None = None
    alternative_group: str | None = None
    selfhost_setup: bool = True

    def required_in(self, profile: DeploymentProfile) -> bool:
        """Whether the profile's capabilities need any of this group's keys."""
        return not required_keys(profile).isdisjoint(self.keys)


class SettingsValidator:
    """Validates required settings are present for each enabled feature group."""

    def __init__(self) -> None:
        self.groups: list[SettingsGroup] = []
        self.missing_groups: list[tuple[SettingsGroup, list[str]]] = []
        self.show_warnings: bool = True
        self.profile: DeploymentProfile = baseline_profile(DeploymentKind.PRODUCTION)
        self._register_predefined_groups()

    def _register_predefined_groups(self) -> None:
        # Database connections
        self.register_group(
            SettingsGroup(
                name="MongoDB Connection",
                keys=["MONGO_DB"],
                description="MongoDB database connection",
                affected_features="All database operations, user data, and application state",
                docs_url="https://www.mongodb.com/docs/manual/reference/connection-string/",
            )
        )

        self.register_group(
            SettingsGroup(
                name="Redis Connection",
                keys=["REDIS_URL"],
                description="Redis cache and queue service",
                affected_features="Caching, rate limiting, and task scheduling",
                docs_url="https://redis.io/docs/connect/clients/",
            )
        )

        self.register_group(
            SettingsGroup(
                name="PostgreSQL Connection",
                keys=["POSTGRES_URL"],
                description="PostgreSQL database connection",
                affected_features="Relational data storage and queries",
                docs_url="https://www.postgresql.org/docs/current/libpq-connect.html#LIBPQ-CONNSTRING",
            )
        )

        self.register_group(
            SettingsGroup(
                name="ChromaDB Connection",
                keys=["CHROMADB_HOST", "CHROMADB_PORT"],
                description="ChromaDB vector database connection",
                affected_features="Vector storage and semantic search capabilities",
                all_required=True,
                docs_url="https://docs.trychroma.com/",
            )
        )

        self.register_group(
            SettingsGroup(
                name="RabbitMQ Connection",
                keys=["RABBITMQ_URL"],
                description="RabbitMQ message queue connection",
                affected_features="Asynchronous task processing and job queue",
                docs_url="https://www.rabbitmq.com/uri-spec.html",
            )
        )

        # Authentication
        self.register_group(
            SettingsGroup(
                name="WorkOS Authentication",
                keys=["WORKOS_API_KEY", "WORKOS_CLIENT_ID", "WORKOS_COOKIE_PASSWORD"],
                description="WorkOS authentication service",
                affected_features="User authentication, login, and session management",
                all_required=True,
                docs_url="https://workos.com/docs/reference/api-keys",
                selfhost_setup=False,
            )
        )

        # Media Processing
        self.register_group(
            SettingsGroup(
                name="Cloudinary Media Storage",
                keys=[
                    "CLOUDINARY_CLOUD_NAME",
                    "CLOUDINARY_API_KEY",
                    "CLOUDINARY_API_SECRET",
                ],
                description="Cloudinary media storage service",
                affected_features=(
                    "File uploads, image storage, and support ticket attachments when "
                    "BLOB_STORE is cloudinary (hosted, or a self-host that chose it)"
                ),
                all_required=True,
                docs_url="https://cloudinary.com/documentation/cloudinary_credentials",
                selfhost_setup=False,
            )
        )

        self.register_group(
            SettingsGroup(
                name="S3 Blob Storage",
                keys=["S3_ENDPOINT_URL", "S3_BUCKET", "S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY"],
                description="S3-compatible bucket (AWS S3, Cloudflare R2, Railway, Backblaze B2, MinIO)",
                affected_features=(
                    "File uploads, image storage, and support ticket attachments when "
                    "BLOB_STORE is s3"
                ),
                docs_url="https://docs.heygaia.io/self-hosting/ai-models-and-tools#file-storage",
                selfhost_setup=False,
            )
        )

        self.register_group(
            SettingsGroup(
                name="File Sharing",
                keys=["SHARE_GRANT_SECRET"],
                description="HMAC signing secret for single-purpose file-share grants",
                affected_features="File attachments fetched by Composio during tool execution",
                selfhost_setup=False,
            )
        )

        # Speech Processing
        self.register_group(
            SettingsGroup(
                name="Speech Processing",
                keys=["DEEPGRAM_API_KEY"],
                description="Speech-to-text transcription service",
                affected_features="Audio transcription and voice interaction",
                all_required=False,
                docs_url="https://deepgram.com/",
            )
        )

        # AI Services (OpenAI and Google AI are alternatives - configure at least one)
        self.register_group(
            SettingsGroup(
                name="OpenAI Integration",
                keys=["OPENAI_API_KEY"],
                description="OpenAI API integration (alternative to Google AI)",
                affected_features="AI chat, text generation, and language processing",
                docs_url="https://platform.openai.com/api-keys",
                alternative_group="Google AI",
            )
        )

        self.register_group(
            SettingsGroup(
                name="Google AI",
                keys=["GOOGLE_API_KEY"],
                description="Google AI services (alternative to OpenAI)",
                affected_features="Google AI and ML capabilities",
                docs_url="https://console.cloud.google.com/apis/credentials",
                alternative_group="OpenAI Integration",
            )
        )

        # Search Services
        self.register_group(
            SettingsGroup(
                name="Tavily Web Search",
                keys=["TAVILY_API_KEY"],
                description="Tavily AI-powered web search integration",
                affected_features="Web search capabilities, image search, news search, and content extraction",
                docs_url="https://tavily.com/#api",
            )
        )

        self.register_group(
            SettingsGroup(
                name="Firecrawl Web Scraping",
                keys=["FIRECRAWL_API_KEY"],
                description="Firecrawl web scraping and content extraction service",
                affected_features="Advanced web content extraction, URL processing, and page scraping",
                docs_url="https://www.firecrawl.dev/",
            )
        )

        self.register_group(
            SettingsGroup(
                name="Llama Index",
                keys=["LLAMA_INDEX_KEY"],
                description="Llama Index for document processing and retrieval",
                affected_features="Advanced document indexing, RAG capabilities, and structured data retrieval",
                docs_url="https://docs.llamaindex.ai/",
                selfhost_setup=False,
            )
        )

        # Email Services
        self.register_group(
            SettingsGroup(
                name="Resend Email Service",
                keys=["RESEND_API_KEY", "RESEND_AUDIENCE_ID", "EMAIL_UNSUBSCRIBE_SECRET"],
                description="Resend email delivery service",
                affected_features="Email notifications and communication",
                all_required=True,
                docs_url="https://resend.com/docs/api-reference/api-keys",
            )
        )

        # Weather Services
        self.register_group(
            SettingsGroup(
                name="Weather Service",
                keys=["OPENWEATHER_API_KEY"],
                description="OpenWeather API for weather data",
                affected_features="Weather forecasts and current conditions",
                docs_url="https://openweathermap.org/api",
                selfhost_setup=False,
            )
        )

        # External Integrations
        self.register_group(
            SettingsGroup(
                name="Composio Integration",
                keys=["COMPOSIO_KEY", "COMPOSIO_WEBHOOK_SECRET"],
                description="Composio integration service",
                affected_features="Composio platform integration and webhook processing",
                all_required=True,
                docs_url="https://docs.composio.dev/",
            )
        )

        # Code Execution
        self.register_group(
            SettingsGroup(
                name="E2B Code Execution",
                keys=["E2B_API_KEY"],
                description="E2B secure code execution environment",
                affected_features="Code execution and sandboxed environments",
                docs_url="https://e2b.dev/docs",
                selfhost_setup=False,
            )
        )

        # Browser Automation
        self.register_group(
            SettingsGroup(
                name="Browser Host",
                keys=["BROWSER_HOST_URL", "BROWSER_HOST_KEY", "BROWSER_FALLBACK_HOST_URL"],
                description="gaia-browser-host: the BROWSER_ENGINE host + the Chromium host",
                affected_features="Autonomous browser automation (the browser_task tool)",
                selfhost_setup=False,
            )
        )

        # Payment Processing
        self.register_group(
            SettingsGroup(
                name="Dodo Payments",
                keys=["DODO_PAYMENTS_API_KEY", "DODO_WEBHOOK_PAYMENTS_SECRET"],
                description="Dodo payment processing service",
                affected_features="Payment processing and subscription management",
                all_required=True,
                docs_url="https://docs.dodopayments.com/",
                selfhost_setup=False,
            )
        )

        # Content Management
        self.register_group(
            SettingsGroup(
                name="Blog Management",
                keys=["BLOG_BEARER_TOKEN"],
                description="Blog content management",
                affected_features="Blog creation and management",
                selfhost_setup=False,
            )
        )

        # Monitoring
        self.register_group(
            SettingsGroup(
                name="Sentry Monitoring",
                keys=["SENTRY_DSN"],
                description="Sentry error tracking and monitoring",
                affected_features="Error reporting and application monitoring",
                docs_url="https://docs.sentry.io/platforms/python/",
                selfhost_setup=False,
            )
        )
        self.register_group(
            SettingsGroup(
                name="Posthog Analytics",
                keys=["POSTHOG_PROJECT_TOKEN", "POSTHOG_HOST"],
                description="Posthog analytics and event tracking",
                affected_features="User behavior analytics and event tracking",
                docs_url="https://posthog.com/docs/api",
                selfhost_setup=False,
            )
        )

    def register_group(self, group: SettingsGroup) -> None:
        """
        Register a settings group for validation.

        Args:
            group: The settings group to register
        """
        self.groups.append(group)

    def configure(self, show_warnings: bool, profile: DeploymentProfile) -> None:
        """Set whether to warn and which deployment the groups are judged against."""
        self.show_warnings = show_warnings
        self.profile = profile
        self.missing_groups = []

    def validate_settings(
        # Deliberately `object`, not `CommonSettings`: the body only does
        # hasattr()/getattr() with dynamic keys; importing CommonSettings would
        # need a TYPE_CHECKING-guarded import to dodge a circular dependency (apps/api/CLAUDE.md item 9).
        self,
        settings_obj: object,
    ) -> list[tuple[SettingsGroup, list[str]]]:
        """Validate settings against registered groups."""
        self.missing_groups = []
        unused = unused_keys(self.profile)

        for group in self.groups:
            if unused.issuperset(group.keys):
                continue
            missing_keys = []

            for key in group.keys:
                # Check if the key exists and is not None
                if not hasattr(settings_obj, key) or getattr(settings_obj, key) is None:
                    missing_keys.append(key)

            # Determine if the group is considered missing based on all_required flag
            if group.all_required and missing_keys:
                # If all keys are required, any missing key means the group is missing
                self.missing_groups.append((group, missing_keys))
            elif not group.all_required and len(missing_keys) == len(group.keys):
                # If not all keys are required, all keys must be missing for the group to be missing
                self.missing_groups.append((group, missing_keys))

        return self.missing_groups

    def log_validation_results(self) -> None:
        """Log validation results with warnings for missing configuration."""
        if not self.show_warnings or not self.missing_groups:
            return

        hosted = self.profile.kind is DeploymentKind.PRODUCTION
        for group, missing_keys in self.missing_groups:
            required = group.required_in(self.profile)
            # GAIA Cloud logs only what it needs; an optional group there is noise.
            if hosted and not required:
                continue
            prefix = "CRITICAL" if hosted and required else "WARNING"

            # Create the warning message
            warning_msg = (
                f"{prefix}: Missing configuration for {group.name} - "
                f"Missing keys: {', '.join(missing_keys)}"
            )

            # Add information about affected features
            if group.affected_features:
                warning_msg += f"\n  → Affected: {group.affected_features}"

            log.warning(
                f"{LogTag.STARTUP} Missing configuration for feature group",
                severity=prefix,
                group_name=group.name,
                missing_keys=missing_keys,
                affected_features=group.affected_features,
            )


settings_validator = SettingsValidator()
