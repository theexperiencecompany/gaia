"""Tests for shared.py.secrets — inject_infisical_secrets, InfisicalConfigError."""

import os
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from shared.py.secrets import InfisicalConfigError, inject_infisical_secrets


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ALL_ENV_KEYS = [
    "INFISICAL_TOKEN",
    "INFISICAL_PROJECT_ID",
    "INFISICAL_MACHINE_IDENTITY_CLIENT_ID",
    "INFISICAL_MACHINE_IDENTITY_CLIENT_SECRET",
]

_FULL_ENV = {
    "INFISICAL_TOKEN": "tok-123",
    "INFISICAL_PROJECT_ID": "proj-abc",
    "INFISICAL_MACHINE_IDENTITY_CLIENT_ID": "cid-xyz",
    "INFISICAL_MACHINE_IDENTITY_CLIENT_SECRET": "csec-xyz",
    "ENV": "production",
}


def _env_without(key: str, env: str = "production") -> dict[str, str]:
    """Return a full env dict with one key removed."""
    d = {**_FULL_ENV, "ENV": env}
    d.pop(key, None)
    return d


# ---------------------------------------------------------------------------
# Development (non-production) — no-op on missing config
# ---------------------------------------------------------------------------


class TestInjectInfisicalSecretsDev:
    """In development, missing Infisical config should log a warning and return."""

    @patch("shared.py.secrets.logger")
    def test_missing_token_in_dev_returns_early(self, mock_logger: MagicMock):
        env = _env_without("INFISICAL_TOKEN", env="development")
        with patch.dict(os.environ, env, clear=True):
            inject_infisical_secrets()
        mock_logger.warning.assert_called_once()
        assert "INFISICAL_TOKEN" in mock_logger.warning.call_args.args[0]

    @patch("shared.py.secrets.logger")
    def test_missing_project_id_in_dev_returns_early(self, mock_logger: MagicMock):
        env = _env_without("INFISICAL_PROJECT_ID", env="development")
        with patch.dict(os.environ, env, clear=True):
            inject_infisical_secrets()
        mock_logger.warning.assert_called_once()
        assert "INFISICAL_PROJECT_ID" in mock_logger.warning.call_args.args[0]

    @patch("shared.py.secrets.logger")
    def test_missing_client_id_in_dev_returns_early(self, mock_logger: MagicMock):
        env = _env_without("INFISICAL_MACHINE_IDENTITY_CLIENT_ID", env="development")
        with patch.dict(os.environ, env, clear=True):
            inject_infisical_secrets()
        mock_logger.warning.assert_called_once()

    @patch("shared.py.secrets.logger")
    def test_missing_client_secret_in_dev_returns_early(self, mock_logger: MagicMock):
        env = _env_without("INFISICAL_MACHINE_IDENTITY_CLIENT_SECRET", env="development")
        with patch.dict(os.environ, env, clear=True):
            inject_infisical_secrets()
        mock_logger.warning.assert_called_once()

    @patch("shared.py.secrets.logger")
    def test_all_missing_in_dev_returns_on_first_missing(self, mock_logger: MagicMock):
        with patch.dict(os.environ, {"ENV": "development"}, clear=True):
            inject_infisical_secrets()
        # Should return on the very first missing key (INFISICAL_TOKEN)
        mock_logger.warning.assert_called_once()
        assert "INFISICAL_TOKEN" in mock_logger.warning.call_args.args[0]

    @patch("shared.py.secrets.logger")
    def test_default_env_is_production(self, mock_logger: MagicMock):
        """When ENV is not set at all, it defaults to 'production'."""
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(InfisicalConfigError):
                inject_infisical_secrets()


# ---------------------------------------------------------------------------
# Production — raises InfisicalConfigError on missing config
# ---------------------------------------------------------------------------


