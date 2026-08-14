"""Unit tests for the application lifespan PostHog config guard.

The guard must never block boot: token-less environments (local dev without
Infisical, the schemathesis live server) legitimately run without analytics —
the SILENT loader no-ops captures. Missing config is a loud log line, not a
fatal error.
"""

import pytest
from pytest_mock import MockerFixture

from app.core.lifespan import lifespan


@pytest.mark.asyncio
async def test_lifespan_boots_without_posthog_tokens_in_development(
    mocker: MockerFixture,
) -> None:
    """Token-less development boot must not raise (schemathesis live server,
    local dev). Regression pin: the previous guard raised here and CI's
    live-server boot died on it."""
    monkeypatch = mocker.patch("app.core.lifespan.settings")
    monkeypatch.ENV = "development"
    monkeypatch.POSTHOG_PROJECT_TOKEN = None
    monkeypatch.POSTHOG_HOST = None

    mocker.patch("app.core.lifespan.unified_startup", new=mocker.AsyncMock())
    mocker.patch("app.core.lifespan.start_browser_reaper")
    mocker.patch("app.core.lifespan.start_revoke_listener")
    mocker.patch("app.core.lifespan.start_up_listener")
    mocker.patch("app.core.lifespan.unified_shutdown", new=mocker.AsyncMock())
    mocker.patch("app.core.lifespan.stop_up_listener", new=mocker.AsyncMock())
    mocker.patch("app.core.lifespan.stop_revoke_listener", new=mocker.AsyncMock())
    mocker.patch("app.core.lifespan.stop_browser_reaper")
    mocker.patch("app.core.lifespan._CONTEXT_EXECUTOR.shutdown")
    log_error = mocker.patch("app.core.lifespan.log.error")

    async with lifespan(None):
        pass

    log_error.assert_called_once()
    assert "PostHog" in log_error.call_args.args[0]


@pytest.mark.asyncio
async def test_lifespan_boots_without_posthog_tokens_in_production(
    mocker: MockerFixture,
) -> None:
    """Even production boots without tokens — the failure mode is loud logs
    and no-op captures, never a bricked API."""
    monkeypatch = mocker.patch("app.core.lifespan.settings")
    monkeypatch.ENV = "production"
    monkeypatch.POSTHOG_PROJECT_TOKEN = None
    monkeypatch.POSTHOG_HOST = None

    mocker.patch("app.core.lifespan.unified_startup", new=mocker.AsyncMock())
    mocker.patch("app.core.lifespan.start_browser_reaper")
    mocker.patch("app.core.lifespan.start_revoke_listener")
    mocker.patch("app.core.lifespan.start_up_listener")
    mocker.patch("app.core.lifespan.unified_shutdown", new=mocker.AsyncMock())
    mocker.patch("app.core.lifespan.stop_up_listener", new=mocker.AsyncMock())
    mocker.patch("app.core.lifespan.stop_revoke_listener", new=mocker.AsyncMock())
    mocker.patch("app.core.lifespan.stop_browser_reaper")
    mocker.patch("app.core.lifespan._CONTEXT_EXECUTOR.shutdown")

    async with lifespan(None):
        pass
