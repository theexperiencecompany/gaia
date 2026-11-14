"""One engine: finding Chromium, launching either engine whole or not at all, and how it fails.

Nothing here starts a browser: the binary layout is built on disk and the
process is a fake with a pid, a return code and a wait().
"""

from __future__ import annotations

import asyncio
from pathlib import Path
import shutil
import tempfile
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

from pydantic import SecretStr
import pytest

from app.browser_host import engine as engine_mod
from app.browser_host.cdp_mux import CdpMux
from app.browser_host.engine import ChromiumBinary, Engine, launch_engine
from app.browser_host.host import BrowserHost
from app.browser_host.obscura_launch import LaunchedEngine
from app.browser_host.process import EngineLaunchError, ProcessSampler
from app.config.browser_host_settings import BrowserHostSettings, browser_host_settings
from app.constants.browser import (
    BROWSER_VIEWPORT_HEIGHT,
    BROWSER_VIEWPORT_WIDTH,
    BrowserEngine,
    EngineExit,
)
from app.constants.fortress import FORTRESS_IMAGE, FORTRESS_PERSONA_ARGS, FORTRESS_VOICES
from shared.py.wide_events import log
from tests.unit.browser_host.conftest import FakeMux

pytestmark = pytest.mark.unit

_SHELL = "/ms-playwright/chromium_headless_shell-1187/chrome-linux/headless_shell"
_SHELL_BIN = ChromiumBinary(path=_SHELL, fortress=False)
_FORTRESS_BIN = ChromiumBinary(path="/opt/fortress/tilion", fortress=True)
_WS = "ws://127.0.0.1:9333/devtools/browser/abc"


class _Proc:
    """An engine process: a pid, a return code, and a wait() that returns once it exits."""

    def __init__(self, returncode: int | None = None) -> None:
        self.pid = 4242
        self.returncode = returncode
        self.exited = asyncio.Event()

    async def wait(self) -> int:
        await self.exited.wait()
        return self.returncode or 0

    def exit(self, code: int) -> None:
        self.returncode = code
        self.exited.set()


def _playwright_install(root: Path, *, shell_name: str | None = "headless_shell") -> Path:
    """Lay out Playwright's browsers dir for one revision; return the full chromium binary."""
    full = root / "chromium-1187" / "chrome-linux" / "chrome"
    full.parent.mkdir(parents=True)
    full.write_text("")
    if shell_name is not None:
        shell_bin = root / "chromium_headless_shell-1187" / "chrome-linux" / shell_name
        shell_bin.parent.mkdir(parents=True)
        shell_bin.write_text("")
    return full


# --- finding the binary ---


@pytest.mark.parametrize("shell", ["headless_shell", "chrome-headless-shell"])
def test_the_headless_shell_of_the_same_revision_is_preferred(tmp_path: Path, shell: str) -> None:
    full = _playwright_install(tmp_path, shell_name=shell)

    found = engine_mod._headless_shell_beside(full)

    assert found == tmp_path / "chromium_headless_shell-1187" / "chrome-linux" / shell


@pytest.mark.parametrize("shell", [None, "not-a-browser"])
def test_without_a_shell_build_there_is_nothing_beside_the_browser(
    tmp_path: Path, shell: str | None
) -> None:
    assert (
        engine_mod._headless_shell_beside(_playwright_install(tmp_path, shell_name=shell)) is None
    )


def test_a_browser_outside_a_playwright_install_has_no_shell(tmp_path: Path) -> None:
    binary = tmp_path / "opt" / "chrome"
    binary.parent.mkdir()
    binary.write_text("")

    assert engine_mod._headless_shell_beside(binary) is None