class TestInjectInfisicalSecretsProd:
    """In production, missing Infisical config should raise InfisicalConfigError."""

    @pytest.mark.parametrize("missing_key", _ALL_ENV_KEYS)
    def test_missing_key_raises(self, missing_key: str):
        env = _env_without(missing_key, env="production")
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(InfisicalConfigError) as exc_info:
                inject_infisical_secrets()
            assert missing_key in str(exc_info.value)

    def test_empty_string_treated_as_missing(self):
        env = {**_FULL_ENV, "INFISICAL_TOKEN": ""}
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(InfisicalConfigError):
                inject_infisical_secrets()


# ---------------------------------------------------------------------------
# Successful SDK interaction
# ---------------------------------------------------------------------------


class TestInjectInfisicalSecretsSuccess:
    """Test the happy path: all config present, SDK called, secrets injected."""

    @patch("shared.py.secrets.logger")
    def test_secrets_injected_into_environ(self, mock_logger: MagicMock):
        mock_secret = SimpleNamespace(secretKey="MY_SECRET", secretValue="s3cret")
        mock_secrets_response = SimpleNamespace(secrets=[mock_secret])

        mock_client = MagicMock()
        mock_client.secrets.list_secrets.return_value = mock_secrets_response

        mock_sdk_class = MagicMock(return_value=mock_client)

        with patch.dict(os.environ, _FULL_ENV, clear=True):
            with patch.dict("sys.modules", {"infisical_sdk": MagicMock(InfisicalSDKClient=mock_sdk_class)}):
                inject_infisical_secrets()

            assert os.environ.get("MY_SECRET") == "s3cret"

    @patch("shared.py.secrets.logger")
    def test_local_env_takes_precedence(self, mock_logger: MagicMock):
        """Existing env vars should NOT be overwritten by Infisical."""
        mock_secret = SimpleNamespace(secretKey="EXISTING_KEY", secretValue="infisical_value")
        mock_secrets_response = SimpleNamespace(secrets=[mock_secret])

        mock_client = MagicMock()
        mock_client.secrets.list_secrets.return_value = mock_secrets_response

        mock_sdk_class = MagicMock(return_value=mock_client)

        env = {**_FULL_ENV, "EXISTING_KEY": "local_value"}
        with patch.dict(os.environ, env, clear=True):
            with patch.dict("sys.modules", {"infisical_sdk": MagicMock(InfisicalSDKClient=mock_sdk_class)}):
                inject_infisical_secrets()

            # Local value must be preserved
            assert os.environ["EXISTING_KEY"] == "local_value"

    @patch("shared.py.secrets.logger")
    def test_sdk_authentication_called(self, mock_logger: MagicMock):
        mock_client = MagicMock()
        mock_client.secrets.list_secrets.return_value = SimpleNamespace(secrets=[])
        mock_sdk_class = MagicMock(return_value=mock_client)

        with patch.dict(os.environ, _FULL_ENV, clear=True):
            with patch.dict("sys.modules", {"infisical_sdk": MagicMock(InfisicalSDKClient=mock_sdk_class)}):
                inject_infisical_secrets()

        mock_client.auth.universal_auth.login.assert_called_once_with(
            client_id="cid-xyz",
            client_secret="csec-xyz",
        )

    @patch("shared.py.secrets.logger")
    def test_sdk_client_created_with_correct_host(self, mock_logger: MagicMock):
        mock_client = MagicMock()
        mock_client.secrets.list_secrets.return_value = SimpleNamespace(secrets=[])
        mock_sdk_class = MagicMock(return_value=mock_client)

        with patch.dict(os.environ, _FULL_ENV, clear=True):
            with patch.dict("sys.modules", {"infisical_sdk": MagicMock(InfisicalSDKClient=mock_sdk_class)}):
                inject_infisical_secrets()

        mock_sdk_class.assert_called_once_with(
            host="https://app.infisical.com",
            cache_ttl=3600,
        )

    @patch("shared.py.secrets.logger")
    def test_list_secrets_called_with_correct_params(self, mock_logger: MagicMock):
        mock_client = MagicMock()
        mock_client.secrets.list_secrets.return_value = SimpleNamespace(secrets=[])
        mock_sdk_class = MagicMock(return_value=mock_client)

        with patch.dict(os.environ, _FULL_ENV, clear=True):
            with patch.dict("sys.modules", {"infisical_sdk": MagicMock(InfisicalSDKClient=mock_sdk_class)}):
                inject_infisical_secrets()

        mock_client.secrets.list_secrets.assert_called_once_with(
            project_id="proj-abc",
            environment_slug="production",
            secret_path="/",
            expand_secret_references=True,
            view_secret_value=True,
            recursive=False,
            include_imports=True,
        )

    @patch("shared.py.secrets.logger")
    def test_multiple_secrets_injected(self, mock_logger: MagicMock):
        secrets = [
            SimpleNamespace(secretKey="KEY_A", secretValue="val_a"),
            SimpleNamespace(secretKey="KEY_B", secretValue="val_b"),
            SimpleNamespace(secretKey="KEY_C", secretValue="val_c"),
        ]
        mock_client = MagicMock()
        mock_client.secrets.list_secrets.return_value = SimpleNamespace(secrets=secrets)
        mock_sdk_class = MagicMock(return_value=mock_client)

        with patch.dict(os.environ, _FULL_ENV, clear=True):
            with patch.dict("sys.modules", {"infisical_sdk": MagicMock(InfisicalSDKClient=mock_sdk_class)}):
                inject_infisical_secrets()

            assert os.environ["KEY_A"] == "val_a"
            assert os.environ["KEY_B"] == "val_b"
            assert os.environ["KEY_C"] == "val_c"


