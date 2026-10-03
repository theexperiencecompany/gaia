"""One running browser engine: its process, its root CDP connection, and how it fails.

An engine is launched whole or not at all. It fails one of three ways: its
process exits, its root connection drops, or it stops answering on that
connection, which no page's work can hold up. The host keeps one engine taking
new sessions and lets a recycled one drain beside it, so each knows only itself.
"""

from __future__ import annotations

import asyncio
import base64
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
import hashlib
from pathlib import Path
import shutil
import tempfile

from browser_use.browser.profile import CHROME_DEFAULT_ARGS
from cryptography import x509
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from playwright.sync_api import sync_playwright

from app.browser_host.cdp_mux import CdpMux, cdp_call
from app.browser_host.obscura_launch import launch_obscura
from app.browser_host.process import (
    ProcessSampler,
    process_tree_rss_mb,
    spawn_engine,
    stop_process,
    until_published,
)
from app.config.browser_host_settings import browser_host_settings
from app.constants.browser import (
    BROWSER_HOST_LIVENESS_TIMEOUT_SECONDS,
    BROWSER_VIEWPORT_HEIGHT,
    BROWSER_VIEWPORT_WIDTH,
    BrowserEngine,
    EngineExit,
)
from app.constants.log_tags import LogTag
from shared.py.wide_events import log

# Flags beyond browser-use's CHROME_DEFAULT_ARGS. --no-sandbox is a deliberate gap:
# the renderer sandbox needs unprivileged user namespaces the container lacks.
# Compensating controls: browser-only network island, per-context download deny, http(s)-only proxy.
_HOST_EXTRA_ARGS: tuple[str, ...] = ("--no-sandbox",)
# Playwright names the shell binary per platform: headless_shell on Linux (what
# production runs), chrome-headless-shell on macOS, .exe on Windows.
_HEADLESS_SHELL_BINARIES = ("headless_shell", "chrome-headless-shell", "headless_shell.exe")
# How a headless build names itself in its User-Agent ("HeadlessChrome/153.0.0.0").
_HEADLESS_MARKER = "HeadlessChrome/"
# Per-renderer V8 heap ceiling: one runaway page must not OOM every other user's session.
_JS_HEAP_MB = 512
# A wedged engine stays alive and silent, so its root connection is asked on a
# timer; this many unanswered asks in a row is a dead engine, not a busy one.
_LIVENESS_PROBE_INTERVAL_SECONDS = 15.0
_LIVENESS_STRIKES = 2


def _headless_shell_beside(chromium: Path) -> Path | None:
    """Playwright's headless-shell build for the same revision, if it is installed."""
    for parent in chromium.parents:
        if not parent.name.startswith("chromium-"):
            continue
        shell_root = (
            parent.parent / f"chromium_headless_shell-{parent.name.removeprefix('chromium-')}"
        )
        if not shell_root.is_dir():
            return None
        for name in _HEADLESS_SHELL_BINARIES:
            found = next((p for p in shell_root.rglob(name) if p.is_file()), None)
            if found is not None:
                return found
        return None
    return None


def resolve_chromium_path() -> str:
    """Resolve the browser binary: CHROMIUM_BIN when set, else Playwright's headless shell.

    The shell build drops the browser-UI layer (three contexts: 702 MB versus
    1419 MB). Playwright's resolver is sync-only, so call this in a worker thread.
    """
    if browser_host_settings.CHROMIUM_BIN:
        configured = Path(browser_host_settings.CHROMIUM_BIN)
        if not configured.is_file():
            raise RuntimeError(f"CHROMIUM_BIN is set but is not a file: {configured}")
        return str(configured)
    with sync_playwright() as p:
        full = Path(p.chromium.executable_path)
    shell = _headless_shell_beside(full)
    return str(shell or full)


