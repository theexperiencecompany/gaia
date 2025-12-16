"""Application settings: load from env, validate, and expose typed access.

Flow
- `.env` loaded first, then external secrets via `inject_infisical_secrets()`.
- Pick settings class by `ENV` (production/development).
- Pydantic builds the object; `settings_validator` logs missing groups.
- `get_settings()` memoizes the instance for fast imports.

Add env vars
1) Add fields to `CommonSettings`/`ProductionSettings`/`DevelopmentSettings`.
2) Use Optional[...] in dev if it’s not required there.
3) If you want warnings, register a group in `config/settings_validator.py`.
4) Read values via `from app.config.settings import settings`.
"""

import os
import time
from functools import lru_cache
from typing import Literal, Optional

from app.config.loggers import app_logger as logger
from app.config.secrets import inject_infisical_secrets
from app.config.settings_validator import settings_validator
from dotenv import load_dotenv
from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

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
    def from_env(cls, **kwargs):
        """Create settings from environment variables."""
        try:
            return cls(**kwargs)
        except Exception as e:
            logger.warning(f"Error creating settings: {str(e)}")
            # Create a minimal instance with empty strings for required fields
            fields = cls.model_fields
            defaults = {
                field_name: ""
                for field_name in fields
                if field_name not in kwargs
                and "str" in str(fields[field_name].annotation)
            }
            return cls(**defaults, **kwargs)


class CommonSettings(BaseAppSettings):
    """Common settings required for all environments."""

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

    # ----------------------------------------------
    # Profiling & Performance Monitoring
    # ----------------------------------------------
    ENABLE_PROFILING: bool = False  # Must be explicitly enabled via .env
    PROFILING_SAMPLE_RATE: float = 1.0  # 100% of requests by default

    # ----------------------------------------------
    # Computed Properties
    # ----------------------------------------------

    # OAuth Callback URLs
    @computed_field  # type: ignore
    @property
    def WORKOS_REDIRECT_URI(self) -> str:
        """WorkOS OAuth callback URL."""
        return f"{self.HOST}/api/v1/oauth/workos/callback"

    @computed_field  # type: ignore
    @property
    def WORKOS_DESKTOP_REDIRECT_URI(self) -> str:
        """WorkOS OAuth callback URL for desktop app."""
        return f"{self.HOST}/api/v1/oauth/workos/desktop/callback"

    @computed_field  # type: ignore
    @property
    def COMPOSIO_REDIRECT_URI(self) -> str:
        """Composio OAuth callback URL."""
        return f"{self.HOST}/api/v1/oauth/composio/callback"

    @computed_field  # type: ignore
    @property
    def GOOGLE_CALLBACK_URL(self) -> str:
        """Google OAuth callback URL."""
        return f"{self.HOST}/api/v1/oauth/google/callback"

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
    GOOGLE_CLIENT_ID: str
    GOOGLE_CLIENT_SECRET: str
    GOOGLE_USERINFO_URL: str = "https://www.googleapis.com/oauth2/v2/userinfo"
    GOOGLE_TOKEN_URL: str = "https://oauth2.googleapis.com/token"

    # ----------------------------------------------
    # External API Integration Keys
    # ----------------------------------------------
    TAVILY_API_KEY: str
    LLAMA_INDEX_KEY: str

    # AI & Machine Learning
    OPENAI_API_KEY: str
    GOOGLE_API_KEY: str

    # Media & Content Processing
    ASSEMBLYAI_API_KEY: str

    # Weather Services
    OPENWEATHER_API_KEY: str

    # Email & Communication
    RESEND_API_KEY: str
    RESEND_AUDIENCE_ID: str

    # Media Storage
    CLOUDINARY_CLOUD_NAME: str
    CLOUDINARY_API_KEY: str
    CLOUDINARY_API_SECRET: str

    # External Service Integration
    COMPOSIO_KEY: str
    FIRECRAWL_API_KEY: str

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

    # ----------------------------------------------
    # Webhook Secrets & Security
    # ----------------------------------------------
    COMPOSIO_WEBHOOK_SECRET: str
    DODO_WEBHOOK_PAYMENTS_SECRET: str = ""

    # ----------------------------------------------
    # Content Management
    # ----------------------------------------------
    BLOG_BEARER_TOKEN: str  # Bearer token for blog management operations

    # ----------------------------------------------
    # Memory & Storage Configuration
    # ----------------------------------------------
    MEM0_API_KEY: str
    MEM0_ORG_ID: str
    MEM0_PROJECT_ID: str

    # ----------------------------------------------
    # Code Execution Environment
    # ----------------------------------------------
    E2B_API_KEY: str

    # ----------------------------------------------
    # Payment Processing
    # ----------------------------------------------
    DODO_PAYMENTS_API_KEY: str

    # ----------------------------------------------
    # Monitoring & Analytics
    # ----------------------------------------------
    SENTRY_DSN: str
    POSTHOG_API_KEY: str
    OPIK_API_KEY: str
    OPIK_WORKSPACE: str

    model_config = SettingsConfigDict(
        env_file_encoding="utf-8",
        extra="allow",
    )


