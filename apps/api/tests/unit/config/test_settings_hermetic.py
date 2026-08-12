"""The Infisical fence: test runs must never call the real vault.

The root conftest patches both bindings (the source module and the
settings-module copy) and asserts them at startup; these tests pin that
guarantee at the unit level so a regression is caught with a precise
failure, not a wall of startup noise.
"""

from unittest.mock import MagicMock

from app.config import secrets, settings


def test_settings_binding_is_mocked() -> None:
    assert isinstance(settings.inject_infisical_secrets, MagicMock)


def test_secrets_module_binding_is_mocked() -> None:
    assert isinstance(secrets.inject_infisical_secrets, MagicMock)
