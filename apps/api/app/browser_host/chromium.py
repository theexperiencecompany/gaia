"""One long-lived Chromium, one isolated browser context per session.

The host launches a single Chromium and multiplexes every session onto its own
``Target.createBrowserContext`` — the proven isolation primitive (see
``scratchpad/ctx_proof.py``): cookies and storage never cross contexts, yet a
second context costs a fraction of a second Chromium. All context lifecycle
(create / seed / dump / dispose) flows through one root CDP connection.

``ChromiumHost`` owns:
  * the Chromium subprocess and its root CDP client,
  * the live session registry (context id, primary page, activity, viewers),
  * an idle reaper that disposes untouched, unwatched contexts,
  * crash recovery: a dead Chromium is relaunched and its sessions marked dead.
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass, field
import json
from pathlib import Path
import subprocess
import tempfile
import time
from typing import Any
import uuid

from browser_use.browser.profile import CHROME_DEFAULT_ARGS
from cdp_use.client import CDPClient
import httpx
from playwright.sync_api import StorageState, StorageStateCookie, sync_playwright

from app.browser_host.metrics import ProcessSampler, SessionMetrics
from app.config.settings import settings
from app.constants.browser import (
    BROWSER_VIEWPORT_HEIGHT,
    BROWSER_VIEWPORT_WIDTH,
    BrowserEngine,
)
from app.constants.log_tags import LogTag
from app.services.browser.storage_state_types import LocalStorageEntry, OriginState
from shared.py.wide_events import log

# Extra flags on top of browser-use's CHROME_DEFAULT_ARGS: never phone home for
# component updates, and the two flags a containerized Chromium needs to run.
#
# --no-sandbox is a KNOWN, DELIBERATE gap, not an oversight. Chromium's renderer
# sandbox needs unprivileged user namespaces, which the container does not get:
# measured against chromedp/headless-shell, running as root refuses outright
# ("Running as root without --no-sandbox is not supported") and running as a
# non-root uid under Docker's default seccomp fails with "No usable sandbox!".
# Enabling it means relaxing seccomp/AppArmor or granting SYS_ADMIN — trading a
# renderer-escape risk for a container-escape one — so the real fix is an
# isolation boundary per session (container/microVM), not a flag flip. Until that
# lands, the compensating controls are: no data-plane network (compose puts this
# on a browser-only island), downloads denied per context, and an http(s)-only
# navigation allowlist in the CDP proxy.
_HOST_EXTRA_ARGS: tuple[str, ...] = (
    "--disable-component-update",
    "--no-sandbox",
    "--disable-dev-shm-usage",
)
# Playwright names the shell binary per platform: `headless_shell` on Linux (what
# production runs), `chrome-headless-shell` on macOS, `.exe` on Windows.
_HEADLESS_SHELL_BINARIES = ("headless_shell", "chrome-headless-shell", "headless_shell.exe")
# Poll budget for Chromium to publish its DevTools endpoint after launch.
_CDP_READY_TIMEOUT_SECONDS = 30.0
_CDP_READY_POLL_SECONDS = 0.2
# Every root-CDP round-trip is bounded. ``cdp_use.CDPClient.send_raw`` awaits its
# response future with no timeout of its own, so a wedged renderer (a blocking
# dialog, a hung GPU process) would otherwise freeze whoever awaits it — the
# session lock and the reaper included — while the process stays alive and looks
# healthy. Bounded calls turn "the host is gone for everyone" into "one request
# failed".
_CDP_CALL_TIMEOUT_SECONDS = 20.0
# The health probe backs a container healthcheck, so it must give up well inside
# the orchestrator's own timeout rather than share the generous call budget.
_CDP_HEALTH_TIMEOUT_SECONDS = 5.0
# How often the idle reaper wakes to sweep for dead/idle contexts.
_REAPER_INTERVAL_SECONDS = 15.0


@dataclass(slots=True)
class HostSession:
    """A single browser session: one isolated context with its primary page."""

    session_id: str
    context_id: str
    target_id: str
    created_at: float
    last_activity_at: float
    viewer_count: int = 0
    dead: bool = False
    metrics: SessionMetrics = field(default_factory=SessionMetrics)


class AtCapacityError(RuntimeError):
    """Raised when the host already holds ``BROWSER_HOST_MAX_SESSIONS`` contexts."""


class SessionNotFoundError(KeyError):
    """Raised when a session id is not (or no longer) live on the host."""


class CDPTimeoutError(RuntimeError):
    """Raised when a root-CDP call outruns its budget — Chromium is wedged, not busy."""


async def cdp_call(
    cdp: CDPClient,
    method: str,
    params: dict[str, Any] | None = None,
    *,
    session_id: str | None = None,
    timeout: float = _CDP_CALL_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """One CDP round-trip, bounded by ``timeout``.

    The single place the host talks to Chromium, so a wedged browser always
    raises :class:`CDPTimeoutError` instead of suspending its caller forever.
    """
    try:
        return await asyncio.wait_for(
            cdp.send_raw(method, params, session_id=session_id), timeout=timeout
        )
    except TimeoutError as exc:
        log.error(
            f"{LogTag.BROWSER} browser host CDP call timed out",
            error_type="CDPTimeoutError",
            browser={"cdp_method": method, "timeout_seconds": timeout},
        )
        raise CDPTimeoutError(method) from exc


def _headless_shell_beside(chromium: Path) -> Path | None:
    """Playwright's headless-shell build for the same revision, if it is installed."""
    for parent in chromium.parents:
        if not parent.name.startswith("chromium-"):
            continue
        shell_root = parent.parent / parent.name.replace("chromium-", "chromium_headless_shell-", 1)
        if not shell_root.is_dir():
            return None
        for name in _HEADLESS_SHELL_BINARIES:
            found = next((p for p in shell_root.rglob(name) if p.is_file()), None)
            if found is not None:
                return found
        return None
    return None


