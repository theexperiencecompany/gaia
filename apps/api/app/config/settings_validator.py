"""Validate presence of env-backed settings, grouped by feature.

WARNING: This file is parsed by the GAIA CLI (packages/cli/src/lib/env-parser.ts) using regex.
Any changes to the structure of SettingsGroup or how groups are registered MUST be reflected in the CLI parser.
If you change the syntax, please update the CLI parser accordingly.

Why
- Make missing config obvious with actionable logs.

Flow
- Define fields in `app.config.settings` (Pydantic classes).
- Register related keys here as `SettingsGroup`s.
- `validate_settings()` scans the instantiated settings object and logs what’s missing.

Add env vars
1) Add fields to `CommonSettings`/`ProductionSettings`/`DevelopmentSettings`.
2) Add a `SettingsGroup` in `_register_predefined_groups()` with matching key names.
"""

from typing import Any, List, Optional, Tuple

from app.config.loggers import app_logger as logger


class SettingsGroup:
    def __init__(
        self,
        name: str,
        keys: List[str],
        description: str,
        affected_features: str,
        required_in_prod: bool = True,
        all_required: bool = True,
        docs_url: Optional[str] = None,
        alternative_group: Optional[str] = None,
    ):
        """
        Initialize a settings group.

        Args:
            name: The name of the settings group
            keys: List of configuration keys in this group
            description: Description of what this group of settings enables
            affected_features: Description of features affected if these settings are missing
            required_in_prod: Whether this group is required in production
            all_required: Whether all keys in the group are required (True) or any one is sufficient (False)
            docs_url: Optional URL to documentation for setting up this group
            alternative_group: Name of another group that can be used instead of this one (mutually exclusive)
        """
        self.name = name
        self.keys = keys
        self.description = description
        self.affected_features = affected_features
        self.required_in_prod = required_in_prod
        self.all_required = all_required
        self.docs_url = docs_url
        self.alternative_group = alternative_group


class SettingsValidator:
    def __init__(self) -> None:
        self.groups: List[SettingsGroup] = []
        self.missing_groups: List[Tuple[SettingsGroup, List[str]]] = []
        self.show_warnings: bool = True
        self.is_production: bool = True
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
                affected_features="File uploads, image storage, and support ticket attachments",
                all_required=True,
                docs_url="https://cloudinary.com/documentation/cloudinary_credentials",
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
            )
        )

        # Memory Services
        self.register_group(
            SettingsGroup(
                name="MEM0 Memory Services",
                keys=["MEM0_API_KEY", "MEM0_ORG_ID", "MEM0_PROJECT_ID"],
                description="MEM0 AI memory services",
                affected_features="Conversation memory and context preservation",
                all_required=True,
                docs_url="https://docs.mem0.ai/",
            )
        )

        # Email Services
        self.register_group(
            SettingsGroup(
                name="Resend Email Service",
                keys=["RESEND_API_KEY", "RESEND_AUDIENCE_ID"],
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
            )
        )

        # Content Management
        self.register_group(
            SettingsGroup(
                name="Blog Management",
                keys=["BLOG_BEARER_TOKEN"],
                description="Blog content management",
                affected_features="Blog creation and management",
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
            )
        )
        self.register_group(
            SettingsGroup(
                name="Posthog Analytics",
                keys=["POSTHOG_API_KEY"],
                description="Posthog analytics and event tracking",
                affected_features="User behavior analytics and event tracking",
                docs_url="https://posthog.com/docs/api",
            )
        )

    def register_group(self, group: SettingsGroup) -> None:
        """
        Register a settings group for validation.

        Args:
            group: The settings group to register
        """
        self.groups.append(group)

    def configure(self, show_warnings: bool, is_production: bool) -> None:
        """
        Configure the validator.

        Args:
            show_warnings: Whether to show warnings for missing keys
            is_production: Whether the application is running in production mode
        """
        self.show_warnings = show_warnings
        self.is_production = is_production
        self.missing_groups = []

    def validate_settings(
        self, settings_obj: Any
    ) -> List[Tuple[SettingsGroup, List[str]]]:
        """
        Validate settings against registered groups.

        Args:
            settings_obj: The settings object to validate

        Returns:
            List of tuples with missing groups and their missing keys
        """
        self.missing_groups = []

        for group in self.groups:
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

        # Log detailed warnings
        for group, missing_keys in self.missing_groups:
            # Skip if not required in production and we're in production
            if self.is_production and not group.required_in_prod:
                continue

            # Determine the message prefix based on criticality
            prefix = (
                "CRITICAL"
                if self.is_production and group.required_in_prod
                else "WARNING"
            )

            # Create the warning message
            warning_msg = (
                f"{prefix}: Missing configuration for {group.name} - "
                f"Missing keys: {', '.join(missing_keys)}"
            )

            # Add information about affected features
            if group.affected_features:
                warning_msg += f"\n  → Affected: {group.affected_features}"

            logger.warning(warning_msg)


settings_validator = SettingsValidator()