# ---------------------------------------------------------------------------
# SDK failure
# ---------------------------------------------------------------------------


class TestInjectInfisicalSecretsSDKFailure:
    """Test that SDK exceptions are wrapped in InfisicalConfigError."""

    @patch("shared.py.secrets.logger")
    def test_sdk_exception_wrapped(self, mock_logger: MagicMock):
        mock_sdk_class = MagicMock(side_effect=ConnectionError("unreachable"))

        with patch.dict(os.environ, _FULL_ENV, clear=True):
            with patch.dict("sys.modules", {"infisical_sdk": MagicMock(InfisicalSDKClient=mock_sdk_class)}):
                with pytest.raises(InfisicalConfigError, match="Failed to fetch secrets"):
                    inject_infisical_secrets()

    @patch("shared.py.secrets.logger")
    def test_auth_failure_wrapped(self, mock_logger: MagicMock):
        mock_client = MagicMock()
        mock_client.auth.universal_auth.login.side_effect = RuntimeError("auth failed")
        mock_sdk_class = MagicMock(return_value=mock_client)

        with patch.dict(os.environ, _FULL_ENV, clear=True):
            with patch.dict("sys.modules", {"infisical_sdk": MagicMock(InfisicalSDKClient=mock_sdk_class)}):
                with pytest.raises(InfisicalConfigError, match="auth failed"):
                    inject_infisical_secrets()

    @patch("shared.py.secrets.logger")
    def test_list_secrets_failure_wrapped(self, mock_logger: MagicMock):
        mock_client = MagicMock()
        mock_client.secrets.list_secrets.side_effect = TimeoutError("timed out")
        mock_sdk_class = MagicMock(return_value=mock_client)

        with patch.dict(os.environ, _FULL_ENV, clear=True):
            with patch.dict("sys.modules", {"infisical_sdk": MagicMock(InfisicalSDKClient=mock_sdk_class)}):
                with pytest.raises(InfisicalConfigError, match="timed out"):
                    inject_infisical_secrets()


# ---------------------------------------------------------------------------
# InfisicalConfigError
# ---------------------------------------------------------------------------


class TestInfisicalConfigError:
    """Test the custom exception class."""

    def test_is_exception(self):
        assert issubclass(InfisicalConfigError, Exception)

    def test_message_preserved(self):
        err = InfisicalConfigError("missing token")
        assert str(err) == "missing token"
