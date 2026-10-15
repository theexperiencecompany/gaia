"""Unit tests for the Cloudinary global-context configuration.

init_cloudinary is a sync lazy loader resolving its API key through the
credential service runtime snapshot (store, then env), like the LLM lanes.
Cloud name and secret always come from env; all three are required.
"""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.config.cloudinary import CLOUDINARY_PROVIDER, init_cloudinary, require_cloudinary
from app.core.lazy_loader import providers
from app.utils.errors import AppError
from app.utils.exceptions import ProviderNotConfiguredError

MOD = "app.config.cloudinary"
SERVICE_MOD = "app.services.providers.provider_credentials_service"


def _stored(api_key: str | None) -> dict[str, str | None]:
    return {"api_key": api_key, "base_url": None, "model": None, "preset": None}


def _patch_env(settings_mock: Any, **overrides: str | None) -> None:
    values: dict[str, str | None] = {
        "CLOUDINARY_CLOUD_NAME": "env-cloud",
        "CLOUDINARY_API_KEY": "env-key",
        "CLOUDINARY_API_SECRET": "env-secret",  # pragma: allowlist secret
        **overrides,
    }
    for key, value in values.items():
        setattr(settings_mock, key, value)


class TestInitCloudinary:
    def test_env_only_configures_from_settings(self, monkeypatch: pytest.MonkeyPatch):
        """Nothing stored: the resolver itself serves the env key, with no caller fallback."""
        from app.config.settings import settings

        monkeypatch.setattr(settings, "CLOUDINARY_CLOUD_NAME", "env-cloud")
        monkeypatch.setattr(settings, "CLOUDINARY_API_KEY", "env-key")
        monkeypatch.setattr(
            settings, "CLOUDINARY_API_SECRET", "env-secret"
        )  # pragma: allowlist secret
        config_mock = MagicMock()
        with patch(f"{MOD}.cloudinary.config", config_mock):
            init_cloudinary().loader_func()

        assert config_mock.call_args.kwargs["cloud_name"] == "env-cloud"
        assert config_mock.call_args.kwargs["api_key"] == "env-key"

    def test_stored_api_key_wins_over_env(self):
        config_mock = MagicMock()
        with (
            patch(f"{MOD}.resolved_config", return_value=_stored("stored-key")),
            patch(f"{SERVICE_MOD}.settings") as mock_settings,
            patch(f"{MOD}.cloudinary.config", config_mock),
        ):
            _patch_env(mock_settings)
            init_cloudinary().loader_func()

        assert config_mock.call_args.kwargs["api_key"] == "stored-key"

    @pytest.mark.parametrize("missing", ["CLOUDINARY_CLOUD_NAME", "CLOUDINARY_API_SECRET"])
    def test_partial_configuration_fails_loud_and_configures_nothing(self, missing: str):
        """Raise on partial config; a stored key alone cannot drive the SDK."""
        config_mock = MagicMock()
        with (
            patch(f"{MOD}.resolved_config", return_value=_stored("stored-key")),
            patch(f"{SERVICE_MOD}.settings") as mock_settings,
            patch(f"{MOD}.cloudinary.config", config_mock),
        ):
            _patch_env(mock_settings, **{missing: None})
            with pytest.raises(ProviderNotConfiguredError) as refused:
                init_cloudinary().loader_func()
        config_mock.assert_not_called()
        assert refused.value.message == (
            "Cloudinary is not fully configured: cloud name, API key, and "
            "API secret are all required (a stored credential carries only "
            "the API key today; cloud name and secret come from env)"
        )


class TestRequireCloudinary:
    def test_an_unconfigured_instance_refuses_uploads_naming_the_fix(self):
        providers.reset(CLOUDINARY_PROVIDER)
        with (
            patch(f"{MOD}.resolved_config", return_value=None),
            patch(f"{SERVICE_MOD}.settings") as mock_settings,
        ):
            _patch_env(mock_settings, CLOUDINARY_CLOUD_NAME=None, CLOUDINARY_API_KEY=None)
            with pytest.raises(AppError) as refused:
                require_cloudinary()
        providers.reset(CLOUDINARY_PROVIDER)

        error = refused.value
        assert error.status_code == 503
        assert error.code == "file_storage_not_configured"
        assert error.message == (
            "File uploads are not set up on this instance. Ask the admin to add "
            "Cloudinary credentials."
        )
        assert error.why == (
            "Uploaded files are stored in Cloudinary, and no Cloudinary account is configured."
        )
        assert error.fix == (
            "Set CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY and CLOUDINARY_API_SECRET "
            "in apps/api/.env, then restart the API."
        )
