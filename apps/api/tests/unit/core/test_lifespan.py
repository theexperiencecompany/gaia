"""Unit tests for the application lifespan PostHog config guard.

The guard must never block boot: token-less environments (local dev without
Infisical, the schemathesis live server) legitimately run without analytics —
the SILENT loader no-ops captures. Missing config is a loud log line, not a
fatal error. The client-init path (tokens present) must fetch the provider and
close it when the lifespan ends.
"""

import pytest
from pytest_mock import MockerFixture

from app.core.lifespan import lifespan


def _boot_patches(mocker: MockerFixture) -> None:
    mocker.patch("app.core.lifespan.unified_startup", new=mocker.AsyncMock())
    mocker.patch("app.core.lifespan.start_browser_reaper")
    mocker.patch("app.core.lifespan.start_revoke_listener")
    mocker.patch("app.core.lifespan.start_up_listener")
    mocker.patch("app.core.lifespan.unified_shutdown", new=mocker.AsyncMock())
    mocker.patch("app.core.lifespan.stop_up_listener", new=mocker.AsyncMock())
    mocker.patch("app.core.lifespan.stop_revoke_listener", new=mocker.AsyncMock())
    mocker.patch("app.core.lifespan.stop_browser_reaper")
    mocker.patch("app.core.lifespan._CONTEXT_EXECUTOR.shutdown")


def _set_posthog(mocker: MockerFixture, token: str | None, host: str | None) -> None:
    settings = mocker.patch("app.core.lifespan.settings")
    settings.ENV = "development"
    settings.POSTHOG_PROJECT_TOKEN = token
    settings.POSTHOG_HOST = host


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("token", "host", "expected_missing"),
    [
        (None, "https://ph.example.com", "POSTHOG_PROJECT_TOKEN"),
        ("phc_test", None, "POSTHOG_HOST"),
        (None, None, "POSTHOG_PROJECT_TOKEN"),
    ],
)
async def test_missing_posthog_config_logs_loudly_but_boots(
    mocker: MockerFixture,
    token: str | None,
    host: str | None,
    expected_missing: str,
) -> None:
    """Any missing piece of the PostHog config is a loud startup log line,
    never a boot failure — no matter the ENV."""
    _set_posthog(mocker, token, host)
    _boot_patches(mocker)
    log_error = mocker.patch("app.core.lifespan.log.error")
    providers_get = mocker.patch("app.core.lifespan.providers.get")

    async with lifespan(None):
        pass

    log_error.assert_called_once()
    assert log_error.call_args.kwargs["missing_var"] == expected_missing
    assert "PostHog not configured" in log_error.call_args.args[0]
    providers_get.assert_not_called()


@pytest.mark.asyncio
async def test_full_posthog_config_initialises_client_and_shuts_it_down(
    mocker: MockerFixture,
) -> None:
    """With both keys present the client is fetched by provider name and closed
    when the lifespan ends.

    ``shutdown()``, not ``flush()``: flush only drains the queue, leaving the
    consumer threads, the flag poller, and exception capture alive.
    """
    _set_posthog(mocker, "phc_test", "https://ph.example.com")
    _boot_patches(mocker)
    log_error = mocker.patch("app.core.lifespan.log.error")
    fake_client = mocker.Mock()
    providers_get = mocker.patch("app.core.lifespan.providers.get", return_value=fake_client)

    async with lifespan(None):
        fake_client.shutdown.assert_not_called()

    log_error.assert_not_called()
    providers_get.assert_called_once_with("posthog")
    fake_client.shutdown.assert_called_once_with()
    fake_client.flush.assert_not_called()


@pytest.mark.asyncio
async def test_client_is_shut_down_even_when_the_app_body_raises(
    mocker: MockerFixture,
) -> None:
    """A crash inside the running app must still close the client — otherwise a
    failing pod drops every event still sitting in the queue."""
    _set_posthog(mocker, "phc_test", "https://ph.example.com")
    _boot_patches(mocker)
    mocker.patch("app.core.lifespan.log.error")
    fake_client = mocker.Mock()
    mocker.patch("app.core.lifespan.providers.get", return_value=fake_client)

    with pytest.raises(RuntimeError, match="Startup failed"):
        async with lifespan(None):
            raise ValueError("boom")

    fake_client.shutdown.assert_called_once_with()


@pytest.mark.asyncio
async def test_full_config_with_unregistered_provider_skips_shutdown(
    mocker: MockerFixture,
) -> None:
    """A missing provider registration (client None) must not attempt to shut
    down None."""
    _set_posthog(mocker, "phc_test", "https://ph.example.com")
    _boot_patches(mocker)
    providers_get = mocker.patch("app.core.lifespan.providers.get", return_value=None)

    async with lifespan(None):
        pass

    providers_get.assert_called_once_with("posthog")


@pytest.mark.asyncio
async def test_partial_config_never_initialises_client(mocker: MockerFixture) -> None:
    """One missing key means no client — the init guard is an AND, not an OR
    (a single key must not half-arm analytics)."""
    _set_posthog(mocker, "phc_test", None)
    _boot_patches(mocker)
    providers_get = mocker.patch("app.core.lifespan.providers.get")

    async with lifespan(None):
        pass

    providers_get.assert_not_called()
