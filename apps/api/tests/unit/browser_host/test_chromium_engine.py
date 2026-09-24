"""The engine under the host: finding it, launching it, admitting sessions onto it, keeping it alive.

Nothing here starts a browser. The binary layout is built on disk, the process
is a fake with a pid and a return code, and psutil, the sampler and the
DevTools endpoint answer as the real ones do.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
import subprocess
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import psutil
import pytest

from app.browser_host import chromium
from app.browser_host.cdp_mux import CdpMux
from app.browser_host.chromium import (
    AtCapacityError,
    CDPTimeoutError,
    ChromiumHost,
    cdp_call,
)
from app.constants.browser import (
    BROWSER_VIEWPORT_HEIGHT,
    BROWSER_VIEWPORT_WIDTH,
    BrowserEngine,
    HostAdmissionRefusal,
)
from app.constants.log_tags import LogTag
from tests.unit.browser_host.conftest import FakeMux, install_mux, make_host, make_session

pytestmark = pytest.mark.unit

_MB = 1024 * 1024


def _sampler(rss_mb: float | None) -> MagicMock:
    sampler = MagicMock()
    sampler.sample.return_value = None if rss_mb is None else (rss_mb, 5.0)
    return sampler


class _Proc:
    """An engine process: a pid, a return code, and a wait() that returns once it has exited."""

    def __init__(self, pid: int = 4242, returncode: int | None = None) -> None:
        self.pid = pid
        self.returncode = returncode
        self.terminated = False
        self.killed = False
        self.ignores_terminate = False

    def terminate(self) -> None:
        self.terminated = True
        if not self.ignores_terminate:
            self.returncode = -15

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9

    async def wait(self) -> int:
        if self.ignores_terminate:
            raise TimeoutError
        return self.returncode or 0


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


# --- cdp_call ---


async def test_a_timed_out_cdp_call_names_the_method_and_its_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logger = MagicMock()
    monkeypatch.setattr(chromium, "log", logger)

    with pytest.raises(CDPTimeoutError) as err:
        await cdp_call(FakeMux(hang_on="Page.navigate"), "Page.navigate", timeout=0.01)

    assert err.value.args == ("Page.navigate",)
    logger.error.assert_called_once_with(
        f"{LogTag.BROWSER} browser host CDP call timed out",
        error_type="CDPTimeoutError",
        browser={"cdp_method": "Page.navigate", "timeout_seconds": 0.01},
    )


# --- finding the binary ---


def test_the_headless_shell_of_the_same_revision_is_preferred(tmp_path: Path) -> None:
    full = _playwright_install(tmp_path)

    found = chromium._headless_shell_beside(full)

    assert found == tmp_path / "chromium_headless_shell-1187" / "chrome-linux" / "headless_shell"


def test_the_macos_shell_name_is_found_too(tmp_path: Path) -> None:
    full = _playwright_install(tmp_path, shell_name="chrome-headless-shell")

    found = chromium._headless_shell_beside(full)

    assert found is not None
    assert found.name == "chrome-headless-shell"


@pytest.mark.parametrize("shell", [None, "not-a-browser"])
def test_without_a_shell_build_there_is_nothing_beside_the_browser(
    tmp_path: Path, shell: str | None
) -> None:
    assert chromium._headless_shell_beside(_playwright_install(tmp_path, shell_name=shell)) is None


def test_a_browser_outside_a_playwright_install_has_no_shell(tmp_path: Path) -> None:
    binary = tmp_path / "opt" / "chrome"
    binary.parent.mkdir()
    binary.write_text("")

    assert chromium._headless_shell_beside(binary) is None


def test_a_configured_binary_wins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    binary = tmp_path / "chrome"
    binary.write_text("")
    monkeypatch.setattr(chromium.browser_host_settings, "CHROMIUM_BIN", str(binary))

    assert chromium._resolve_chromium_path() == str(binary)


def test_a_configured_binary_that_is_not_a_file_fails_loud(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(chromium.browser_host_settings, "CHROMIUM_BIN", str(tmp_path))

    with pytest.raises(RuntimeError, match="CHROMIUM_BIN is set but is not a file"):
        chromium._resolve_chromium_path()


@pytest.mark.parametrize("shell", ["headless_shell", None])
def test_without_a_configured_binary_playwrights_own_is_used(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, shell: str | None
) -> None:
    full = _playwright_install(tmp_path, shell_name=shell)
    monkeypatch.setattr(chromium.browser_host_settings, "CHROMIUM_BIN", None)
    playwright = MagicMock()
    playwright.__enter__.return_value.chromium.executable_path = str(full)
    monkeypatch.setattr(chromium, "sync_playwright", lambda: playwright)

    resolved = Path(chromium._resolve_chromium_path())

    assert resolved.name == (shell or "chrome")


# --- the launch command ---


@pytest.fixture
def chrome_host(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ChromiumHost:
    monkeypatch.setattr(chromium.tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(chromium.browser_host_settings, "BROWSER_HOST_HEADED", False)
    host = ChromiumHost()
    host._chromium_path = "/ms-playwright/chromium_headless_shell-1187/chrome-linux/headless_shell"
    return host


def test_the_command_debugs_on_an_ephemeral_port_from_a_fresh_profile(
    chrome_host: ChromiumHost, tmp_path: Path
) -> None:
    args = chrome_host._chromium_command()

    assert args[0] == chrome_host._chromium_path
    assert "--remote-debugging-port=0" in args
    profile = Path(chrome_host._user_data_dir or "")
    assert f"--user-data-dir={profile}" in args
    assert profile.is_dir()
    assert profile.parent == tmp_path
    assert profile.name.startswith("gaia-browser-host-")


def test_the_command_caps_the_js_heap_and_sizes_the_window_to_the_viewport(
    chrome_host: ChromiumHost,
) -> None:
    args = chrome_host._chromium_command()

    assert "--js-flags=--max-old-space-size=512" in args
    assert f"--window-size={BROWSER_VIEWPORT_WIDTH},{BROWSER_VIEWPORT_HEIGHT}" in args
    assert not any(a.startswith("--user-agent=") for a in args)


def test_the_shell_build_gets_the_bare_headless_flag(chrome_host: ChromiumHost) -> None:
    args = chrome_host._chromium_command()

    assert "--headless" in args
    assert "--headless=new" not in args


def test_the_full_browser_gets_the_new_headless_mode(chrome_host: ChromiumHost) -> None:
    chrome_host._chromium_path = "/ms-playwright/chromium-1187/chrome-linux/chrome"

    args = chrome_host._chromium_command()

    assert "--headless=new" in args
    assert "--headless" not in args


def test_a_headed_host_runs_with_no_headless_flag(
    chrome_host: ChromiumHost, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(chromium.browser_host_settings, "BROWSER_HOST_HEADED", True)

    args = chrome_host._chromium_command()

    assert not any(a.startswith("--headless") for a in args)


def test_a_learned_user_agent_is_launched_with(chrome_host: ChromiumHost) -> None:
    chrome_host._user_agent = "Mozilla/5.0 Chrome/153.0.0.0"

    assert "--user-agent=Mozilla/5.0 Chrome/153.0.0.0" in chrome_host._chromium_command()


def test_the_command_needs_a_resolved_binary() -> None:
    with pytest.raises(RuntimeError, match="chromium_path not set"):
        ChromiumHost()._chromium_command()


# --- the DevTools endpoint ---


async def test_the_port_is_read_once_chromium_has_written_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Chromium creates the file before it writes the port: an empty read keeps polling."""
    host = ChromiumHost()
    host._user_data_dir = str(tmp_path)
    port_file = tmp_path / "DevToolsActivePort"
    port_file.write_text("")
    naps: list[float] = []

    async def _nap(seconds: float) -> None:
        naps.append(seconds)
        port_file.write_text("9333\n/devtools/browser/abc\n")

    monkeypatch.setattr(chromium.asyncio, "sleep", _nap)

    assert await host._read_devtools_port() == 9333
    assert naps == [chromium._CDP_READY_POLL_SECONDS]


