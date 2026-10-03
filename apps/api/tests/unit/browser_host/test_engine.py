"""One engine: finding Chromium, launching either engine whole or not at all, and how it fails.

Nothing here starts a browser: the binary layout is built on disk and the
process is a fake with a pid, a return code and a wait().
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.browser_host import engine as engine_mod
from app.browser_host.cdp_mux import CdpMux
from app.browser_host.engine import Engine, launch_engine
from app.browser_host.obscura_launch import LaunchedEngine
from app.browser_host.process import EngineLaunchError
from app.constants.browser import (
    BROWSER_VIEWPORT_HEIGHT,
    BROWSER_VIEWPORT_WIDTH,
    BrowserEngine,
    EngineExit,
)
from tests.unit.browser_host.conftest import FakeMux

pytestmark = pytest.mark.unit

_SHELL = "/ms-playwright/chromium_headless_shell-1187/chrome-linux/headless_shell"
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
    monkeypatch.setattr(engine_mod.browser_host_settings, "CHROMIUM_BIN", str(binary))
    assert engine_mod.resolve_chromium_path() == str(binary)

    monkeypatch.setattr(engine_mod.browser_host_settings, "CHROMIUM_BIN", str(tmp_path))
    with pytest.raises(RuntimeError, match="CHROMIUM_BIN is set but is not a file"):
        engine_mod.resolve_chromium_path()


@pytest.mark.parametrize("shell", ["headless_shell", None])
def test_without_a_configured_binary_playwrights_own_is_used(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, shell: str | None
) -> None:
    full = _playwright_install(tmp_path, shell_name=shell)
    monkeypatch.setattr(engine_mod.browser_host_settings, "CHROMIUM_BIN", None)
    playwright = MagicMock()
    playwright.__enter__.return_value.chromium.executable_path = str(full)
    monkeypatch.setattr(engine_mod, "sync_playwright", lambda: playwright)

    assert Path(engine_mod.resolve_chromium_path()).name == (shell or "chrome")


# --- the Chromium command ---


def test_the_command_debugs_on_an_ephemeral_port_from_its_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(engine_mod.browser_host_settings, "BROWSER_HOST_HEADED", False)

    args = engine_mod.chromium_argv(_SHELL, "/tmp/p", None)

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
    monkeypatch.setattr(engine_mod.browser_host_settings, "BROWSER_HOST_HEADED", False)
    full = engine_mod.chromium_argv("/opt/chrome", "/tmp/p", "UA/1")
    assert "--headless=new" in full
    assert "--headless" not in full
    assert "--user-agent=UA/1" in full

    monkeypatch.setattr(engine_mod.browser_host_settings, "BROWSER_HOST_HEADED", True)
    assert not any(a.startswith("--headless") for a in engine_mod.chromium_argv(_SHELL, "/p", None))


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
    monkeypatch.setattr(engine_mod.browser_host_settings, "BROWSER_HOST_TEST_CA_FILE", None)
    assert not any(
        a.startswith("--ignore-certificate-errors")
        for a in engine_mod.chromium_argv(_SHELL, "/p", None)
    )

    monkeypatch.setattr(engine_mod.browser_host_settings, "BROWSER_HOST_TEST_CA_FILE", str(ca_file))

    assert f"--ignore-certificate-errors-spki-list={_TEST_CA_PIN}" in engine_mod.chromium_argv(
        _SHELL, "/p", None
    )


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
    monkeypatch.setattr(engine_mod.ProcessSampler, "for_pid", MagicMock(return_value=None))
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
    assert engine.base_rss_mb == 321.0
    assert engine.alive


async def test_a_chromium_launch_gets_a_fresh_profile_and_dials_its_port(
    root: FakeMux, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(engine_mod.tempfile, "tempdir", str(tmp_path))
    spawned: list[list[str]] = []

    async def _spawn(argv: list[str], env: dict[str, str] | None) -> Any:
        spawned.append(argv)
        profile = next(a for a in argv if a.startswith("--user-data-dir=")).split("=", 1)[1]
        (Path(profile) / "DevToolsActivePort").write_text("9333\n/devtools/browser/abc\n")
        return _Proc()

    monkeypatch.setattr(engine_mod, "spawn_engine", _spawn)

    engine = await Engine.launch(BrowserEngine.CHROMIUM, _SHELL, "UA/1")

    assert engine.profile_dir is not None
    assert Path(engine.profile_dir).parent == tmp_path
    assert f"--user-data-dir={engine.profile_dir}" in spawned[0]
    assert "--user-agent=UA/1" in spawned[0]
    assert root.urls == [_WS]


async def test_a_launch_that_fails_leaves_no_process_and_no_profile(
    root: FakeMux, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(engine_mod.tempfile, "tempdir", str(tmp_path))
    proc = _Proc()
    monkeypatch.setattr(engine_mod, "spawn_engine", AsyncMock(return_value=proc))
    monkeypatch.setattr(
        engine_mod, "until_published", AsyncMock(side_effect=EngineLaunchError("never"))
    )
    stop = AsyncMock()
    monkeypatch.setattr(engine_mod, "stop_process", stop)

    with pytest.raises(EngineLaunchError):
        await Engine.launch(BrowserEngine.CHROMIUM, _SHELL, None)

    stop.assert_awaited_once_with(proc)
    assert list(tmp_path.iterdir()) == []
    assert root.started == 0


async def test_a_chromium_launch_needs_its_binary_resolved() -> None:
    with pytest.raises(RuntimeError, match="chromium_path not resolved"):
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

    engine, agent = await launch_engine(BrowserEngine.CHROMIUM, _SHELL, None)

    assert engine is second
    assert agent == "M Chrome/153"
    assert [c.args for c in launch.await_args_list] == [
        (BrowserEngine.CHROMIUM, _SHELL, None),
        (BrowserEngine.CHROMIUM, _SHELL, "M Chrome/153"),
    ]
    shutdown.assert_awaited_once()


@pytest.mark.parametrize(
    ("kind", "agent", "announced"),
    [
        (BrowserEngine.OBSCURA, None, "unused"),
        (BrowserEngine.CHROMIUM, "Known/1", "unused"),
        (BrowserEngine.CHROMIUM, None, "M Chrome/153"),
    ],
)
async def test_an_engine_that_already_announces_a_plain_browser_is_launched_once(
    monkeypatch: pytest.MonkeyPatch, kind: BrowserEngine, agent: str | None, announced: str
) -> None:
    only = _engine(mux=FakeMux({"Browser.getVersion": {"userAgent": announced}}))
    launch = AsyncMock(return_value=only)
    monkeypatch.setattr(Engine, "launch", launch)

    engine, learned = await launch_engine(kind, _SHELL, agent)

    assert engine is only
    assert [c.args for c in launch.await_args_list] == [(kind, _SHELL, agent)]
    assert learned == (agent if kind is BrowserEngine.OBSCURA or agent else announced)


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
    monkeypatch.setattr(engine_mod.shutil, "rmtree", MagicMock(side_effect=OSError("busy")))
    warning = MagicMock()
    monkeypatch.setattr(engine_mod.log, "warning", warning)

    await _engine(profile="/nowhere").shutdown()

    assert warning.call_args.kwargs == {"error_type": "OSError"}
    assert "profile not removed" in warning.call_args.args[0]


async def test_an_engines_memory_is_its_process_trees(monkeypatch: pytest.MonkeyPatch) -> None:
    read = MagicMock(return_value=812.5)
    monkeypatch.setattr(engine_mod, "process_tree_rss_mb", read)

    assert _engine().rss_mb() == 812.5
    read.assert_called_once_with(4242)


async def test_an_engine_reports_the_agent_it_announces() -> None:
    engine = _engine(mux=FakeMux({"Browser.getVersion": {"userAgent": "UA/9"}}))

    assert await engine.user_agent() == "UA/9"
