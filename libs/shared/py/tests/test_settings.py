"""Tests for shared.py.settings — BaseAppSettings, CommonSettings, from_env factory."""

import os
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from shared.py.settings.base import BaseAppSettings, CommonSettings


# ---------------------------------------------------------------------------
# BaseAppSettings — defaults
# ---------------------------------------------------------------------------


class TestBaseAppSettingsDefaults:
    """Test default values for BaseAppSettings."""

    def test_default_env_is_production(self):
        with patch.dict(os.environ, {}, clear=True):
            settings = BaseAppSettings()
        assert settings.ENV == "production"

    def test_default_show_missing_key_warnings(self):
        with patch.dict(os.environ, {}, clear=True):
            settings = BaseAppSettings()
        assert settings.SHOW_MISSING_KEY_WARNINGS is True

    def test_env_can_be_development(self):
        with patch.dict(os.environ, {"ENV": "development"}, clear=True):
            settings = BaseAppSettings()
        assert settings.ENV == "development"

    def test_env_rejects_invalid_value(self):
        with patch.dict(os.environ, {"ENV": "staging"}, clear=True):
            with pytest.raises(ValidationError):
                BaseAppSettings()

    def test_show_missing_key_warnings_from_env(self):
        with patch.dict(os.environ, {"SHOW_MISSING_KEY_WARNINGS": "false"}, clear=True):
            settings = BaseAppSettings()
        assert settings.SHOW_MISSING_KEY_WARNINGS is False

    def test_extra_fields_allowed(self):
        with patch.dict(os.environ, {}, clear=True):
            settings = BaseAppSettings(CUSTOM_FIELD="hello")
        assert settings.CUSTOM_FIELD == "hello"  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# BaseAppSettings — from_env factory
# ---------------------------------------------------------------------------


class TestBaseAppSettingsFromEnv:
    """Test the from_env() class method fallback behavior."""

    def test_from_env_returns_instance(self):
        with patch.dict(os.environ, {}, clear=True):
            settings = BaseAppSettings.from_env()
        assert isinstance(settings, BaseAppSettings)

    def test_from_env_passes_kwargs(self):
        with patch.dict(os.environ, {}, clear=True):
            settings = BaseAppSettings.from_env(ENV="development")
        assert settings.ENV == "development"

    def test_from_env_fallback_on_validation_error(self):
        """When creation fails, from_env should try with empty-string defaults for str fields."""

        class StrictSettings(BaseAppSettings):
            REQUIRED_STR: str  # no default — will fail if not supplied

        with patch.dict(os.environ, {}, clear=True):
            # Direct construction would fail, but from_env should gracefully handle it
            settings = StrictSettings.from_env()
            assert isinstance(settings, StrictSettings)
            # The fallback fills str fields with ""
            assert settings.REQUIRED_STR == ""

    def test_from_env_kwargs_not_overridden_by_fallback(self):
        """Explicitly provided kwargs should survive the fallback logic."""

        class StrictSettings(BaseAppSettings):
            REQUIRED_STR: str

        with patch.dict(os.environ, {}, clear=True):
            settings = StrictSettings.from_env(REQUIRED_STR="provided")
            assert settings.REQUIRED_STR == "provided"


# ---------------------------------------------------------------------------
# CommonSettings — defaults
# ---------------------------------------------------------------------------


class TestCommonSettingsDefaults:
    """Test default values for CommonSettings."""

    def test_default_host(self):
        with patch.dict(os.environ, {}, clear=True):
            settings = CommonSettings()
        assert settings.HOST == "https://api.heygaia.io"

    def test_default_frontend_url(self):
        with patch.dict(os.environ, {}, clear=True):
            settings = CommonSettings()
        assert settings.FRONTEND_URL == "https://heygaia.io"

    def test_default_worker_type(self):
        with patch.dict(os.environ, {}, clear=True):
            settings = CommonSettings()
        assert settings.WORKER_TYPE == "unknown"

    def test_inherits_base_defaults(self):
        with patch.dict(os.environ, {}, clear=True):
            settings = CommonSettings()
        assert settings.ENV == "production"
        assert settings.SHOW_MISSING_KEY_WARNINGS is True

    def test_env_override(self):
        with patch.dict(os.environ, {"HOST": "http://localhost:8000", "FRONTEND_URL": "http://localhost:3000"}, clear=True):
            settings = CommonSettings()
        assert settings.HOST == "http://localhost:8000"
        assert settings.FRONTEND_URL == "http://localhost:3000"

    def test_extra_fields_allowed(self):
        with patch.dict(os.environ, {}, clear=True):
            settings = CommonSettings(SOME_EXTRA="value")
        assert settings.SOME_EXTRA == "value"  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# CommonSettings — from_env (inherited)
# ---------------------------------------------------------------------------


class TestCommonSettingsFromEnv:
    """Test from_env inherited from BaseAppSettings works on CommonSettings."""

    def test_from_env_returns_common_settings(self):
        with patch.dict(os.environ, {}, clear=True):
            settings = CommonSettings.from_env()
        assert isinstance(settings, CommonSettings)
        assert settings.HOST == "https://api.heygaia.io"

    def test_from_env_with_kwargs(self):
        with patch.dict(os.environ, {}, clear=True):
            settings = CommonSettings.from_env(WORKER_TYPE="api")
        assert settings.WORKER_TYPE == "api"


# ---------------------------------------------------------------------------
# model_config settings
# ---------------------------------------------------------------------------


class TestModelConfig:
    """Test Pydantic model_config settings."""

    def test_base_env_file_encoding(self):
        assert BaseAppSettings.model_config["env_file_encoding"] == "utf-8"

    def test_base_extra_allowed(self):
        assert BaseAppSettings.model_config["extra"] == "allow"

    def test_base_validate_default_false(self):
        assert BaseAppSettings.model_config["validate_default"] is False

    def test_common_arbitrary_types_allowed(self):
        assert CommonSettings.model_config["arbitrary_types_allowed"] is True


# ---------------------------------------------------------------------------
# Subclassing
# ---------------------------------------------------------------------------


class TestSubclassing:
    """Test that apps can extend BaseAppSettings properly."""

    def test_custom_subclass(self):
        class MyAppSettings(BaseAppSettings):
            DATABASE_URL: str = "sqlite:///test.db"
            DEBUG: bool = False

        with patch.dict(os.environ, {}, clear=True):
            settings = MyAppSettings()
        assert settings.DATABASE_URL == "sqlite:///test.db"
        assert settings.DEBUG is False
        assert settings.ENV == "production"

    def test_custom_subclass_from_env(self):
        class MyAppSettings(BaseAppSettings):
            API_KEY: str = "default"

        with patch.dict(os.environ, {"API_KEY": "from-env"}, clear=True):
            settings = MyAppSettings.from_env()
        assert settings.API_KEY == "from-env"