async def test_a_chromium_that_exits_before_publishing_its_port_fails_loud(
    tmp_path: Path,
) -> None:
    host = ChromiumHost()
    host._user_data_dir = str(tmp_path)
    host._proc = cast(asyncio.subprocess.Process, _Proc(returncode=1))

    with pytest.raises(RuntimeError, match="exited before publishing"):
        await host._read_devtools_port()


async def test_a_port_that_never_appears_times_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    host = ChromiumHost()
    host._user_data_dir = str(tmp_path)
    monkeypatch.setattr(chromium, "_CDP_READY_TIMEOUT_SECONDS", 0.0)

    with pytest.raises(RuntimeError, match="did not write DevToolsActivePort"):
        await host._read_devtools_port()


async def test_reading_the_port_needs_a_profile() -> None:
    with pytest.raises(RuntimeError, match="user_data_dir not set"):
        await ChromiumHost()._read_devtools_port()


async def test_chromium_is_found_on_the_port_it_wrote(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chromium.browser_host_settings, "BROWSER_ENGINE", BrowserEngine.CHROMIUM)
    host = ChromiumHost()
    host._read_devtools_port = AsyncMock(return_value=9333)  # type: ignore[method-assign]  # the port file is covered above
    polled: list[tuple[int, str]] = []

    async def _poll(port: int, engine: str) -> str:
        polled.append((port, engine))
        return "ws://127.0.0.1:9333/devtools/browser/abc"

    host._poll_devtools_endpoint = _poll  # type: ignore[method-assign]  # the HTTP poll is covered below

    assert await host._await_cdp_ready() == "ws://127.0.0.1:9333/devtools/browser/abc"
    assert polled == [(9333, "Chromium")]