class DevelopmentSettings(CommonSettings):
    """Looser settings for development environment with defaults."""

    # ----------------------------------------------
    # Database & Message Queue Connections
    # ----------------------------------------------
    CHROMADB_HOST: Optional[str] = None
    CHROMADB_PORT: Optional[int] = None
    POSTGRES_URL: Optional[str] = None
    RABBITMQ_URL: Optional[str] = None

    # ----------------------------------------------
    # Authentication & OAuth
    # ----------------------------------------------
    GOOGLE_CLIENT_ID: Optional[str] = None
    GOOGLE_CLIENT_SECRET: Optional[str] = None
    ENABLE_PUBSUB_JWT_VERIFICATION: bool = False
    GOOGLE_USERINFO_URL: str = "https://www.googleapis.com/oauth2/v2/userinfo"
    GOOGLE_TOKEN_URL: str = "https://oauth2.googleapis.com/token"

    # ----------------------------------------------
    # External API Integration Keys
    # ----------------------------------------------
    # Search & Data Services
    TAVILY_API_KEY: Optional[str] = None
    LLAMA_INDEX_KEY: Optional[str] = None

    # AI & Machine Learning
    OPENAI_API_KEY: Optional[str] = None
    GOOGLE_API_KEY: Optional[str] = None

    # Media & Content Processing
    ASSEMBLYAI_API_KEY: Optional[str] = None

    # Weather Services
    OPENWEATHER_API_KEY: Optional[str] = None

    # Email & Communication
    RESEND_API_KEY: Optional[str] = None
    RESEND_AUDIENCE_ID: Optional[str] = None

    # Media Storage
    CLOUDINARY_CLOUD_NAME: Optional[str] = None
    CLOUDINARY_API_KEY: Optional[str] = None
    CLOUDINARY_API_SECRET: Optional[str] = None

    # External Service Integration
    COMPOSIO_KEY: Optional[str] = None
    FIRECRAWL_API_KEY: Optional[str] = None

    # ----------------------------------------------
    # Webhook Secrets & Security
    # ----------------------------------------------
    COMPOSIO_WEBHOOK_SECRET: Optional[str] = None
    DODO_WEBHOOK_PAYMENTS_SECRET: Optional[str] = None

    # Voice Agent Configuration
    LIVEKIT_URL: Optional[str] = None
    LIVEKIT_API_KEY: Optional[str] = None
    LIVEKIT_API_SECRET: Optional[str] = None
    AGENT_SECRET: Optional[str] = None
    DEEPGRAM_API_KEY: Optional[str] = None
    ELEVENLABS_API_KEY: Optional[str] = None
    ELEVENLABS_TTS_MODEL: Optional[str] = None
    GAIA_BACKEND_URL: Optional[str] = "http://host.docker.internal:8000"
    ELEVENLABS_VOICE_ID: Optional[str] = None

    # ----------------------------------------------
    # Content Management
    # ----------------------------------------------
    BLOG_BEARER_TOKEN: Optional[str] = (
        None  # Bearer token for blog management operations
    )

    # ----------------------------------------------
    # Memory & Storage Configuration
    # ----------------------------------------------
    MEM0_API_KEY: Optional[str] = None
    MEM0_ORG_ID: Optional[str] = None
    MEM0_PROJECT_ID: Optional[str] = None

    # ----------------------------------------------
    # Code Execution Environment
    # ----------------------------------------------
    E2B_API_KEY: Optional[str] = None

    # ----------------------------------------------
    # Payment Processing
    # ----------------------------------------------
    DODO_PAYMENTS_API_KEY: Optional[str] = None

    # ----------------------------------------------
    # Monitoring & Analytics
    # ----------------------------------------------
    SENTRY_DSN: Optional[str] = None
    POSTHOG_API_KEY: Optional[str] = None
    OPIK_API_KEY: Optional[str] = None
    OPIK_WORKSPACE: Optional[str] = None

    # ----------------------------------------------
    # Environment Configuration
    # ----------------------------------------------
    ENV: Literal["production", "development"] = "development"

    # Default to show warnings in development environment
    SHOW_MISSING_KEY_WARNINGS: bool = True

    model_config = SettingsConfigDict(
        env_file_encoding="utf-8",
        extra="allow",
    )


_infisical_secrets_loaded = False


def _ensure_infisical_loaded():
    """Ensure Infisical secrets are loaded exactly once."""
    global _infisical_secrets_loaded
    if not _infisical_secrets_loaded:
        infisical_start = time.time()
        inject_infisical_secrets()
        logger.info(
            f"Infisical secrets loaded in {(time.time() - infisical_start):.3f}s"
        )
        _infisical_secrets_loaded = True


@lru_cache(maxsize=1)
def get_settings():
    """
    Get cached settings instance based on environment.

    This function uses LRU cache to ensure settings are instantiated only once,
    avoiding expensive Pydantic validation on every import.
    """
    logger.info("Starting settings initialization...")

    _ensure_infisical_loaded()

    env = os.getenv("ENV", "production")

    try:
        # Initialize settings based on environment
        if env == "development":
            settings_obj = DevelopmentSettings.from_env()
        else:
            settings_obj = ProductionSettings.from_env()
            logger.info("Production settings initialized")

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
        logger.error(f"Error initializing settings: {str(e)}")
        # In case of error, we still need to return a settings object
        # Use development settings with defaults as fallback
        if env == "development":
            return DevelopmentSettings.from_env(SHOW_MISSING_KEY_WARNINGS=True)
        else:
            logger.critical("Critical error initializing production settings!")
            raise


settings = get_settings()
