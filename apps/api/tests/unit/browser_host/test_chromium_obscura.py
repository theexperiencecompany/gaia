"""``ChromiumHost`` launching Obscura instead of Chromium behind ``BROWSER_ENGINE``.

Obscura is a CDP *server* (`obscura serve`), not chrome-with-a-debug-flag, so the
launch argv and the endpoint discovery differ — but everything past launch speaks
plain CDP and is shared. These cover the engine branch only.
"""

from __future__ import annotations

import subprocess
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.browser_host import chromium
from app.browser_host.chromium import ChromiumHost
from app.config.settings import settings
from app.constants.browser import BrowserEngine


@pytest.mark.unit
async def test_launch_obscura_builds_the_serve_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """engine=obscura spawns ``<bin> serve --port <port> --stealth --allow-private-network``."""
    monkeypatch.setattr(settings, "BROWSER_ENGINE", BrowserEngine.OBSCURA)
    monkeypatch.setattr(settings, "OBSCURA_BIN", "/opt/obscura/obscura")
    monkeypatch.setattr(settings, "OBSCURA_PORT", 9931)
    # Obscura needs no user-data-dir; the chromium path must never be touched.
    mkdtemp = MagicMock()
    monkeypatch.setattr(chromium.tempfile, "mkdtemp", mkdtemp)

    host = ChromiumHost()
    proc = MagicMock(returncode=None)
    spawn = AsyncMock(return_value=proc)
    monkeypatch.setattr(chromium.asyncio, "create_subprocess_exec", spawn)
    host._await_cdp_ready = AsyncMock(return_value="ws://ready")  # type: ignore[method-assign]
    cdp = MagicMock()
    cdp.start = AsyncMock()

    with patch.object(chromium, "CDPClient", return_value=cdp):
        await host._launch()

    assert list(spawn.call_args.args) == [
        "/opt/obscura/obscura",
        "serve",
        "--port",
        "9931",
        "--stealth",
        "--allow-private-network",
    ]
    assert spawn.call_args.kwargs == {
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    mkdtemp.assert_not_called()
    assert host._user_data_dir is None


@pytest.mark.unit
async def test_launch_obscura_without_bin_fails_loud(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing OBSCURA_BIN must raise, not silently fall back to Chromium."""
    monkeypatch.setattr(settings, "BROWSER_ENGINE", BrowserEngine.OBSCURA)
    monkeypatch.setattr(settings, "OBSCURA_BIN", None)
    host = ChromiumHost()

    with pytest.raises(RuntimeError, match="requires OBSCURA_BIN"):
        await host._launch()


@pytest.mark.unit
async def test_await_cdp_ready_obscura_derives_endpoint_from_json_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Obscura's ws endpoint comes from ``/json/version`` at OBSCURA_PORT, no port file."""
    monkeypatch.setattr(settings, "BROWSER_ENGINE", BrowserEngine.OBSCURA)
    monkeypatch.setattr(settings, "OBSCURA_PORT", 9931)
    host = ChromiumHost()
    # Obscura writes no DevToolsActivePort — reaching for it would be the bug.
    host._read_devtools_port = AsyncMock(side_effect=AssertionError("obscura has no port file"))  # type: ignore[method-assign]
    resp = MagicMock()
    resp.json.return_value = {"webSocketDebuggerUrl": "ws://127.0.0.1:9931/devtools/browser"}
    resp.raise_for_status = MagicMock()
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.get = AsyncMock(return_value=resp)

    with patch.object(chromium.httpx, "AsyncClient", return_value=client):
        url = await host._await_cdp_ready()

    assert url == "ws://127.0.0.1:9931/devtools/browser"
    client.get.assert_awaited_once_with("http://127.0.0.1:9931/json/version", timeout=2.0)


@pytest.mark.unit
async def test_await_cdp_ready_obscura_named_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed discovery names Obscura, not Chromium."""
    monkeypatch.setattr(settings, "BROWSER_ENGINE", BrowserEngine.OBSCURA)
    monkeypatch.setattr(settings, "OBSCURA_PORT", 9931)
    monkeypatch.setattr(chromium, "_CDP_READY_TIMEOUT_SECONDS", 0.1)
    monkeypatch.setattr(chromium, "_CDP_READY_POLL_SECONDS", 0.01)
    host = ChromiumHost()
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.get = AsyncMock(side_effect=chromium.httpx.ConnectError("nope"))

    with patch.object(chromium.httpx, "AsyncClient", return_value=client):
        with pytest.raises(RuntimeError, match="Obscura did not expose its CDP endpoint in time"):
            await host._await_cdp_ready()


@pytest.mark.unit
async def test_start_skips_chromium_path_resolution_for_obscura(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """engine=obscura must not resolve (or require) a Chromium binary at start."""
    monkeypatch.setattr(settings, "BROWSER_ENGINE", BrowserEngine.OBSCURA)
    resolve = MagicMock(side_effect=AssertionError("resolved chromium under obscura"))
    monkeypatch.setattr(chromium, "_resolve_chromium_path", resolve)
    host = ChromiumHost()
    host._launch = AsyncMock()  # type: ignore[method-assign]

    with patch.object(chromium.asyncio, "create_task", MagicMock()):
        await host.start()

    resolve.assert_not_called()
    assert host._chromium_path is None
    host._launch.assert_awaited_once()