async def test_an_endpoint_that_never_answers_names_the_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(chromium, "_CDP_READY_TIMEOUT_SECONDS", 0.0)

    with pytest.raises(RuntimeError, match="^Chromium did not expose its CDP endpoint in time$"):
        await ChromiumHost()._poll_devtools_endpoint(9333, "Chromium")


# --- launch and shutdown ---


async def test_a_launch_samples_the_engine_it_started_and_dials_its_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(chromium.browser_host_settings, "BROWSER_ENGINE", BrowserEngine.CHROMIUM)
    proc = _Proc(pid=777)
    spawned: list[tuple[tuple[str, ...], dict[str, Any]]] = []

    async def _spawn(*args: str, **kwargs: Any) -> _Proc:
        spawned.append((args, kwargs))
        return proc

    monkeypatch.setattr(chromium.asyncio, "create_subprocess_exec", _spawn)
    sampled: list[int] = []
    monkeypatch.setattr(
        chromium.ProcessSampler, "for_pid", lambda pid: sampled.append(pid) or _sampler(1.0)
    )
    root = install_mux(monkeypatch)
    host = ChromiumHost()
    host._chromium_command = lambda: ["chrome", "--headless"]  # type: ignore[method-assign]  # the argv is covered above
    host._await_cdp_ready = AsyncMock(return_value="ws://127.0.0.1:9333/devtools/browser/r")  # type: ignore[method-assign]  # the endpoint is covered above

    await host._launch()

    ((args, kwargs),) = spawned
    assert args == ("chrome", "--headless")
    assert kwargs == {"env": None, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    assert sampled == [777]
    assert host.root_ws_url == "ws://127.0.0.1:9333/devtools/browser/r"
    assert root.urls == ["ws://127.0.0.1:9333/devtools/browser/r"]
    assert root.started == 1
    assert host._root_mux is cast(CdpMux, root)


async def test_shutdown_closes_the_root_and_terminates_the_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host = ChromiumHost()
    root = FakeMux()
    host._root_mux = cast(CdpMux, root)
    proc = _Proc()
    host._proc = cast(asyncio.subprocess.Process, proc)
    host._root_ws_url = "ws://x"
    host._sampler = _sampler(1.0)
    budgets: list[float | None] = []
    real_wait_for = asyncio.wait_for

    async def _wait_for(awaitable: Any, timeout: float | None) -> Any:
        budgets.append(timeout)
        return await real_wait_for(awaitable, timeout)

    monkeypatch.setattr(chromium.asyncio, "wait_for", _wait_for)

    await host._shutdown_chromium()

    assert root.closed
    assert (proc.terminated, proc.killed) == (True, False)
    assert budgets == [5]
    assert (host._root_mux, host._proc, host._root_ws_url, host._sampler) == (
        None,
        None,
        None,
        None,
    )


async def test_an_engine_that_ignores_terminate_is_killed() -> None:
    host = ChromiumHost()
    proc = _Proc()
    proc.ignores_terminate = True
    host._proc = cast(asyncio.subprocess.Process, proc)

    await host._shutdown_chromium()

    assert (proc.terminated, proc.killed) == (True, True)


async def test_an_engine_that_already_exited_is_not_signalled() -> None:
    host = ChromiumHost()
    proc = _Proc(returncode=0)
    host._proc = cast(asyncio.subprocess.Process, proc)

    await host._shutdown_chromium()

    assert (proc.terminated, proc.killed) == (False, False)


async def test_a_root_connection_that_fails_to_close_is_warned_about_and_dropped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host = ChromiumHost()
    root = MagicMock()
    root.close = AsyncMock(side_effect=ConnectionResetError())
    host._root_mux = root
    logger = MagicMock()
    monkeypatch.setattr(chromium, "log", logger)

    await host._shutdown_chromium()

    logger.warning.assert_called_once_with(
        f"{LogTag.BROWSER} browser host CDP stop failed", error_type="ConnectionResetError"
    )
    assert host._root_mux is None


# --- start and stop ---


async def test_a_fresh_host_is_down_and_stops_cleanly(monkeypatch: pytest.MonkeyPatch) -> None:
    logger = MagicMock()
    monkeypatch.setattr(chromium, "log", logger)
    host = ChromiumHost()

    assert host.chromium_up is False
    await host.stop()

    logger.warning.assert_not_called()
    assert (host._reaper_task, host._watcher_task) == (None, None)


async def test_start_measures_the_engine_it_launched_and_starts_its_watchers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(chromium.browser_host_settings, "BROWSER_ENGINE", BrowserEngine.OBSCURA)
    host = ChromiumHost()
    running = {"watcher": asyncio.Event(), "reaper": asyncio.Event()}

    async def _launch() -> None:
        host._sampler = _sampler(250.0)

    async def _loop(name: str) -> None:
        running[name].set()
        await asyncio.Event().wait()

    host._launch = _launch  # type: ignore[method-assign]  # the launch is covered above
    host._watch_loop = lambda: _loop("watcher")  # type: ignore[method-assign]  # loops are covered below
    host._reaper_loop = lambda: _loop("reaper")  # type: ignore[method-assign]  # loops are covered below

    await host.start()
    await asyncio.wait_for(asyncio.gather(*(e.wait() for e in running.values())), 1.0)

    assert host._base_memory_mb == 250.0
    host._shutdown_chromium = AsyncMock()  # type: ignore[method-assign]  # nothing real to stop
    await host.stop()
    assert (host._reaper_task, host._watcher_task) == (None, None)


async def test_start_on_an_engine_it_cannot_sample_takes_no_baseline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(chromium.browser_host_settings, "BROWSER_ENGINE", BrowserEngine.OBSCURA)
    host = ChromiumHost()
    host._launch = AsyncMock()  # type: ignore[method-assign]  # launches nothing, so no sampler
    host._watch_loop = AsyncMock()  # type: ignore[method-assign]  # loops are covered below
    host._reaper_loop = AsyncMock()  # type: ignore[method-assign]  # loops are covered below

    await host.start()

    assert host._base_memory_mb == 0.0


async def test_the_headless_check_needs_a_root_connection() -> None:
    with pytest.raises(RuntimeError, match="the engine has no root connection"):
        await ChromiumHost()._relaunch_without_headless_marker()


# --- admission ---


@pytest.fixture
def watermark(monkeypatch: pytest.MonkeyPatch) -> None:
    """Admit up to 900 MB of a 1000 MB box, each session costing the 50 MB floor."""
    monkeypatch.setattr(chromium.browser_host_settings, "BROWSER_HOST_MEMORY_HIGH_WATERMARK", 0.9)
    monkeypatch.setattr(chromium.browser_host_settings, "BROWSER_HOST_MAX_SESSIONS", 0)


def _memory(monkeypatch: pytest.MonkeyPatch, *readings: tuple[float, float]) -> None:
    queue = list(readings)
    monkeypatch.setattr(
        chromium, "memory_usage_mb", lambda: queue.pop(0) if len(queue) > 1 else queue[0]
    )


@pytest.mark.usefixtures("watermark")
async def test_a_create_is_admitted_up_to_the_watermark_exactly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _memory(monkeypatch, (850.0, 1000.0))
    host = make_host()

    await host._reserve_slot()

    assert host._pending_slots == 1


@pytest.mark.usefixtures("watermark")
async def test_a_create_past_the_watermark_is_refused_with_the_numbers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _memory(monkeypatch, (851.0, 1000.0))
    host = make_host()

    with pytest.raises(AtCapacityError) as err:
        await host._reserve_slot()

    assert str(err.value) == "at capacity (memory)"
    assert err.value.gate is HostAdmissionRefusal.MEMORY
    assert (err.value.used_mb, err.value.limit_mb, err.value.projected_mb) == (851.0, 1000.0, 901.0)
    assert (err.value.sessions, err.value.pending) == (0, 0)


@pytest.mark.usefixtures("watermark")
async def test_every_create_in_flight_reserves_its_cost(monkeypatch: pytest.MonkeyPatch) -> None:
    host = make_host()
    host._pending_slots = 1
    _memory(monkeypatch, (800.0, 1000.0))
    await host._reserve_slot()

    _memory(monkeypatch, (751.0, 1000.0))
    with pytest.raises(AtCapacityError) as err:
        await host._reserve_slot()

    assert (err.value.projected_mb, err.value.pending) == (901.0, 2)


@pytest.mark.usefixtures("watermark")
async def test_a_ceiling_of_zero_turns_the_backstop_off(monkeypatch: pytest.MonkeyPatch) -> None:
    host = make_host()
    host._sessions = {"s1": make_session("s1")}
    _memory(monkeypatch, (100.0, 1000.0))

    await host._reserve_slot()

    assert host._pending_slots == 1


@pytest.mark.usefixtures("watermark")
async def test_a_ceiling_of_one_admits_a_single_session(monkeypatch: pytest.MonkeyPatch) -> None:
    """The fallback host runs with a ceiling of one."""
    monkeypatch.setattr(chromium.browser_host_settings, "BROWSER_HOST_MAX_SESSIONS", 1)
    host = make_host()
    host._sessions = {"s1": make_session("s1")}
    _memory(monkeypatch, (100.0, 1000.0))

    with pytest.raises(AtCapacityError) as err:
        await host._reserve_slot()

    assert err.value.gate is HostAdmissionRefusal.SESSION_CEILING


@pytest.mark.usefixtures("watermark")
async def test_under_pressure_a_create_waits_for_memory_to_free(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Graceful slowdown: an idle reap mid-wait admits the create instead of a 429."""
    monkeypatch.setattr(chromium, "_ADMISSION_WAIT_SECONDS", 5.0)
    _memory(monkeypatch, (900.0, 1000.0), (100.0, 1000.0))
    naps: list[float] = []

    async def _nap(seconds: float) -> None:
        naps.append(seconds)

    monkeypatch.setattr(chromium.asyncio, "sleep", _nap)
    host = make_host()

    await host._reserve_slot()

    assert naps == [chromium._ADMISSION_POLL_SECONDS]
    assert host._pending_slots == 1


def test_the_next_sessions_cost_is_the_measured_average_over_the_launch_baseline() -> None:
    host = make_host()
    host._sampler = _sampler(500.0)
    host._base_memory_mb = 100.0
    host._sessions = {"a": make_session("a"), "b": make_session("b")}

    assert host._estimate_session_cost_mb() == 200.0


@pytest.mark.parametrize(
    ("rss_mb", "sessions"),
    [(160.0, 2), (None, 2), (500.0, 0)],
    ids=["below-floor", "unsampled", "no-sessions"],
)
def test_the_next_sessions_cost_never_drops_below_the_floor(
    rss_mb: float | None, sessions: int
) -> None:
    host = make_host()
    host._sampler = _sampler(rss_mb)
    host._base_memory_mb = 100.0
    host._sessions = {str(i): make_session(str(i)) for i in range(sessions)}

    assert host._estimate_session_cost_mb() == 50.0


def test_a_fresh_host_measures_cost_from_zero() -> None:
    host = make_host()
    host._sampler = _sampler(400.0)
    host._sessions = {"a": make_session("a"), "b": make_session("b")}

    assert host._estimate_session_cost_mb() == 200.0


# --- the engine's own memory ---


class _PsProcess:
    def __init__(self, rss: int, children: list[_PsProcess] | None = None, *, broken: bool = False):
        self._rss = rss
        self._children = children or []
        self._broken = broken

    def memory_info(self) -> Any:
        if self._broken:
            raise psutil.NoSuchProcess(1)
        return MagicMock(rss=self._rss)

    def children(self, recursive: bool = False) -> list[_PsProcess]:
        assert recursive, "renderers are grandchildren of the browser process"
        return self._children


def test_the_engines_memory_is_its_whole_process_tree(monkeypatch: pytest.MonkeyPatch) -> None:
    tree = _PsProcess(
        100 * _MB, [_PsProcess(50 * _MB), _PsProcess(0, broken=True), _PsProcess(25 * _MB)]
    )
    monkeypatch.setattr(
        chromium.psutil, "Process", lambda pid: tree if pid == 4242 else _PsProcess(0, broken=True)
    )
    host = make_host()
    host._proc = cast(asyncio.subprocess.Process, _Proc(pid=4242))

    assert host.engine_rss_mb() == 175.0


def test_an_engine_that_vanished_has_no_memory_reading(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chromium.psutil, "Process", lambda pid: _PsProcess(0, broken=True))

    assert make_host().engine_rss_mb() is None


@pytest.mark.parametrize("proc", [None, _Proc(returncode=0)], ids=["never-started", "exited"])
def test_an_engine_that_is_not_running_has_no_memory_reading(proc: _Proc | None) -> None:
    host = ChromiumHost()
    host._proc = cast(asyncio.subprocess.Process, proc)

    assert host.engine_rss_mb() is None


def test_the_sampler_reading_is_the_engines_rss() -> None:
    host = make_host()
    host._sampler = _sampler(321.0)
    assert host._engine_rss_mb() == 321.0

    host._sampler = _sampler(None)
    assert host._engine_rss_mb() is None


# --- recycling a bloated idle engine ---


@pytest.fixture
def recyclable(monkeypatch: pytest.MonkeyPatch) -> ChromiumHost:
    monkeypatch.setattr(chromium.browser_host_settings, "BROWSER_ENGINE_RECYCLE_MB", 1500)
    host = make_host()
    host._shutdown_chromium = AsyncMock()  # type: ignore[method-assign]  # nothing real to stop
    host._launch = AsyncMock()  # type: ignore[method-assign]  # nothing real to launch
    return host


def _rss(host: ChromiumHost, monkeypatch: pytest.MonkeyPatch, rss_mb: float | None) -> None:
    monkeypatch.setattr(host, "engine_rss_mb", lambda: rss_mb)


async def test_an_idle_engine_over_its_limit_is_relaunched(
    recyclable: ChromiumHost, monkeypatch: pytest.MonkeyPatch
) -> None:
    _rss(recyclable, monkeypatch, 1600.4)
    logger = MagicMock()
    monkeypatch.setattr(chromium, "log", logger)

    await recyclable._recycle_if_bloated()

    cast(AsyncMock, recyclable._shutdown_chromium).assert_awaited_once()
    cast(AsyncMock, recyclable._launch).assert_awaited_once()
    logger.warning.assert_called_once_with(
        f"{LogTag.BROWSER} browser engine recycled over its idle memory limit",
        browser={"operation": "recycle", "rss_mb": 1600, "limit_mb": 1500},
    )


@pytest.mark.parametrize("rss_mb", [1500.0, None], ids=["at-the-limit", "unreadable"])
async def test_an_engine_within_its_limit_is_left_running(
    recyclable: ChromiumHost, monkeypatch: pytest.MonkeyPatch, rss_mb: float | None
) -> None:
    _rss(recyclable, monkeypatch, rss_mb)

    await recyclable._recycle_if_bloated()

    cast(AsyncMock, recyclable._launch).assert_not_awaited()


async def test_an_engine_serving_a_session_is_never_recycled(
    recyclable: ChromiumHost, monkeypatch: pytest.MonkeyPatch
) -> None:
    _rss(recyclable, monkeypatch, 9999.0)
    recyclable._sessions = {"s1": make_session("s1")}

    await recyclable._recycle_if_bloated()

    cast(AsyncMock, recyclable._launch).assert_not_awaited()


async def test_recycling_can_be_turned_off(
    recyclable: ChromiumHost, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(chromium.browser_host_settings, "BROWSER_ENGINE_RECYCLE_MB", None)
    _rss(recyclable, monkeypatch, 9999.0)

    await recyclable._recycle_if_bloated()

    cast(AsyncMock, recyclable._launch).assert_not_awaited()


async def test_a_host_that_is_stopping_is_not_recycled(
    recyclable: ChromiumHost, monkeypatch: pytest.MonkeyPatch
) -> None:
    _rss(recyclable, monkeypatch, 9999.0)
    recyclable._stopping.set()

    await recyclable._recycle_if_bloated()

    cast(AsyncMock, recyclable._launch).assert_not_awaited()


async def test_a_session_that_arrives_while_waiting_to_recycle_stops_it(
    recyclable: ChromiumHost, monkeypatch: pytest.MonkeyPatch
) -> None:
    _rss(recyclable, monkeypatch, 9999.0)
    await recyclable._recover_lock.acquire()
    recycle = asyncio.create_task(recyclable._recycle_if_bloated())
    await asyncio.sleep(0)
    recyclable._sessions = {"s1": make_session("s1")}
    recyclable._recover_lock.release()
    await recycle

    cast(AsyncMock, recyclable._launch).assert_not_awaited()


# --- the reaper ---


async def _run_reaper(
    host: ChromiumHost, monkeypatch: pytest.MonkeyPatch, sweeps: int
) -> list[float]:
    """Run the reaper loop for a number of sweeps; return the naps it took between them."""
    naps: list[float] = []

    async def _nap(seconds: float) -> None:
        naps.append(seconds)
        if len(naps) > sweeps:
            raise asyncio.CancelledError

    monkeypatch.setattr(chromium.asyncio, "sleep", _nap)
    with pytest.raises(asyncio.CancelledError):
        await host._reaper_loop()
    return naps


async def test_the_reaper_sweeps_idle_sessions_then_bloat_every_interval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host = make_host()
    host._reap_idle = AsyncMock()  # type: ignore[method-assign]  # covered in test_chromium_contexts
    host._recycle_if_bloated = AsyncMock()  # type: ignore[method-assign]  # covered above
    host._recover_crash = AsyncMock()  # type: ignore[method-assign]  # nothing crashed

    naps = await _run_reaper(host, monkeypatch, sweeps=2)

    assert naps == [chromium._REAPER_INTERVAL_SECONDS] * 3
    assert cast(AsyncMock, host._reap_idle).await_count == 2
    assert cast(AsyncMock, host._recycle_if_bloated).await_count == 2
    cast(AsyncMock, host._recover_crash).assert_not_awaited()


async def test_the_reaper_recovers_a_dead_engine_instead_of_sweeping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host = ChromiumHost()
    host._reap_idle = AsyncMock()  # type: ignore[method-assign]  # must not run on a dead engine
    host._recover_crash = AsyncMock()  # type: ignore[method-assign]  # recovery is covered elsewhere

    await _run_reaper(host, monkeypatch, sweeps=1)

    cast(AsyncMock, host._recover_crash).assert_awaited_once()
    cast(AsyncMock, host._reap_idle).assert_not_awaited()


async def test_a_failed_sweep_is_logged_and_the_reaper_keeps_going(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host = make_host()
    host._reap_idle = AsyncMock(side_effect=[RuntimeError("boom"), None])  # type: ignore[method-assign]  # one bad sweep
    host._recycle_if_bloated = AsyncMock()  # type: ignore[method-assign]  # covered above
    logger = MagicMock()
    monkeypatch.setattr(chromium, "log", logger)

    await _run_reaper(host, monkeypatch, sweeps=2)

    assert cast(AsyncMock, host._reap_idle).await_count == 2
    logger.error.assert_called_once_with(
        f"{LogTag.BROWSER} browser host reaper sweep failed", error_type="RuntimeError"
    )


# --- activity and viewers ---


def test_touch_marks_a_session_active_now() -> None:
    host = make_host()
    host._sessions = {"s1": make_session("s1", last_activity_at=0.0)}

    host.touch("s1")
    host.touch("unknown")

    assert host._sessions["s1"].last_activity_at > 0.0


def test_a_viewer_keeps_a_session_counted_until_it_leaves() -> None:
    host = make_host()
    session = make_session("s1", last_activity_at=0.0)
    host._sessions = {"s1": session}

    host.add_viewer("s1")
    host.add_viewer("s1")
    watched = (session.viewer_count, session.last_activity_at)
    session.last_activity_at = 0.0
    host.remove_viewer("s1")
    one_left = session.viewer_count
    host.remove_viewer("s1")
    host.remove_viewer("s1")
    host.add_viewer("unknown")
    host.remove_viewer("unknown")

    assert watched[0] == 2
    assert watched[1] > 0.0
    assert one_left == 1
    assert session.viewer_count == 0
    assert session.last_activity_at > 0.0


# --- the process watcher and liveness ---


async def test_an_engine_exit_is_reported_with_its_return_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host = ChromiumHost()
    host._proc = cast(asyncio.subprocess.Process, _Proc(returncode=-11))
    logger = MagicMock()
    monkeypatch.setattr(chromium, "log", logger)

    async def _recover() -> None:
        host._stopping.set()

    host._recover_crash = _recover  # type: ignore[method-assign]  # one recovery, then the loop exits

    await host._watch_loop()

    logger.error.assert_called_once_with(
        f"{LogTag.BROWSER} browser engine process exited",
        browser={"operation": "crash_detect", "returncode": -11},
    )


async def test_an_unanswered_liveness_probe_is_logged_with_its_cause(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host = make_host()
    root = FakeMux()
    root.send_error = ConnectionResetError()
    host._root_mux = cast(CdpMux, root)
    logger = MagicMock()
    monkeypatch.setattr(chromium, "log", logger)

    assert await host._engine_responsive(1.0) is False

    logger.error.assert_called_once_with(
        f"{LogTag.BROWSER} browser host CDP is unresponsive", error_type="ConnectionResetError"
    )
