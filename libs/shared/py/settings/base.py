"""
Base settings classes for GAIA applications.

These classes provide the foundation for application-specific settings.
Each app should extend these classes with their own configuration.
"""

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

from shared.py.logging import get_contextual_logger

logger = get_contextual_logger("config")


class BaseAppSettings(BaseSettings):
    """Base configuration settings for all GAIA applications."""

    ENV: Literal["production", "development"] = "production"
    SHOW_MISSING_KEY_WARNINGS: bool = True

    model_config = SettingsConfigDict(
        extra="allow",
        env_file_encoding="utf-8",
        validate_default=False,
    )

    @classmethod
    def from_env(cls, **kwargs):
        """
        Create a settings instance from environment values and provided overrides, with a fallback that fills missing string-typed fields with empty strings if direct construction fails.
        
        Parameters:
            **kwargs: Field overrides to pass to the settings constructor; values take precedence over environment.
        
        Returns:
            An instance of the settings class populated from environment and the given overrides. If initial construction fails, any string-typed fields not supplied in `kwargs` are set to the empty string before instantiation.
        """
        try:
            return cls(**kwargs)
        except Exception as e:
            logger.warning(f"Error creating settings: {str(e)}")
            fields = cls.model_fields
            defaults = {
                field_name: ""
                for field_name in fields
                if field_name not in kwargs
                and "str" in str(fields[field_name].annotation)
            }
            return cls(**defaults, **kwargs)


class CommonSettings(BaseAppSettings):
    """Common settings shared across GAIA applications."""

    HOST: str = "https://api.heygaia.io"
    FRONTEND_URL: str = "https://heygaia.io"
    WORKER_TYPE: str = "unknown"

    model_config = SettingsConfigDict(
        env_file_encoding="utf-8",
        extra="allow",
        validate_default=False,
        arbitrary_types_allowed=True,
    )


__all__ = [
    "BaseAppSettings",
    "CommonSettings",
]