def spki_pin(pem_path: str) -> str:
    """Return a PEM certificate's SPKI pin as Chrome reads one: base64 of its key's SHA-256."""
    certificate = x509.load_pem_x509_certificate(Path(pem_path).read_bytes())
    key = certificate.public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
    return base64.b64encode(hashlib.sha256(key).digest()).decode()


def chromium_argv(chromium_path: str, profile_dir: str, user_agent: str | None) -> list[str]:
    """Build the full Chromium argv for one launch into its own fresh profile."""
    args = [chromium_path, "--remote-debugging-port=0", f"--user-data-dir={profile_dir}"]
    args.extend(CHROME_DEFAULT_ARGS)
    args.extend(_HOST_EXTRA_ARGS)
    # Bounds the JS heap only (DOM, images and raster live outside V8): a ceiling, not a saving.
    args.append(f"--js-flags=--max-old-space-size={_JS_HEAP_MB}")
    # The window is the viewport, so pages paint edge to edge instead of into 800x600.
    args.append(f"--window-size={BROWSER_VIEWPORT_WIDTH},{BROWSER_VIEWPORT_HEIGHT}")
    if browser_host_settings.BROWSER_HOST_TEST_CA_FILE:
        # A test stack's fixture site: its chain carries this CA, whose key Chrome then accepts.
        args.append(
            f"--ignore-certificate-errors-spki-list={spki_pin(browser_host_settings.BROWSER_HOST_TEST_CA_FILE)}"
        )
    if user_agent is not None:
        args.append(f"--user-agent={user_agent}")
    if not browser_host_settings.BROWSER_HOST_HEADED:
        # The shell build is headless by construction and only knows the bare flag.
        is_shell = Path(chromium_path).name in _HEADLESS_SHELL_BINARIES
        args.append("--headless" if is_shell else "--headless=new")
    return args


def _devtools_file_reader(profile_dir: str) -> Callable[[], Awaitable[str | None]]:
    """Read Chromium's root websocket URL from the DevToolsActivePort file it writes once listening.

    The file holds the port and the browser endpoint's path; it is created before
    it is written, so a partial read means "not yet".
    """
    port_file = Path(profile_dir) / "DevToolsActivePort"

    async def read() -> str | None:
        lines = port_file.read_text().splitlines() if port_file.exists() else []
        if len(lines) < 2 or not lines[0].strip().isdigit():
            return None
        return f"ws://127.0.0.1:{lines[0].strip()}{lines[1].strip()}"

    return read


