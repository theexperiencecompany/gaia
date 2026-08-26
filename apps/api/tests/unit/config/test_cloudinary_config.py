"""Unit tests for the Cloudinary global-context configuration.

``init_cloudinary`` is a sync lazy loader that resolves its API key through
the credential service's runtime snapshot (store → env) — the same contract
as the LLM lanes' loaders. Cloud name + secret have no stored representation
and always come from env; all three are required.
"""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.config.cloudinary import init_cloudinary

MOD = "app.config.cloudinary"


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
    def test_env_only_configures_from_settings(self):
        config_mock = MagicMock()
        with (
            patch(f"{MOD}.resolved_config", return_value=None),
            patch(f"{MOD}.settings") as mock_settings,
            patch(f"{MOD}.cloudinary.config", config_mock),
        ):
            _patch_env(mock_settings)
            init_cloudinary().loader_func()

        assert config_mock.call_args.kwargs["cloud_name"] == "env-cloud"
        assert config_mock.call_args.kwargs["api_key"] == "env-key"

    def test_stored_api_key_wins_over_env(self):
        config_mock = MagicMock()
        with (
            patch(f"{MOD}.resolved_config", return_value=_stored("stored-key")),
            patch(f"{MOD}.settings") as mock_settings,
            patch(f"{MOD}.cloudinary.config", config_mock),
        ):
            _patch_env(mock_settings)
            init_cloudinary().loader_func()

        assert config_mock.call_args.kwargs["api_key"] == "stored-key"

    @pytest.mark.parametrize("missing", ["CLOUDINARY_CLOUD_NAME", "CLOUDINARY_API_SECRET"])
    def test_partial_configuration_fails_loud_and_configures_nothing(self, missing: str):
        """A stored API key alone cannot drive the SDK; without cloud name or
        secret the loader raises (the WARN strategy degrades loudly) rather
        than configuring the global client with holes."""
        config_mock = MagicMock()
        with (
            patch(f"{MOD}.resolved_config", return_value=_stored("stored-key")),
            patch(f"{MOD}.settings") as mock_settings,
            patch(f"{MOD}.cloudinary.config", config_mock),
        ):
            _patch_env(mock_settings, **{missing: None})
            with pytest.raises(RuntimeError, match="not fully configured"):
                init_cloudinary().loader_func()
        config_mock.assert_not_called()
