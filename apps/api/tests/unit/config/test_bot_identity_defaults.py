"""Hosted GAIA reads its bot handles from the shared identity file; self-host does not."""

from typing import Any, cast

import pytest

from app.config.capability_requirements import required_keys
from app.config.deployment import DeploymentKind, baseline_profile
from app.config.settings import Settings
from shared.py import bot_identity

_HANDLE_ENV = (
    "TELEGRAM_BOT_USERNAME",
    "WHATSAPP_PHONE_NUMBER",
    "DISCORD_OAUTH_CLIENT_ID",
    "SLACK_OAUTH_CLIENT_ID",
)


def _boot(kind: DeploymentKind, monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Build Settings from this test's kwargs only, never a developer's .env."""
    for name in _HANDLE_ENV:
        monkeypatch.delenv(name, raising=False)
    kwargs: dict[str, Any] = {"ENV": kind}
    for name in required_keys(baseline_profile(kind)):
        kwargs[name] = 0 if Settings.model_fields[name].annotation == int | None else "x"
    return Settings(**cast(Any, kwargs))


def test_hosted_falls_back_to_the_shared_identity_file(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _boot(DeploymentKind.PRODUCTION, monkeypatch)

    assert settings.telegram_bot_username == bot_identity.TELEGRAM_USERNAME
    assert settings.WHATSAPP_PHONE_NUMBER == bot_identity.WHATSAPP_NUMBER
    assert settings.DISCORD_OAUTH_CLIENT_ID == bot_identity.DISCORD_CLIENT_ID
    assert settings.SLACK_OAUTH_CLIENT_ID == bot_identity.SLACK_CLIENT_ID


def test_selfhost_has_no_bot_handles_until_it_sets_them(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _boot(DeploymentKind.SELFHOST, monkeypatch)

    assert settings.telegram_bot_username is None
    assert settings.WHATSAPP_PHONE_NUMBER is None