def _resolve_chromium_path() -> str:
    """The browser binary: the configured override, else Playwright's headless shell.

    Playwright installs ``chromium_headless_shell-<rev>`` beside the full browser,
    and that is the right binary for this host: it never shows a window, and the
    shell build drops the whole browser-UI layer. Measured at the same Chrome
    revision, three contexts open: 702 MB versus 1419 MB, and 340 MB versus
    756 MB idle. Falls back to the full browser when the shell is absent.

    Playwright's resolver uses its sync API, which refuses to run inside a
    running event loop — callers must invoke this in a worker thread.
    """
    override = settings.BROWSER_HOST_CHROMIUM_PATH
    if override:
        return str(override)

    with sync_playwright() as p:
        full = Path(p.chromium.executable_path)
    shell = _headless_shell_beside(full)
    return str(shell or full)


def _cdp_cookie_to_storage_state(cookie: dict[str, Any]) -> StorageStateCookie:
    """CDP ``Network.Cookie`` -> Playwright ``storage_state`` cookie shape."""
    out: StorageStateCookie = {
        "name": cookie["name"],
        "value": cookie["value"],
        "domain": cookie["domain"],
        "path": cookie["path"],
        "expires": cookie.get("expires", -1),
        "httpOnly": cookie.get("httpOnly", False),
        "secure": cookie.get("secure", False),
    }
    same_site = cookie.get("sameSite")
    if same_site:
        out["sameSite"] = same_site
    return out


def _storage_state_cookie_to_cdp(cookie: StorageStateCookie) -> dict[str, Any]:
    """Playwright ``storage_state`` cookie -> CDP ``Storage.setCookies`` param."""
    out: dict[str, Any] = {
        "name": cookie["name"],
        "value": cookie["value"],
        "domain": cookie["domain"],
        "path": cookie.get("path", "/"),
        "secure": cookie.get("secure", False),
        "httpOnly": cookie.get("httpOnly", False),
    }
    expires = cookie.get("expires")
    if expires is not None and expires > 0:
        out["expires"] = expires
    same_site = cookie.get("sameSite")
    if same_site:
        out["sameSite"] = same_site
    return out


