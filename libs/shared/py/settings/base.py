"""
Base settings classes for GAIA applications.

These classes provide the foundation for application-specific settings.
Each app should extend these classes with their own configuration.
"""

from typing import Literal, Self

from pydantic_settings import BaseSettings, SettingsConfigDict

from shared.py.wide_events import log


class BaseAppSettings(BaseSettings):  # type: ignore[explicit-any]
    """Base configuration settings for all GAIA applications."""

    ENV: Literal["production", "staging", "development"] = "production"
    SHOW_MISSING_KEY_WARNINGS: bool = True

    model_config = SettingsConfigDict(
        extra="allow",
        env_file_encoding="utf-8",
        validate_default=False,
    )

    @classmethod
    def from_env(cls, **kwargs: object) -> Self:
        """Create settings from environment variables with fallback handling.

        ``model_validate``, not ``cls(**kwargs)``: the generated per-field
        ``__init__`` (``ENV`` is a Literal, ``SHOW_MISSING_KEY_WARNINGS`` a bool)
        cannot accept an ``object``-typed kwargs bag, and ``Any`` is not welcome
        here — ``model_validate`` takes the bag through pydantic's own
        (untyped) validation seam, which is the runtime path either way."""
        try:
            return cls.model_validate(kwargs)
        except Exception as e:
            log.warning(f"Error creating settings: {e!s}")
            fields = cls.model_fields
            # dict[str, object], not dict[str, str]: this is a kwargs bag aimed at
            # per-field types (ENV is a Literal, SHOW_MISSING_KEY_WARNINGS a bool).
            # The annotation filter below — not the type system — is what keeps
            # only str-annotated fields in it.
            defaults: dict[str, object] = {
                field_name: ""
                for field_name in fields
                if field_name not in kwargs and "str" in str(fields[field_name].annotation)
            }
            return cls.model_validate({**defaults, **kwargs})


class CommonSettings(BaseAppSettings):  # type: ignore[explicit-any]
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