def test_a_configured_binary_wins_and_a_missing_one_fails_loud(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binary = tmp_path / "chrome"
    binary.write_text("")
    monkeypatch.setattr(browser_host_settings, "CHROMIUM_BIN", str(binary))
    monkeypatch.setattr(browser_host_settings, "BROWSER_HOST_FORTRESS", False)
    assert engine_mod.resolve_chromium_binary() == ChromiumBinary(path=str(binary), fortress=False)

    monkeypatch.setattr(browser_host_settings, "BROWSER_HOST_FORTRESS", True)
    assert engine_mod.resolve_chromium_binary() == ChromiumBinary(path=str(binary), fortress=True)

    monkeypatch.setattr(browser_host_settings, "CHROMIUM_BIN", str(tmp_path))
    with pytest.raises(RuntimeError, match="the Chromium binary is not a file"):
        engine_mod.resolve_chromium_binary()


def test_fortress_on_without_a_configured_binary_launches_the_images_and_fails_loud_without_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    launcher = tmp_path / "tilion"
    monkeypatch.setattr(browser_host_settings, "CHROMIUM_BIN", None)
    monkeypatch.setattr(browser_host_settings, "BROWSER_HOST_FORTRESS", True)
    monkeypatch.setattr(engine_mod, "FORTRESS_IMAGE_BIN", str(launcher))
    with pytest.raises(RuntimeError, match=f"run this host on {FORTRESS_IMAGE}"):
        engine_mod.resolve_chromium_binary()

    launcher.write_text("")

    assert engine_mod.resolve_chromium_binary() == ChromiumBinary(path=str(launcher), fortress=True)


@pytest.mark.parametrize("shell", ["headless_shell", None])
def test_without_a_configured_binary_playwrights_own_is_used(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, shell: str | None
) -> None:
    full = _playwright_install(tmp_path, shell_name=shell)
    monkeypatch.setattr(browser_host_settings, "CHROMIUM_BIN", None)
    monkeypatch.setattr(browser_host_settings, "BROWSER_HOST_FORTRESS", False)
    playwright = MagicMock()
    playwright.__enter__.return_value.chromium.executable_path = str(full)
    monkeypatch.setattr(engine_mod, "sync_playwright", lambda: playwright)

    resolved = engine_mod.resolve_chromium_binary()
    assert Path(resolved.path).name == (shell or "chrome")
    assert resolved.fortress is False


# --- the Chromium command ---


def test_the_command_debugs_on_an_ephemeral_port_from_its_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(browser_host_settings, "BROWSER_HOST_HEADED", False)

    args = engine_mod.chromium_argv(_SHELL_BIN, "/tmp/p", None)

    assert args[:3] == [_SHELL, "--remote-debugging-port=0", "--user-data-dir=/tmp/p"]
    assert "--no-sandbox" in args
    assert len(args) == len(set(args))
    assert "--js-flags=--max-old-space-size=512" in args
    assert f"--window-size={BROWSER_VIEWPORT_WIDTH},{BROWSER_VIEWPORT_HEIGHT}" in args
    assert not any(a.startswith("--user-agent=") for a in args)
    assert "--headless" in args
    assert "--headless=new" not in args


def test_the_full_browser_runs_the_new_headless_mode_and_a_headed_host_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(browser_host_settings, "BROWSER_HOST_HEADED", False)
    full = engine_mod.chromium_argv(ChromiumBinary("/opt/chrome", fortress=False), "/tmp/p", "UA/1")
    assert "--headless=new" in full
    assert "--headless" not in full
    assert "--user-agent=UA/1" in full

    monkeypatch.setattr(browser_host_settings, "BROWSER_HOST_HEADED", True)
    assert not any(
        a.startswith("--headless") for a in engine_mod.chromium_argv(_SHELL_BIN, "/p", None)
    )


#: A throwaway CA (a public certificate, no key), and its SPKI pin as openssl computes it
#: (pkey -pubin -outform der | dgst -sha256 | base64).
_TEST_CA_PEM = """-----BEGIN CERTIFICATE-----
MIIBlzCCAT2gAwIBAgIUAoFsjAAE3xxbIEhmPMsdO3EKhZMwCgYIKoZIzj0EAwIw
IDEeMBwGA1UEAwwVYnJvd3NlciBzdGFjayB0ZXN0IENBMCAXDTI2MTAwMzAxMTgz
NVoYDzIxMjYwOTA5MDExODM1WjAgMR4wHAYDVQQDDBVicm93c2VyIHN0YWNrIHRl
c3QgQ0EwWTATBgcqhkjOPQIBBggqhkjOPQMBBwNCAATL7JwItBwMiVgDHFAlUAje
VyK8V28pkCHeTKLjP1rFzd4x1+VbjthFC45qRH52xtpzDjYekkKYOm+3CuB/vB33
o1MwUTAdBgNVHQ4EFgQUKEDP8pgIJcbB2o3IYL0U1M/xH4kwHwYDVR0jBBgwFoAU
KEDP8pgIJcbB2o3IYL0U1M/xH4kwDwYDVR0TAQH/BAUwAwEB/zAKBggqhkjOPQQD
AgNIADBFAiAblNP7iEJMr5Gxk5u1Nzm4bKxBG/k01ZfFg8aD1HhszAIhAK0Hghzc
paMViKIAHZ+GlPEKYALVJgqJMY2CTa8M4lzM
-----END CERTIFICATE-----
"""
_TEST_CA_PIN = "Pp4xppYSf3OB1ZBSw+8Gjix3drxeRv2dNV4Uql7d38c="


def test_chrome_accepts_a_test_stacks_ca_only_while_one_is_set(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ca_file = tmp_path / "ca.pem"
    ca_file.write_text(_TEST_CA_PEM)
    monkeypatch.setattr(browser_host_settings, "BROWSER_HOST_TEST_CA_FILE", None)
    assert not any(
        a.startswith("--ignore-certificate-errors")
        for a in engine_mod.chromium_argv(_SHELL_BIN, "/p", None)
    )

    monkeypatch.setattr(browser_host_settings, "BROWSER_HOST_TEST_CA_FILE", str(ca_file))

    assert f"--ignore-certificate-errors-spki-list={_TEST_CA_PIN}" in engine_mod.chromium_argv(
        _SHELL_BIN, "/p", None
    )


# --- Fortress's one persona ---

#: Every surface Fortress draws per context unless pinned; one left out splits the identity.
_FORTRESS_SURFACES = frozenset(
    {
        "--uxr-platform", "--uxr-ua-platform", "--uxr-ua-os", "--uxr-ua-arch",
        "--uxr-ua-bitness", "--uxr-ua-platform-version", "--uxr-ua-brand",
        "--uxr-hw-concurrency", "--uxr-device-memory", "--uxr-webgl-vendor",
        "--uxr-webgl-renderer", "--uxr-webgl-fullparams", "--uxr-webgl-max-viewport-dims",
        "--uxr-webgl-max-texture-size", "--uxr-webgl-max-cube", "--uxr-webgl-max-renderbuffer",
        "--uxr-webgpu-vendor", "--uxr-webgpu-architecture", "--uxr-webgpu-description",
        "--uxr-screen-width", "--uxr-screen-height", "--uxr-device-pixel-ratio",
        "--uxr-screen-avail-width", "--uxr-screen-avail-height", "--uxr-screen-avail-top",
        "--uxr-screen-avail-left", "--uxr-screen-color-depth", "--uxr-outer-width",
        "--uxr-outer-height", "--uxr-color-gamut", "--uxr-dynamic-range", "--uxr-color-scheme",
        "--uxr-battery-level", "--uxr-battery-charging", "--uxr-battery-charging-time",
        "--uxr-net-effective-type", "--uxr-net-rtt", "--uxr-net-downlink", "--uxr-net-save-data",
        "--uxr-storage-quota", "--uxr-media-devices", "--uxr-voices-list", "--uxr-timezone",
        "--uxr-languages", "--accept-lang",
    }
)  # fmt: skip


def _persona_flags(args: list[str]) -> dict[str, str]:
    return dict(a.split("=", 1) for a in args if a.startswith(("--uxr-", "--accept-lang")))


def test_a_chromium_host_launches_no_persona_unless_fortress_is_switched_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("BROWSER_HOST_FORTRESS", raising=False)
    assert BrowserHostSettings().BROWSER_HOST_FORTRESS is False

    args = engine_mod.chromium_argv(_SHELL_BIN, "/p", None)

    assert _persona_flags(args) == {}
    assert {"--disable-speech-synthesis-api", "--disable-speech-api"} <= set(args)


def test_fortress_launches_with_every_surface_pinned_and_its_timezone_and_languages_from_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(browser_host_settings, "FORTRESS_TIMEZONE", "Europe/Berlin")
    monkeypatch.setattr(browser_host_settings, "FORTRESS_LANGUAGES", ("en-US", "de"))

    args = engine_mod.chromium_argv(_FORTRESS_BIN, "/p", None)
    flags = _persona_flags(args)

    assert set(flags) == _FORTRESS_SURFACES
    assert len(args) == len(set(args))
    assert flags["--uxr-timezone"] == "Europe/Berlin"
    # JS's navigator.languages and the Accept-Language header must say the same thing.
    assert flags["--uxr-languages"] == flags["--accept-lang"] == "en-US,de"
    assert flags["--uxr-media-devices"] == "ai:1,vi:1,ao:1"
    assert not any(a.startswith(("--user-agent=", "--enable-automation")) for a in args)
    # Measured on the real host: with browser-use's speech flags a pinned voice list has no API.
    assert not {"--disable-speech-synthesis-api", "--disable-speech-api"} & set(args)
    # outerWidth/Height agree with the window the host opens (inner is its viewport).
    assert (flags["--uxr-outer-width"], flags["--uxr-outer-height"]) == (
        str(BROWSER_VIEWPORT_WIDTH),
        str(BROWSER_VIEWPORT_HEIGHT),
    )


def test_fortress_voices_are_ascii_entries_of_name_lang_local_default() -> None:
    voices = _persona_flags(list(FORTRESS_PERSONA_ARGS))["--uxr-voices-list"]

    assert voices.isascii()
    entries = [entry.split("|") for entry in voices.split(";")]
    assert len(entries) == len(FORTRESS_VOICES)
    assert all(len(e) == 4 and e[2] in "01" and e[3] in "01" for e in entries)
    assert [e[3] for e in entries].count("1") == 1


# --- the DevTools endpoint file ---


async def test_chromiums_endpoint_is_read_once_it_has_written_both_lines(tmp_path: Path) -> None:
    """Chromium creates the file before it writes it: a partial read means "not yet"."""
    read = engine_mod._devtools_file_reader(str(tmp_path))
    port_file = tmp_path / "DevToolsActivePort"
    assert await read() is None

    for partial in ("", "9333\n", "not-a-port\n/devtools/browser/abc\n"):
        port_file.write_text(partial)
        assert await read() is None
    port_file.write_text("9333\n/devtools/browser/abc\n")

    assert await read() == _WS


# --- launching whole or not at all ---


@pytest.fixture
def root(monkeypatch: pytest.MonkeyPatch) -> FakeMux:
    fake = FakeMux({"Browser.getVersion": {"userAgent": "Mozilla HeadlessChrome/153"}})
    monkeypatch.setattr(engine_mod, "CdpMux", fake.build)
    monkeypatch.setattr(engine_mod, "process_tree_rss_mb", lambda pid: 321.0)
    monkeypatch.setattr(ProcessSampler, "for_pid", MagicMock(return_value=None))
    return fake


async def test_an_obscura_launch_dials_the_endpoint_it_published(
    root: FakeMux, monkeypatch: pytest.MonkeyPatch
) -> None:
    proc = _Proc()
    monkeypatch.setattr(
        engine_mod,
        "launch_obscura",
        AsyncMock(return_value=LaunchedEngine(proc=cast(Any, proc), port=9333, ws_url=_WS)),
    )

    engine = await Engine.launch(BrowserEngine.OBSCURA, None, None)

    assert root.urls == [_WS]
    assert root.started == 1
    assert engine.profile_dir is None
    assert engine.fortress is False
    assert engine.base_rss_mb == 321.0
    assert engine.alive


async def test_a_chromium_launch_gets_a_fresh_profile_and_dials_its_port(
    root: FakeMux, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    spawned: list[list[str]] = []

    async def _spawn(argv: list[str], env: dict[str, str] | None) -> Any:
        spawned.append(argv)
        profile = next(a for a in argv if a.startswith("--user-data-dir=")).split("=", 1)[1]
        (Path(profile) / "DevToolsActivePort").write_text("9333\n/devtools/browser/abc\n")
        return _Proc()

    monkeypatch.setattr(engine_mod, "spawn_engine", _spawn)

    engine = await Engine.launch(BrowserEngine.CHROMIUM, _SHELL_BIN, "UA/1")

    assert engine.profile_dir is not None
    assert Path(engine.profile_dir).parent == tmp_path
    assert f"--user-data-dir={engine.profile_dir}" in spawned[0]
    assert "--user-agent=UA/1" in spawned[0]
    assert engine.fortress is False
    assert root.urls == [_WS]


@pytest.mark.parametrize(
    ("chromium", "agents"),
    [(_SHELL_BIN, [None, "Mozilla Chrome/153"]), (_FORTRESS_BIN, [None])],
)
async def test_a_headless_announcing_chromium_relaunches_as_plain_chrome_unless_it_is_fortress(
    root: FakeMux,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    chromium: ChromiumBinary,
    agents: list[str | None],
) -> None:
    """The default host announced HeadlessChrome; a made-up UA desyncs Fortress's Client Hints."""
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(browser_host_settings, "BROWSER_ENGINE", BrowserEngine.CHROMIUM)
    spawned: list[list[str]] = []

    async def _spawn(argv: list[str], env: dict[str, str] | None) -> Any:
        spawned.append(argv)
        profile = next(a for a in argv if a.startswith("--user-data-dir=")).split("=", 1)[1]
        (Path(profile) / "DevToolsActivePort").write_text("9333\n/devtools/browser/abc\n")
        return _Proc()

    monkeypatch.setattr(engine_mod, "spawn_engine", _spawn)
    monkeypatch.setattr(engine_mod, "stop_process", AsyncMock())
    host = BrowserHost(on_fatal=MagicMock())
    host._chromium = chromium

    try:
        engine = await host._launch()
    finally:
        await host.stop()

    announced = [
        next((a.split("=", 1)[1] for a in argv if a.startswith("--user-agent=")), None)
        for argv in spawned
    ]
    assert announced == agents
    assert engine.fortress is chromium.fortress


async def test_chromium_is_spawned_without_the_desktop_session_bus(
    root: FakeMux, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "unix:path=/run/user/1002/bus")
    monkeypatch.setenv("GAIA_ENGINE_ENV_PROBE", "kept")
    envs: list[dict[str, str] | None] = []

    async def _spawn(argv: list[str], env: dict[str, str] | None) -> Any:
        envs.append(env)
        profile = next(a for a in argv if a.startswith("--user-data-dir=")).split("=", 1)[1]
        (Path(profile) / "DevToolsActivePort").write_text("9333\n/devtools/browser/abc\n")
        return _Proc()

    monkeypatch.setattr(engine_mod, "spawn_engine", _spawn)

    await Engine.launch(BrowserEngine.CHROMIUM, _SHELL_BIN, None)

    assert envs[0] is not None
    assert "DBUS_SESSION_BUS_ADDRESS" not in envs[0]
    assert envs[0]["GAIA_ENGINE_ENV_PROBE"] == "kept"


@pytest.mark.parametrize(("configured", "passed"), [("jwt-key", "jwt-key"), (None, None)])
def test_fortress_gets_its_license_only_from_the_hosts_setting(
    monkeypatch: pytest.MonkeyPatch, configured: str | None, passed: str | None
) -> None:
    """A blank inherited TILION_LICENSE_KEY would shadow ~/.tilion/license.jwt, so only the setting is passed."""
    monkeypatch.setenv("TILION_LICENSE_KEY", "")
    monkeypatch.setattr(
        browser_host_settings,
        "TILION_LICENSE_KEY",
        SecretStr(configured) if configured is not None else None,
    )

    assert engine_mod.chromium_env().get("TILION_LICENSE_KEY") == passed


class _MuxThatNeverShakesHands:
    def __init__(self, url: str) -> None:
        self.url = url

    async def start(self) -> None:
        raise TimeoutError


async def test_an_engine_that_never_finishes_the_handshake_fails_naming_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    proc = _Proc()
    monkeypatch.setattr(engine_mod, "spawn_engine", AsyncMock(return_value=proc))
    monkeypatch.setattr(engine_mod, "until_published", AsyncMock(return_value=_WS))
    monkeypatch.setattr(engine_mod, "CdpMux", _MuxThatNeverShakesHands)
    stop = AsyncMock()
    monkeypatch.setattr(engine_mod, "stop_process", stop)

    with pytest.raises(
        EngineLaunchError, match=f"published {_WS} but did not finish the CDP handshake"
    ):
        await Engine.launch(BrowserEngine.CHROMIUM, _SHELL_BIN, None)

    stop.assert_awaited_once_with(proc)
    assert list(tmp_path.iterdir()) == []


async def test_a_launch_that_fails_leaves_no_process_and_no_profile(
    root: FakeMux, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    proc = _Proc()
    monkeypatch.setattr(engine_mod, "spawn_engine", AsyncMock(return_value=proc))
    monkeypatch.setattr(
        engine_mod, "until_published", AsyncMock(side_effect=EngineLaunchError("never"))
    )
    stop = AsyncMock()
    monkeypatch.setattr(engine_mod, "stop_process", stop)

    with pytest.raises(EngineLaunchError):
        await Engine.launch(BrowserEngine.CHROMIUM, _SHELL_BIN, None)

    stop.assert_awaited_once_with(proc)
    assert list(tmp_path.iterdir()) == []
    assert root.started == 0


async def test_a_chromium_launch_needs_its_binary_resolved() -> None:
    with pytest.raises(RuntimeError, match="chromium binary not resolved"):
        await Engine.launch(BrowserEngine.CHROMIUM, None, None)


def _engine(
    proc: _Proc | None = None, mux: FakeMux | None = None, profile: str | None = None
) -> Engine:
    return Engine(
        kind=BrowserEngine.CHROMIUM,
        proc=cast(Any, proc or _Proc()),
        root_mux=cast(CdpMux, mux or FakeMux()),
        root_ws_url=_WS,
        profile_dir=profile,
        sampler=None,
        base_rss_mb=0.0,
        fortress=False,
    )


async def test_a_headless_chromium_is_relaunched_announcing_plain_chrome(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = _engine(mux=FakeMux({"Browser.getVersion": {"userAgent": "M HeadlessChrome/153"}}))
    second = _engine()
    launch = AsyncMock(side_effect=[first, second])
    monkeypatch.setattr(Engine, "launch", launch)
    shutdown = AsyncMock()
    monkeypatch.setattr(Engine, "shutdown", shutdown)

    engine, agent = await launch_engine(BrowserEngine.CHROMIUM, _SHELL_BIN, None)

    assert engine is second
    assert agent == "M Chrome/153"
    assert [c.args for c in launch.await_args_list] == [
        (BrowserEngine.CHROMIUM, _SHELL_BIN, None),
        (BrowserEngine.CHROMIUM, _SHELL_BIN, "M Chrome/153"),
    ]
    shutdown.assert_awaited_once()


@pytest.mark.parametrize(
    ("kind", "agent", "announced", "fortress"),
    [
        (BrowserEngine.OBSCURA, None, "unused", False),
        (BrowserEngine.CHROMIUM, "Known/1", "unused", False),
        (BrowserEngine.CHROMIUM, None, "M Chrome/153", False),
        (BrowserEngine.CHROMIUM, None, "M HeadlessChrome/153", True),
    ],
)
async def test_an_engine_that_already_announces_a_plain_browser_is_launched_once(
    monkeypatch: pytest.MonkeyPatch,
    kind: BrowserEngine,
    agent: str | None,
    announced: str,
    fortress: bool,
) -> None:
    only = _engine(mux=FakeMux({"Browser.getVersion": {"userAgent": announced}}))
    only.fortress = fortress
    launch = AsyncMock(return_value=only)
    monkeypatch.setattr(Engine, "launch", launch)

    engine, learned = await launch_engine(kind, _SHELL_BIN, agent)

    assert engine is only
    assert [c.args for c in launch.await_args_list] == [(kind, _SHELL_BIN, agent)]
    assert learned == (
        announced if kind is BrowserEngine.CHROMIUM and not (agent or fortress) else agent
    )


# --- how an engine fails, and stops ---


async def test_an_engine_whose_process_exits_has_failed() -> None:
    proc = _Proc()
    engine = _engine(proc)
    watch = asyncio.create_task(engine.wait_failed())
    await asyncio.sleep(0)

    proc.exit(-9)

    assert await asyncio.wait_for(watch, 1.0) is EngineExit.PROCESS_EXITED
    assert not engine.alive


async def test_an_engine_whose_root_connection_drops_has_failed() -> None:
    mux = FakeMux()
    engine = _engine(mux=mux)
    watch = asyncio.create_task(engine.wait_failed())
    await asyncio.sleep(0)

    await mux.close()

    assert await asyncio.wait_for(watch, 1.0) is EngineExit.CONNECTION_CLOSED
    assert not engine.alive


async def test_an_engine_that_stops_answering_fails_only_after_the_strikes_in_a_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(engine_mod, "_LIVENESS_PROBE_INTERVAL_SECONDS", 0.0)
    answers = iter([False, True, False, False])
    engine = _engine()
    asked: list[float] = []

    async def _responsive(_self: Engine, timeout: float) -> bool:
        asked.append(timeout)
        return next(answers)

    monkeypatch.setattr(Engine, "responsive", _responsive)

    failure = await asyncio.wait_for(engine.wait_failed(), 1.0)

    assert failure is EngineExit.STOPPED_ANSWERING
    assert len(asked) == 4


async def test_a_responsive_engine_answers_on_its_root_and_a_dead_one_is_not_asked() -> None:
    mux = FakeMux()
    engine = _engine(mux=mux)
    assert await engine.responsive(1.0) is True
    assert mux.methods == ["Target.getTargets"]

    mux.send_error = RuntimeError("socket gone")
    assert await engine.responsive(1.0) is False

    await mux.close()
    mux.send_error = None
    assert await engine.responsive(1.0) is False
    assert mux.methods == ["Target.getTargets", "Target.getTargets"]


async def test_shutdown_stops_the_tree_then_closes_the_root_and_deletes_the_profile(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    profile = tmp_path / "profile"
    profile.mkdir()
    (profile / "Default").mkdir()
    stop = AsyncMock()
    monkeypatch.setattr(engine_mod, "stop_process", stop)
    mux = FakeMux()
    proc = _Proc()
    engine = _engine(proc, mux, str(profile))

    await engine.shutdown(graceful=False)

    stop.assert_awaited_once_with(proc, graceful=False)
    assert mux.closed
    assert not profile.exists()


async def test_a_profile_that_cannot_be_removed_is_a_warning_not_a_failed_stop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(engine_mod, "stop_process", AsyncMock())
    monkeypatch.setattr(shutil, "rmtree", MagicMock(side_effect=OSError("busy")))
    warning = MagicMock()
    monkeypatch.setattr(log, "warning", warning)

    await _engine(profile="/nowhere").shutdown()

    assert warning.call_args.kwargs == {"error_type": "OSError"}
    assert "profile not removed" in warning.call_args.args[0]


async def test_an_engines_memory_is_its_process_trees(monkeypatch: pytest.MonkeyPatch) -> None:
    read = MagicMock(return_value=812.5)
    monkeypatch.setattr(engine_mod, "process_tree_rss_mb", read)

    assert _engine().rss_mb() == 812.5
    read.assert_called_once_with(4242)