class ChromiumHost:
    """Owns the single browser process and every live context on it.

    Named for its default engine, but fronts either Chromium (headless-shell) or
    the Obscura CDP server, selected by ``settings.BROWSER_ENGINE``. Everything
    past launch — contexts, the CDP client, proxy, screencast — speaks plain CDP
    and is identical for both."""

    def __init__(self) -> None:
        self._proc: asyncio.subprocess.Process | None = None
        self._cdp: CDPClient | None = None
        self._root_ws_url: str | None = None
        self._chromium_path: str | None = None
        self._user_data_dir: str | None = None
        self._sessions: dict[str, HostSession] = {}
        # Slots claimed by a create that has not finished its CDP work yet, so the
        # capacity check stays correct while that work happens outside the lock.
        self._pending_slots = 0
        self._sampler: ProcessSampler | None = None
        self._lock = asyncio.Lock()
        self._reaper_task: asyncio.Task[None] | None = None

    # --- lifecycle ---

    async def start(self) -> None:
        """Resolve the binary, launch the engine, connect CDP, start the reaper."""
        if settings.BROWSER_ENGINE is not BrowserEngine.OBSCURA:
            self._chromium_path = await asyncio.to_thread(_resolve_chromium_path)
        await self._launch()
        self._reaper_task = asyncio.create_task(self._reaper_loop())
        log.info(f"{LogTag.BROWSER} browser host started")

    async def stop(self) -> None:
        """Tear everything down: reaper, CDP client, Chromium process."""
        if self._reaper_task is not None:
            self._reaper_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reaper_task
            self._reaper_task = None
        await self._shutdown_chromium()
        log.info(f"{LogTag.BROWSER} browser host stopped")

    @property
    def root_ws_url(self) -> str:
        """Chromium's root CDP websocket URL (what the proxy/screencast dial)."""
        if self._root_ws_url is None:
            raise RuntimeError("browser host is not started")
        return self._root_ws_url

    @property
    def chromium_up(self) -> bool:
        """Whether the Chromium subprocess is currently alive."""
        return self._proc is not None and self._proc.returncode is None

    # --- session registry ---

    async def create_context(self, storage_state: StorageState | None) -> HostSession:
        """Create an isolated context (+ one blank page), optionally seeding cookies.

        Fails fast with :class:`AtCapacityError` once ``BROWSER_HOST_MAX_SESSIONS``
        contexts are live, so a caller gets a clean 429 instead of a Chromium that
        slowly runs out of memory.
        """
        await self._reserve_slot()
        context_id: str | None = None
        try:
            ctx = await self._cdp_call("Target.createBrowserContext", {"disposeOnDetach": False})
            context_id = str(ctx["browserContextId"])
            # Refuse downloads before the context can navigate anywhere: the agent
            # renders attacker-influenced pages, and a drive-by download is the
            # cheapest way to get a file onto the host's disk. Scoped to this
            # context so it can never race another session's setting.
            await self._cdp_call(
                "Browser.setDownloadBehavior",
                {"behavior": "deny", "browserContextId": context_id},
            )
            target = await self._cdp_call(
                "Target.createTarget",
                {"url": "about:blank", "browserContextId": context_id},
            )
            target_id: str = target["targetId"]

            if storage_state:
                await self._seed_cookies(context_id, storage_state)
                await self._seed_local_storage(target_id, storage_state)

            now = time.monotonic()
            session_id = uuid.uuid4().hex
            session = HostSession(
                session_id=session_id,
                context_id=context_id,
                target_id=target_id,
                created_at=now,
                last_activity_at=now,
            )
            async with self._lock:
                # Hand the reservation over to the session in ONE critical section.
                # Releasing it separately would leave a window where the create is
                # counted twice, and a concurrent caller would get a spurious 429
                # while a slot was actually free.
                self._sessions[session_id] = session
                self._pending_slots -= 1
            session.metrics.context_count += 1
            session.metrics.page_count += 1
            self.sample_resources(session_id)
        except BaseException:
            async with self._lock:
                self._pending_slots -= 1
            # A context that was created before the failure has no session to
            # carry it, so the idle reaper would never find it — drop it here.
            if context_id is not None:
                await self._dispose_context_id(context_id)
            raise

        log.set(browser={"session_id": session_id, "operation": "create"})
        log.info(f"{LogTag.BROWSER} browser context created")
        return session

    async def dispose_context(self, session_id: str) -> StorageState:
        """Dump the context's ``storage_state``, then dispose it. Returns the dump."""
        session = self._get(session_id)
        self.sample_resources(session_id)
        state: StorageState | None = None
        try:
            state = await self._dump_storage_state(session)
            return state
        finally:
            # Release the slot and the Chromium context even when the dump fails
            # or times out. A dump that hangs used to leave the session in the
            # registry forever, burning one of the few slots while the caller had
            # already timed out and moved on.
            async with self._lock:
                self._sessions.pop(session_id, None)
            await self._dispose_context_id(session.context_id)
            log.set(browser={"session_id": session_id, "operation": "dispose"})
            log.set_ns("browser", metrics=session.metrics.snapshot())
            if state is not None:
                log.info(f"{LogTag.BROWSER} browser context disposed")
            else:
                # The context is gone either way, but the user's saved login went
                # with it — that must not read as a clean disposal.
                log.error(
                    f"{LogTag.BROWSER} browser context disposed without saving its storage state",
                    error_type="StorageDumpFailed",
                )

    def get(self, session_id: str) -> HostSession | None:
        """The live session, or ``None`` if unknown/disposed."""
        return self._sessions.get(session_id)

    def touch(self, session_id: str) -> None:
        """Mark a session active now (called on any CDP/live-view traffic)."""
        session = self._sessions.get(session_id)
        if session is not None:
            session.last_activity_at = time.monotonic()

    def sample_resources(self, session_id: str) -> None:
        """Take one RSS/CPU reading for a session (create, navigation, dispose)."""
        session = self._sessions.get(session_id)
        if session is None or self._sampler is None:
            return
        reading = self._sampler.sample()
        if reading is not None:
            session.metrics.add_resource_sample(*reading)

    def note_navigation_started(self, session_id: str) -> None:
        """A ``Page.navigate`` command left the client (called by the CDP proxy)."""
        session = self._sessions.get(session_id)
        if session is not None:
            session.metrics.start_navigation()

    def note_navigation_finished(self, session_id: str) -> None:
        """A load event came back; closes the timing and samples resources."""
        session = self._sessions.get(session_id)
        if session is None or session.metrics.finish_navigation() is None:
            return
        self.sample_resources(session_id)

    def note_page_created(self, session_id: str) -> None:
        """A ``Target.createTarget`` opened another page inside this session."""
        session = self._sessions.get(session_id)
        if session is not None:
            session.metrics.page_count += 1

    def add_viewer(self, session_id: str) -> None:
        """Register a live-view watcher so the reaper won't dispose the session."""
        session = self._sessions.get(session_id)
        if session is not None:
            session.viewer_count += 1
            session.last_activity_at = time.monotonic()

    def remove_viewer(self, session_id: str) -> None:
        """Deregister a live-view watcher on disconnect."""
        session = self._sessions.get(session_id)
        if session is not None:
            session.viewer_count = max(0, session.viewer_count - 1)
            session.last_activity_at = time.monotonic()

    async def session_info(self, session_id: str) -> dict[str, Any]:
        """The GET ``/sessions/{id}`` view: liveness, activity, and page url/title."""
        session = self._get(session_id)
        url, title = await self._focused_page_meta(session)
        return {
            "session_id": session.session_id,
            "live": not session.dead and self.chromium_up,
            "last_activity_at": session.last_activity_at,
            "url": url,
            "title": title,
            "metrics": session.metrics.snapshot(),
        }

    async def healthz(self) -> dict[str, Any]:
        """Readiness for ``/healthz``: a bounded CDP round-trip, not just liveness.

        A wedged-but-alive Chromium reports ``returncode is None`` forever, so
        answering on process state alone keeps the healthcheck green through
        exactly the outage it exists to catch. Probing the pipe is what lets the
        orchestrator restart the host.
        """
        responsive = False
        if self.chromium_up:
            try:
                await self._cdp_call("Target.getTargets", {}, timeout=_CDP_HEALTH_TIMEOUT_SECONDS)
                responsive = True
            except Exception as exc:
                log.error(
                    f"{LogTag.BROWSER} browser host CDP is unresponsive",
                    error_type=type(exc).__name__,
                )
        return {
            "ok": responsive,
            "sessions": len(self._sessions),
            "chromium_up": self.chromium_up,
            "cdp_responsive": responsive,
        }

    async def focused_target_id(self, session_id: str) -> str:
        """The target id of the context's focused page (for the screencast attach)."""
        session = self._get(session_id)
        targets = await self._cdp_call("Target.getTargets", {})
        pages = [
            ti
            for ti in targets["targetInfos"]
            if ti["type"] == "page" and ti.get("browserContextId") == session.context_id
        ]
        if not pages:
            return session.target_id
        # Prefer the primary page when still open, else the most recent one.
        for ti in pages:
            if ti["targetId"] == session.target_id:
                return session.target_id
        return str(pages[-1]["targetId"])

    # --- internals ---

    def _require_cdp(self) -> CDPClient:
        if self._cdp is None:
            raise RuntimeError("browser host CDP client is not connected")
        return self._cdp

    def _get(self, session_id: str) -> HostSession:
        session = self._sessions.get(session_id)
        if session is None:
            raise SessionNotFoundError(session_id)
        return session

    async def _cdp_call(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        session_id: str | None = None,
        timeout: float = _CDP_CALL_TIMEOUT_SECONDS,
    ) -> dict[str, Any]:
        """A bounded round-trip on the root CDP connection."""
        return await cdp_call(
            self._require_cdp(), method, params, session_id=session_id, timeout=timeout
        )

    async def _reserve_slot(self) -> None:
        """Claim one of ``BROWSER_HOST_MAX_SESSIONS`` slots before any CDP work.

        The lock guards the registry only — never the CDP round-trips — so one
        slow or wedged create cannot block every other user's.
        """
        async with self._lock:
            if len(self._sessions) + self._pending_slots >= settings.BROWSER_HOST_MAX_SESSIONS:
                raise AtCapacityError
            self._pending_slots += 1

    async def _dispose_context_id(self, context_id: str) -> None:
        """Best-effort Chromium-side teardown; never raises into a caller's ``finally``."""
        if not self.chromium_up:
            return
        try:
            await self._cdp_call("Target.disposeBrowserContext", {"browserContextId": context_id})
        except Exception as exc:  # teardown must not mask the caller's own failure
            log.warning(
                f"{LogTag.BROWSER} browser host context dispose failed",
                error_type=type(exc).__name__,
            )

    async def _seed_cookies(self, context_id: str, storage_state: StorageState) -> None:
        cookies: list[StorageStateCookie] = storage_state.get("cookies") or []
        if not cookies:
            return
        await self._cdp_call(
            "Storage.setCookies",
            {
                "browserContextId": context_id,
                "cookies": [_storage_state_cookie_to_cdp(c) for c in cookies],
            },
        )

    async def _seed_local_storage(self, target_id: str, storage_state: StorageState) -> None:
        """Restore saved per-origin localStorage — the symmetric partner of ``_dump_origins``.

        The dump saves each origin's localStorage into ``storage_state``; without this,
        that data was stored and never re-injected, so session reuse was cookie-only.
        For every origin that carried localStorage, this registers an
        ``addScriptToEvaluateOnNewDocument`` restore script (via a flat page session)
        so it runs before page scripts on every navigation of the target. Each script
        is guarded to its own origin and seeds a key only when the page has not already
        set it, so it never clobbers a value the live page updated and is safe to re-run.

        Coverage boundary: this registers on the context's INITIAL page target only —
        the single page browser-use drives for the overwhelming majority of tasks. A
        tab opened LATER in the same context (``window.open`` / ``target=_blank``) is
        not covered, exactly as the stealth init script documents: full new-target
        coverage needs a root-client ``Target.setAutoAttach`` hook, which would collide
        with browser-use's own auto-attach over the CDP proxy. Cookies (seeded per
        context) already reach new tabs; this localStorage restore does not.
        """
        origins = [o for o in (storage_state.get("origins") or []) if o.get("localStorage")]
        if not origins:
            return
        attached = await self._cdp_call(
            "Target.attachToTarget", {"targetId": target_id, "flatten": True}
        )
        page_session = attached["sessionId"]
        try:
            for origin in origins:
                await self._cdp_call(
                    "Page.addScriptToEvaluateOnNewDocument",
                    {
                        "source": _build_local_storage_restore_js(
                            origin["origin"], origin["localStorage"]
                        )
                    },
                    session_id=page_session,
                )
        finally:
            await self._cdp_call("Target.detachFromTarget", {"sessionId": page_session})

    async def _dump_storage_state(self, session: HostSession) -> StorageState:
        """Cookies (whole context) + localStorage (per open page) as storage_state."""
        if not self.chromium_up:
            return {"cookies": [], "origins": []}
        raw = await self._cdp_call("Storage.getCookies", {"browserContextId": session.context_id})
        cookies = [_cdp_cookie_to_storage_state(c) for c in raw["cookies"]]
        origins = await self._dump_origins(session)
        return {"cookies": cookies, "origins": origins}

    async def _dump_origins(self, session: HostSession) -> list[OriginState]:
        targets = await self._cdp_call("Target.getTargets", {})
        page_ids = [
            ti["targetId"]
            for ti in targets["targetInfos"]
            if ti["type"] == "page" and ti.get("browserContextId") == session.context_id
        ]
        origins: list[OriginState] = []
        for target_id in page_ids:
            attached = await self._cdp_call(
                "Target.attachToTarget", {"targetId": target_id, "flatten": True}
            )
            page_session = attached["sessionId"]
            try:
                result = await self._cdp_call(
                    "Runtime.evaluate",
                    {
                        "expression": _LOCAL_STORAGE_DUMP_JS,
                        "returnByValue": True,
                    },
                    session_id=page_session,
                )
            finally:
                await self._cdp_call("Target.detachFromTarget", {"sessionId": page_session})
            value = result.get("result", {}).get("value")
            if value and value.get("origin") and value.get("localStorage"):
                origins.append({"origin": value["origin"], "localStorage": value["localStorage"]})
        return origins

    async def _focused_page_meta(self, session: HostSession) -> tuple[str | None, str | None]:
        if not self.chromium_up:
            return None, None
        targets = await self._cdp_call("Target.getTargets", {})
        for ti in targets["targetInfos"]:
            if ti["type"] == "page" and ti.get("browserContextId") == session.context_id:
                return ti.get("url"), ti.get("title")
        return None, None

    async def _launch(self) -> None:
        if settings.BROWSER_ENGINE is BrowserEngine.OBSCURA:
            args = self._obscura_command()
        else:
            args = self._chromium_command()
        self._proc = await asyncio.create_subprocess_exec(
            *args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        self._sampler = ProcessSampler.for_pid(self._proc.pid)
        self._root_ws_url = await self._await_cdp_ready()
        cdp = CDPClient(self._root_ws_url)
        await cdp.start()
        self._cdp = cdp

    def _chromium_command(self) -> list[str]:
        """The full headless-shell argv, incl. the fresh user-data-dir it needs."""
        assert self._chromium_path is not None
        self._user_data_dir = tempfile.mkdtemp(prefix="gaia-browser-host-")
        args = [
            self._chromium_path,
            "--remote-debugging-port=0",
            f"--user-data-dir={self._user_data_dir}",
        ]
        args.extend(CHROME_DEFAULT_ARGS)
        args.extend(_HOST_EXTRA_ARGS)
        # Cap V8 per renderer so one heavy page cannot exhaust a shared host.
        # This bounds the JS heap only — DOM, images and raster buffers live
        # outside V8 — so it is a ceiling on the worst case, not a saving.
        args.append(f"--js-flags=--max-old-space-size={settings.BROWSER_HOST_JS_HEAP_MB}")
        # Size the window to the viewport so pages paint edge-to-edge instead of into
        # an 800x600 default (which leaves whitespace around the content in the view).
        args.append(f"--window-size={BROWSER_VIEWPORT_WIDTH},{BROWSER_VIEWPORT_HEIGHT}")
        if not settings.BROWSER_HOST_HEADED:
            # The shell build is headless by construction and only understands the
            # bare flag; `--headless=new` selects a mode that binary does not have.
            is_shell = Path(self._chromium_path).name in _HEADLESS_SHELL_BINARIES
            args.append("--headless" if is_shell else "--headless=new")
        return args

    def _obscura_command(self) -> list[str]:
        """Obscura's argv. It is a CDP *server* — ``serve``, not a chrome debug flag.

        It publishes its DevTools endpoint at ``/json/version`` on the port we
        name (never ephemeral, so we can poll for it), stealthed, and permitted
        to reach the private network the host allowlist otherwise fronts.
        """
        obscura_bin = settings.OBSCURA_BIN
        if not obscura_bin:
            raise RuntimeError("BROWSER_ENGINE=obscura requires OBSCURA_BIN to be set")
        return [
            obscura_bin,
            "serve",
            "--port",
            str(settings.OBSCURA_PORT),
            "--stealth",
            "--allow-private-network",
        ]

    async def _await_cdp_ready(self) -> str:
        if settings.BROWSER_ENGINE is BrowserEngine.OBSCURA:
            return await self._poll_devtools_endpoint(settings.OBSCURA_PORT, "Obscura")
        port = await self._read_devtools_port()
        return await self._poll_devtools_endpoint(port, "Chromium")

    async def _poll_devtools_endpoint(self, port: int, engine: str) -> str:
        """Poll ``/json/version`` until it yields the root ``webSocketDebuggerUrl``.

        Shared by both engines: Chromium and Obscura alike publish their DevTools
        websocket here, so once the port is known the discovery is identical.
        """
        deadline = time.monotonic() + _CDP_READY_TIMEOUT_SECONDS
        async with httpx.AsyncClient() as client:
            while time.monotonic() < deadline:
                try:
                    resp = await client.get(f"http://127.0.0.1:{port}/json/version", timeout=2.0)
                    resp.raise_for_status()
                    return str(resp.json()["webSocketDebuggerUrl"])
                except (httpx.HTTPError, KeyError):
                    await asyncio.sleep(_CDP_READY_POLL_SECONDS)
        raise RuntimeError(f"{engine} did not expose its CDP endpoint in time")

    async def _read_devtools_port(self) -> int:
        assert self._user_data_dir is not None

        port_file = Path(self._user_data_dir) / "DevToolsActivePort"
        deadline = time.monotonic() + _CDP_READY_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            if self._proc is not None and self._proc.returncode is not None:
                raise RuntimeError("Chromium exited before publishing its DevTools port")
            if port_file.exists():
                # Chromium creates the file, then writes the port asynchronously:
                # between the exists() check and the flush the file can be empty,
                # so read defensively and keep polling instead of crashing the
                # whole launch with an IndexError/ValueError on a partial write.
                port_lines = port_file.read_text().splitlines()
                if port_lines and (first_line := port_lines[0].strip()).isdigit():
                    return int(first_line)
            await asyncio.sleep(_CDP_READY_POLL_SECONDS)
        raise RuntimeError("Chromium did not write DevToolsActivePort in time")

    async def _shutdown_chromium(self) -> None:
        if self._cdp is not None:
            try:
                await self._cdp.stop()
            except Exception as exc:  # a dead socket on shutdown is not actionable
                log.warning(
                    f"{LogTag.BROWSER} browser host CDP stop failed",
                    error_type=type(exc).__name__,
                )
            self._cdp = None
        if self._proc is not None and self._proc.returncode is None:
            self._proc.terminate()
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=5)
            except TimeoutError:
                self._proc.kill()
        self._proc = None
        self._root_ws_url = None
        self._sampler = None

    async def _reaper_loop(self) -> None:
        while True:
            await asyncio.sleep(_REAPER_INTERVAL_SECONDS)
            try:
                if not self.chromium_up:
                    await self._recover_crash()
                    continue
                await self._reap_idle()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # a bad sweep must not kill the reaper
                log.error(
                    f"{LogTag.BROWSER} browser host reaper sweep failed",
                    error_type=type(exc).__name__,
                )

    async def _reap_idle(self) -> None:
        ttl = settings.BROWSER_HOST_IDLE_TTL_SECONDS
        now = time.monotonic()
        stale = [
            s.session_id
            for s in list(self._sessions.values())
            if s.viewer_count == 0 and (now - s.last_activity_at) > ttl
        ]
        for session_id in stale:
            session = self._sessions.get(session_id)
            if session is None:
                continue
            async with self._lock:
                self._sessions.pop(session_id, None)
            await self._dispose_context_id(session.context_id)
            log.set(browser={"session_id": session_id, "operation": "idle_reap"})
            log.info(f"{LogTag.BROWSER} browser context reaped (idle)")

    async def _recover_crash(self) -> None:
        dead_count = len(self._sessions)
        for session in self._sessions.values():
            session.dead = True
        self._sessions.clear()
        log.error(
            f"{LogTag.BROWSER} Chromium crashed; relaunching",
            browser={"operation": "crash_recover", "dead_sessions": dead_count},
        )
        await self._shutdown_chromium()
        await self._launch()


_LOCAL_STORAGE_DUMP_JS = (
    "(() => ({ origin: location.origin, localStorage: Object.keys(localStorage)"
    ".map(k => ({ name: k, value: localStorage.getItem(k) })) }))()"
)


def _build_local_storage_restore_js(origin: str, entries: list[LocalStorageEntry]) -> str:
    """The restore counterpart of ``_LOCAL_STORAGE_DUMP_JS`` for one origin.

    Guards on ``location.origin`` so it only writes on the matching origin, and sets
    each key IF-ABSENT so a value the page updated during the session is never
    clobbered and the script is safe to re-run on every navigation. Origin and
    entries go through ``json.dumps`` so they become well-formed JS literals.
    """
    return (
        "(() => {"
        f" if (location.origin !== {json.dumps(origin)}) return;"
        f" const entries = {json.dumps(entries)};"
        " for (const e of entries) {"
        " if (localStorage.getItem(e.name) === null) localStorage.setItem(e.name, e.value); } })()"
    )