@dataclass(eq=False, slots=True)
class Engine:
    """A launched engine process and the root connection every session dials beside."""

    kind: BrowserEngine
    proc: asyncio.subprocess.Process
    root_mux: CdpMux
    root_ws_url: str
    profile_dir: str | None
    sampler: ProcessSampler | None
    # Engine-tree RSS with no session open: what the per-session estimate subtracts.
    base_rss_mb: float

    @classmethod
    async def launch(
        cls, kind: BrowserEngine, chromium_path: str | None, user_agent: str | None
    ) -> Engine:
        """Start an engine and its root connection; nothing is left running when this raises."""
        profile_dir: str | None = None
        proc: asyncio.subprocess.Process | None = None
        try:
            if kind is BrowserEngine.OBSCURA:
                launched = await launch_obscura()
                proc, root_ws_url = launched.proc, launched.ws_url
            else:
                if chromium_path is None:
                    raise RuntimeError("chromium_path not resolved")
                profile_dir = tempfile.mkdtemp(prefix="gaia-browser-host-")
                proc = await spawn_engine(
                    chromium_argv(chromium_path, profile_dir, user_agent), None
                )
                root_ws_url = await until_published(proc, _devtools_file_reader(profile_dir))
            root_mux = CdpMux(root_ws_url)
            await root_mux.start()
        except BaseException:
            if proc is not None:
                await stop_process(proc)
            await _remove_profile(profile_dir)
            raise
        engine = cls(
            kind=kind,
            proc=proc,
            root_mux=root_mux,
            root_ws_url=root_ws_url,
            profile_dir=profile_dir,
            sampler=ProcessSampler.for_pid(proc.pid),
            base_rss_mb=0.0,
        )
        engine.base_rss_mb = engine.rss_mb() or 0.0
        return engine

    @property
    def alive(self) -> bool:
        """Whether the process runs and its root connection is open."""
        return self.proc.returncode is None and not self.root_mux.closed

    async def user_agent(self) -> str:
        """Return the User-Agent the engine announces."""
        return str((await cdp_call(self.root_mux, "Browser.getVersion"))["userAgent"])

    async def responsive(self, timeout: float) -> bool:
        """Whether the engine answers a round-trip on its root connection within timeout."""
        if not self.alive:
            return False
        try:
            await cdp_call(self.root_mux, "Target.getTargets", timeout=timeout)
        except Exception as exc:
            log.error(
                f"{LogTag.BROWSER} browser host CDP is unresponsive",
                error_type=type(exc).__name__,
            )
            return False
        return True

    def rss_mb(self) -> float | None:
        """Resident memory of the engine's process tree, or None when it cannot be read."""
        return process_tree_rss_mb(self.proc.pid)

    async def wait_failed(self) -> EngineExit:
        """Return once the engine has stopped serving, saying how."""
        watches = {
            asyncio.ensure_future(self.proc.wait()): EngineExit.PROCESS_EXITED,
            asyncio.ensure_future(self.root_mux.wait_closed()): EngineExit.CONNECTION_CLOSED,
            asyncio.ensure_future(self._stops_answering()): EngineExit.STOPPED_ANSWERING,
        }
        try:
            done, _ = await asyncio.wait(list(watches), return_when=asyncio.FIRST_COMPLETED)
        finally:
            for watch in watches:
                watch.cancel()
        return watches[next(iter(done))]

    async def _stops_answering(self) -> None:
        strikes = 0
        while strikes < _LIVENESS_STRIKES:
            await asyncio.sleep(_LIVENESS_PROBE_INTERVAL_SECONDS)
            answered = await self.responsive(BROWSER_HOST_LIVENESS_TIMEOUT_SECONDS)
            strikes = 0 if answered else strikes + 1

    async def shutdown(self, *, graceful: bool = True) -> None:
        """Stop the process tree, close the root connection, and delete its profile.

        Not graceful for a failed engine: a frozen process never acts on a polite request.
        """
        await stop_process(self.proc, graceful=graceful)
        await self.root_mux.close()
        await _remove_profile(self.profile_dir)


async def launch_engine(
    kind: BrowserEngine, chromium_path: str | None, user_agent: str | None
) -> tuple[Engine, str | None]:
    """Launch an engine, returning it and the User-Agent every later Chromium launch must announce.

    Headless Chromium sends "HeadlessChrome/<v>" in every User-Agent, which sites
    read as a bot (DuckDuckGo answered with a CAPTCHA); the first launch learns
    the plain form and relaunches once with it, keeping the client-hint brands.
    """
    engine = await Engine.launch(kind, chromium_path, user_agent)
    if kind is BrowserEngine.OBSCURA or user_agent is not None:
        return engine, user_agent
    announced = await engine.user_agent()
    if _HEADLESS_MARKER not in announced:
        return engine, announced
    plain = announced.replace(_HEADLESS_MARKER, "Chrome/")
    await engine.shutdown()
    return await Engine.launch(kind, chromium_path, plain), plain


async def _remove_profile(profile_dir: str | None) -> None:
    """Delete a launch's Chromium profile; every launch makes a fresh one."""
    if profile_dir is None:
        return
    try:
        await asyncio.to_thread(shutil.rmtree, profile_dir)
    except OSError as exc:
        log.warning(f"{LogTag.BROWSER} browser profile not removed", error_type=type(exc).__name__)
