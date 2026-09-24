"""One long-lived Chromium, one isolated browser context per session.

The host launches a single Chromium and multiplexes every session onto its own
Target.createBrowserContext: cookies and storage never cross contexts, and a
second context costs a fraction of a second Chromium. Each session's context
lifecycle (create / seed / dump / dispose) rides that session's own connection.

ChromiumHost owns the Chromium subprocess and its root CDP connection, the live
session registry (context id, primary page, activity, viewers), an idle reaper
that disposes untouched, unwatched contexts, and a process-exit watcher that
relaunches a dead engine the instant it dies and marks its sessions dead.
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass, field
import json
from pathlib import Path

# spawns the Obscura/Chromium CDP server via create_subprocess_exec with a fixed
# argv from settings, never a shell; import is an intended, confirmed use.
import subprocess  # nosec B404
import tempfile
import time
from typing import Any
import uuid

from browser_use.browser.profile import CHROME_DEFAULT_ARGS
import httpx
from playwright.sync_api import StorageState, StorageStateCookie, sync_playwright
import psutil

from app.browser_host.cdp_mux import CdpMux, CdpTransport
from app.browser_host.memory import memory_usage_mb
from app.browser_host.metrics import ProcessSampler, SessionMetrics
from app.browser_host.obscura_launch import obscura_serve_argv, obscura_serve_env
from app.config.browser_host_settings import browser_host_settings
from app.constants.browser import (
    BROWSER_HOST_LIVENESS_TIMEOUT_SECONDS,
    BROWSER_VIEWPORT_HEIGHT,
    BROWSER_VIEWPORT_WIDTH,
    BrowserEngine,
    HostAdmissionRefusal,
)
from app.constants.log_tags import LogTag
from app.services.browser.storage_state_types import LocalStorageEntry, OriginState
from shared.py.wide_events import log

# Extra flags over browser-use's CHROME_DEFAULT_ARGS. --no-sandbox is a deliberate
# gap: the renderer sandbox needs unprivileged user namespaces the container lacks.
# Compensating controls: browser-only network island, per-context download deny, http(s)-only proxy.
_HOST_EXTRA_ARGS: tuple[str, ...] = (
    "--disable-component-update",
    "--no-sandbox",
    "--disable-dev-shm-usage",
)
# Playwright names the shell binary per platform: `headless_shell` on Linux (what
# production runs), `chrome-headless-shell` on macOS, `.exe` on Windows.
_HEADLESS_SHELL_BINARIES = ("headless_shell", "chrome-headless-shell", "headless_shell.exe")
# How a headless build names itself in its User-Agent ("HeadlessChrome/153.0.0.0").
_HEADLESS_MARKER = "HeadlessChrome/"
# Poll budget for Chromium to publish its DevTools endpoint after launch.
_CDP_READY_TIMEOUT_SECONDS = 30.0
_CDP_READY_POLL_SECONDS = 0.2
# Every CDP round-trip is bounded: CdpMux puts no timeout on the response future,
# so a wedged renderer would otherwise freeze the session lock and the reaper
# while the process stays alive and looks healthy.
_CDP_CALL_TIMEOUT_SECONDS = 20.0
# The health probe backs a container healthcheck, so it must give up well inside
# the orchestrator's own timeout rather than share the generous call budget.
_CDP_HEALTH_TIMEOUT_SECONDS = 5.0
# How often the idle reaper wakes to sweep for dead/idle contexts.
_REAPER_INTERVAL_SECONDS = 15.0
_BYTES_PER_MB = 1024 * 1024
# How often a create rechecks memory while backing off under pressure.
_ADMISSION_POLL_SECONDS = 0.25
# Above the soft watermark the reaper shortens the idle TTL by this factor (down to
# the floor) so idle sessions are reclaimed faster to make room for new ones.
_PRESSURE_IDLE_TTL_DIVISOR = 4
_MIN_PRESSURE_IDLE_TTL_SECONDS = 30.0
# Conservative floor reserved for each in-flight/next session so a burst of
# concurrent creates cannot collectively overshoot the watermark before their
# memory materializes; the live estimate rises above this as real cost shows.
_SESSION_COST_FLOOR_MB = 50
# Under pressure a create waits up to this long for memory to free (idle reap,
# other disposals) before returning 429 — graceful slowdown, not instant refusal.
_ADMISSION_WAIT_SECONDS = 5.0
# CDP's own default, spelled out: a context is disposed explicitly on dispose/reap,
# never because the connection that made it detached.
_NEW_CONTEXT_PARAMS: dict[str, Any] = {"disposeOnDetach": False}
# Per-renderer V8 heap ceiling. One runaway page must not be able to eat the
# whole host's budget and OOM every other user's session with it.
_JS_HEAP_MB = 512


@dataclass(slots=True)
class HostSession:
    """A single browser session: one isolated context with its primary page."""

    session_id: str
    context_id: str
    target_id: str
    # Obscura isolates every CDP connection, so the session's context, its pages
    # and everything driving them must ride this one socket.
    mux: CdpMux
    created_at: float
    last_activity_at: float
    viewer_count: int = 0
    dead: bool = False
    metrics: SessionMetrics = field(default_factory=SessionMetrics)


class AtCapacityError(RuntimeError):
    """Raised when admission turns a session away: the session ceiling or the memory watermark."""

    def __init__(
        self,
        gate: HostAdmissionRefusal,
        *,
        used_mb: float,
        limit_mb: float,
        projected_mb: float,
        sessions: int,
        pending: int,
    ) -> None:
        super().__init__(f"at capacity ({gate})")
        self.gate = gate
        self.used_mb = used_mb
        self.limit_mb = limit_mb
        self.projected_mb = projected_mb
        self.sessions = sessions
        self.pending = pending


class SessionNotFoundError(KeyError):
    """Raised when a session id is not (or no longer) live on the host."""


class CDPTimeoutError(RuntimeError):
    """Raised when a CDP call outruns its budget — Chromium is wedged, not busy."""


class EngineUnresponsiveError(RuntimeError):
    """Raised when the engine does not answer a CDP call on its root connection within the liveness budget."""


async def cdp_call(
    cdp: CdpTransport,
    method: str,
    params: dict[str, Any] | None = None,
    *,
    session_id: str | None = None,
    timeout: float = _CDP_CALL_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """One CDP round-trip, bounded by timeout.

    The single place the host talks to Chromium, so a wedged browser always
    raises :class:CDPTimeoutError instead of suspending its caller forever.
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
        # The prefix occurs once in the name, so the replace count is never reached.
        shell_root = parent.parent / parent.name.replace(
            "chromium-",
            "chromium_headless_shell-",
            1,  # pragma: no mutate
        )
        if not shell_root.is_dir():
            return None
        for name in _HEADLESS_SHELL_BINARIES:
            found = next((p for p in shell_root.rglob(name) if p.is_file()), None)
            if found is not None:
                return found
        return None
    return None


def _resolve_chromium_path() -> str:
    """Resolve the browser binary: CHROMIUM_BIN when set, else Playwright's headless shell.

    The shell build drops the browser-UI layer: at the same Chrome revision with
    three contexts open, 702 MB versus 1419 MB. Falls back to the full browser
    when the shell is absent. Playwright's resolver uses its sync API, which
    refuses to run inside a running event loop, so call this in a worker thread.
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


def _cdp_cookie_to_storage_state(cookie: dict[str, Any]) -> StorageStateCookie:
    """CDP Network.Cookie -> Playwright storage_state cookie shape."""
    out: StorageStateCookie = {
        "name": cookie["name"],
        "value": cookie["value"],
        "domain": cookie["domain"],
        "path": cookie["path"],
        # Required fields of CDP's Network.Cookie: the engine always sends them.
        "expires": cookie["expires"],
        "httpOnly": cookie["httpOnly"],
        "secure": cookie["secure"],
    }
    same_site = cookie.get("sameSite")
    if same_site:
        out["sameSite"] = same_site
    return out


def _storage_state_cookie_to_cdp(cookie: StorageStateCookie) -> dict[str, Any]:
    """Playwright storage_state cookie -> CDP Storage.setCookies param."""
    out: dict[str, Any] = {
        "name": cookie["name"],
        "value": cookie["value"],
        "domain": cookie["domain"],
        "path": cookie.get("path", "/"),
        "secure": cookie.get("secure", False),
        "httpOnly": cookie.get("httpOnly", False),
    }
    expires = cookie.get("expires")
    # -1 marks a session cookie; a real expiry is an epoch far above 1.
    if expires is not None and expires > 0:  # pragma: no mutate
        out["expires"] = expires
    same_site = cookie.get("sameSite")
    if same_site:
        out["sameSite"] = same_site
    return out


class ChromiumHost:
    """Owns the single browser process and every live context on it.

    Named for its default engine, but fronts either Chromium (headless-shell) or
    the Obscura CDP server, selected by browser_host_settings.BROWSER_ENGINE. Everything
    past launch — contexts, the CDP connection, proxy, screencast — speaks plain
    CDP and is identical for both."""

    def __init__(self) -> None:
        self._proc: asyncio.subprocess.Process | None = None
        self._root_mux: CdpMux | None = None
        self._root_ws_url: str | None = None
        self._chromium_path: str | None = None
        self._user_data_dir: str | None = None
        # The browser's own User-Agent without the headless marker, learned on the
        # first launch and passed to every launch after it.
        self._user_agent: str | None = None
        self._sessions: dict[str, HostSession] = {}
        # Slots claimed by a create that has not finished its CDP work yet, so the
        # capacity check stays correct while that work happens outside the lock.
        self._pending_slots = 0
        self._sampler: ProcessSampler | None = None
        self._lock = asyncio.Lock()
        self._reaper_task: asyncio.Task[None] | None = None
        # Watches the engine subprocess and relaunches it the moment it exits.
        self._watcher_task: asyncio.Task[None] | None = None
        # Serializes recovery so the watcher and the reaper can never relaunch at
        # once; recovery re-checks liveness under it, so the second caller no-ops.
        self._recover_lock = asyncio.Lock()
        # Memory used at startup (0 sessions): the baseline the per-session cost
        # estimate subtracts so it measures session-attributable growth, not the
        # engine+host floor. Captured in start() once the engine is up.
        self._base_memory_mb = 0.0
        # Set on stop() so the watcher treats the deliberate terminate as a shutdown.
        # An Event, not a bool: the watcher reads it after await proc.wait(), and the
        # type checker narrows a plain-bool read there to a constant.
        self._stopping = asyncio.Event()

    # --- lifecycle ---

    async def start(self) -> None:
        """Resolve the binary, launch the engine, connect CDP, start the watcher + reaper."""
        if browser_host_settings.BROWSER_ENGINE is not BrowserEngine.OBSCURA:
            self._chromium_path = await asyncio.to_thread(_resolve_chromium_path)
        await self._launch()
        if browser_host_settings.BROWSER_ENGINE is not BrowserEngine.OBSCURA:
            await self._relaunch_without_headless_marker()
        self._base_memory_mb = self._engine_rss_mb() or 0.0
        self._watcher_task = asyncio.create_task(self._watch_loop())
        self._reaper_task = asyncio.create_task(self._reaper_loop())
        log.info(f"{LogTag.BROWSER} browser host started")

    async def _relaunch_without_headless_marker(self) -> None:
        """Relaunch once announcing the same browser, when it calls itself HeadlessChrome.

        Headless Chromium sends "HeadlessChrome/<v>" in every User-Agent, which any
        site can read as a bot (DuckDuckGo answered with a CAPTCHA). The launch
        flag keeps the client-hint brands a CDP override would blank.
        """
        root_mux = self._root_mux
        if root_mux is None:
            raise RuntimeError("the engine has no root connection")  # pragma: no mutate
        user_agent = str((await cdp_call(root_mux, "Browser.getVersion"))["userAgent"])
        if _HEADLESS_MARKER not in user_agent:
            return
        self._user_agent = user_agent.replace(_HEADLESS_MARKER, "Chrome/")
        await self._shutdown_chromium()
        await self._launch()

    async def stop(self) -> None:
        """Tear everything down: reaper, process watcher, root CDP connection, engine process."""
        self._stopping.set()
        if self._reaper_task is not None:
            self._reaper_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reaper_task
            self._reaper_task = None
        # Hold the recovery lock so an in-flight crash recovery finishes before
        # teardown; once held, _stopping blocks any new recovery, so cancelling
        # the watcher next cannot interrupt a relaunch mid-flight.
        async with self._recover_lock:
            await self._shutdown_chromium()
        if self._watcher_task is not None:
            self._watcher_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._watcher_task
            self._watcher_task = None
        log.info(f"{LogTag.BROWSER} browser host stopped")

    @property
    def root_ws_url(self) -> str:
        """The engine's root CDP websocket URL, which every session dials once for its own mux."""
        if self._root_ws_url is None:
            raise RuntimeError("browser host is not started")
        return self._root_ws_url

    @property
    def chromium_up(self) -> bool:
        """Whether the Chromium subprocess is currently alive."""
        return self._proc is not None and self._proc.returncode is None

    # --- session registry ---

    async def create_context(self, storage_state: StorageState | None) -> HostSession:
        """Create an isolated context, plus one blank page, optionally seeding cookies.

        Fails fast with :class:AtCapacityError once BROWSER_HOST_MAX_SESSIONS
        contexts are live, so a caller gets a clean 429 instead of a Chromium that
        slowly runs out of memory.
        """
        await self._reserve_slot()
        mux: CdpMux | None = None
        try:
            mux = CdpMux(self.root_ws_url)
            await mux.start()
            ctx = await cdp_call(mux, "Target.createBrowserContext", _NEW_CONTEXT_PARAMS)
            context_id = str(ctx["browserContextId"])
            # Refuse downloads before the context can navigate: a drive-by download
            # is the cheapest way to get a file onto the host's disk. Scoped to this
            # context so it can never race another session's setting.
            await cdp_call(
                mux,
                "Browser.setDownloadBehavior",
                {"behavior": "deny", "browserContextId": context_id},
            )
            target = await cdp_call(
                mux,
                "Target.createTarget",
                {"url": "about:blank", "browserContextId": context_id},
            )
            target_id: str = target["targetId"]

            if storage_state:
                await self._seed_cookies(mux, context_id, storage_state)
                await self._seed_local_storage(mux, target_id, storage_state)

            now = time.monotonic()
            session_id = uuid.uuid4().hex
            session = HostSession(
                session_id=session_id,
                context_id=context_id,
                target_id=target_id,
                mux=mux,
                created_at=now,
                last_activity_at=now,
                metrics=SessionMetrics(context_count=1, page_count=1),
            )
            async with self._lock:
                # Hand the reservation to the session in ONE critical section:
                # releasing it separately leaves a window where the create is
                # counted twice and a concurrent caller gets a spurious 429.
                self._sessions[session_id] = session
                self._pending_slots -= 1
            self.sample_resources(session_id)
        except BaseException:
            async with self._lock:
                self._pending_slots -= 1
            # A connection opened before the failure has no session to carry it,
            # so the idle reaper would never find it — drop it here.
            if mux is not None:
                await mux.close()
            raise

        log.set(browser={"session_id": session_id, "operation": "create"})
        log.info(f"{LogTag.BROWSER} browser context created")
        return session

    async def dispose_context(self, session_id: str) -> StorageState:
        """Dump the context's storage_state, then dispose it. Returns the dump."""
        session = self._get(session_id)
        self.sample_resources(session_id)
        state: StorageState | None = None
        try:
            state = await self._dump_storage_state(session)
            return state
        finally:
            # Release the slot and the Chromium context even when the dump fails or
            # times out: a hung dump used to leave the session in the registry
            # forever, burning a slot after the caller had already moved on.
            async with self._lock:
                self._sessions.pop(session_id, None)
            await self._close_session_connection(session)
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

    async def storage_state(self, session_id: str) -> StorageState:
        """Dump the live context's storage_state and leave it running.

        A run moving to another engine reads it to open there as the same
        signed-in browser; dispose_context is the read that ends the session.
        """
        return await self._dump_storage_state(self._get(session_id))

    def get(self, session_id: str) -> HostSession | None:
        """Return the live session, or None if unknown/disposed."""
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
        """Record that a Page.navigate command left the client (called by the CDP proxy)."""
        session = self._sessions.get(session_id)
        if session is not None:
            session.metrics.start_navigation()

    def note_navigation_finished(self, session_id: str) -> None:
        """Record a load event coming back; closes the timing and samples resources."""
        session = self._sessions.get(session_id)
        if session is None or session.metrics.finish_navigation() is None:
            return
        self.sample_resources(session_id)

    def note_page_created(self, session_id: str) -> None:
        """Record that a Target.createTarget opened another page inside this session."""
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
        """Build the GET /sessions/{id} view: liveness, activity, and page url/title.

        Answers within the liveness budget whatever the page is doing. Liveness is
        read on the root connection, which no page's work can hold up; the page is
        read on the session's own, which a heavy page holds for seconds at a time.
        Raise EngineUnresponsiveError when the engine itself does not answer.
        """
        session = self._get(session_id)
        live = not session.dead and self.chromium_up
        url: str | None = None
        title: str | None = None
        if live:
            responsive, (url, title) = await asyncio.gather(
                self._engine_responsive(BROWSER_HOST_LIVENESS_TIMEOUT_SECONDS),
                self._focused_page_meta(session),
            )
            if not responsive:
                raise EngineUnresponsiveError(session_id)
        return {
            "session_id": session.session_id,
            "live": live,
            "last_activity_at": session.last_activity_at,
            "url": url,
            "title": title,
            "metrics": session.metrics.snapshot(),
        }

    async def healthz(self) -> dict[str, Any]:
        """Readiness for /healthz: a bounded CDP round-trip, not just liveness.

        A wedged-but-alive Chromium reports returncode is None forever, so
        answering on process state alone keeps the healthcheck green through
        exactly the outage it exists to catch. Probing the pipe is what lets the
        orchestrator restart the host.
        """
        responsive = await self._engine_responsive(_CDP_HEALTH_TIMEOUT_SECONDS)
        return {
            "ok": responsive,
            "sessions": len(self._sessions),
            "chromium_up": self.chromium_up,
            "cdp_responsive": responsive,
        }

    async def focused_target_id(self, session_id: str) -> str:
        """Return the target id of the context's focused page (for the screencast attach)."""
        session = self._get(session_id)
        targets = await cdp_call(session.mux, "Target.getTargets")
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

    def _get(self, session_id: str) -> HostSession:
        session = self._sessions.get(session_id)
        if session is None:
            raise SessionNotFoundError(session_id)
        return session

    def _engine_rss_mb(self) -> float | None:
        """RSS of the engine's own process tree, or None when it cannot be sampled."""
        if self._sampler is None:
            return None
        reading = self._sampler.sample()
        return None if reading is None else reading[0]

    def _estimate_session_cost_mb(self) -> float:
        """Adaptive MB to reserve for the next session: measured average, floored.

        (engine_rss - engine_rss_at_launch) / live_sessions learns the real
        per-session cost as sessions run; the floor keeps a burst of concurrent
        creates from collectively overshooting before their memory materializes.
        """
        floor = float(_SESSION_COST_FLOOR_MB)
        sessions = len(self._sessions)
        # Only the engine tree is what sessions cost: charging them for everything
        # else that grew since launch made a long-lived host 429 every create.
        engine_rss = self._engine_rss_mb()
        if sessions == 0 or engine_rss is None:
            return floor
        return max(floor, (engine_rss - self._base_memory_mb) / sessions)

    async def _reserve_slot(self) -> None:
        """Admit one session when memory allows, else back off then 429.

        The gate is memory, not a count: admit while projected usage (current plus
        a reservation per in-flight and the new create) stays under the high
        watermark; else wait for disposals and raise AtCapacityError only once the
        wait budget is spent. The lock guards the registry, never the CDP calls.
        """
        deadline = time.monotonic() + _ADMISSION_WAIT_SECONDS
        # Backstop on concurrent contexts, not the real gate (admission is memory
        # based); a fallback Chromium host sets it low. 0 disables it.
        ceiling = browser_host_settings.BROWSER_HOST_MAX_SESSIONS
        while True:
            used, limit = memory_usage_mb()
            estimate = self._estimate_session_cost_mb()
            hard_mb = limit * browser_host_settings.BROWSER_HOST_MEMORY_HIGH_WATERMARK
            async with self._lock:
                sessions, pending = len(self._sessions), self._pending_slots
                over_ceiling = ceiling > 0 and sessions + pending >= ceiling
                projected = used + (pending + 1) * estimate
                if not over_ceiling and projected <= hard_mb:
                    self._pending_slots += 1
                    return
            # A clock reading equal to the deadline is a nanosecond event; > and >= agree.
            if time.monotonic() >= deadline:  # pragma: no mutate
                raise AtCapacityError(
                    HostAdmissionRefusal.SESSION_CEILING
                    if over_ceiling
                    else HostAdmissionRefusal.MEMORY,
                    used_mb=used,
                    limit_mb=limit,
                    projected_mb=projected,
                    sessions=sessions,
                    pending=pending,
                )
            await asyncio.sleep(_ADMISSION_POLL_SECONDS)

    async def _close_session_connection(self, session: HostSession) -> None:
        """Best-effort teardown of a session's context and its connection; never raises.

        Closing the socket is what frees the session on a per-connection engine;
        disposing the context first keeps a shared-world engine tidy too.
        """
        if self.chromium_up and not session.mux.closed:
            try:
                await cdp_call(
                    session.mux,
                    "Target.disposeBrowserContext",
                    {"browserContextId": session.context_id},
                )
            except Exception as exc:  # teardown must not mask the caller's own failure
                log.warning(
                    f"{LogTag.BROWSER} browser host context dispose failed",
                    error_type=type(exc).__name__,
                )
        await session.mux.close()

    async def _seed_cookies(
        self, mux: CdpMux, context_id: str, storage_state: StorageState
    ) -> None:
        cookies: list[StorageStateCookie] = storage_state.get("cookies") or []
        if not cookies:
            return
        await cdp_call(
            mux,
            "Storage.setCookies",
            {
                "browserContextId": context_id,
                "cookies": [_storage_state_cookie_to_cdp(c) for c in cookies],
            },
        )

    async def _seed_local_storage(
        self, mux: CdpMux, target_id: str, storage_state: StorageState
    ) -> None:
        """Restore saved per-origin localStorage, the symmetric partner of _dump_origins.

        One addScriptToEvaluateOnNewDocument per origin, guarded to that origin and
        seeding a key only when the page has not set it, so re-runs are safe. Covers
        the context's INITIAL page target only: a tab opened later (window.open /
        target=_blank) is not seeded, unlike cookies, which are seeded per context.
        """
        origins = [o for o in (storage_state.get("origins") or []) if o.get("localStorage")]
        if not origins:
            return
        attached = await cdp_call(
            mux, "Target.attachToTarget", {"targetId": target_id, "flatten": True}
        )
        page_session = attached["sessionId"]
        try:
            for origin in origins:
                await cdp_call(
                    mux,
                    "Page.addScriptToEvaluateOnNewDocument",
                    {
                        "source": _build_local_storage_restore_js(
                            origin["origin"], origin["localStorage"]
                        )
                    },
                    session_id=page_session,
                )
        finally:
            await cdp_call(mux, "Target.detachFromTarget", {"sessionId": page_session})

    async def _dump_storage_state(self, session: HostSession) -> StorageState:
        """Cookies (whole context) + localStorage (per open page) as storage_state.

        Raises EngineUnresponsiveError on a down engine: an empty state there is
        not the context's, and would be saved over the user's login.
        """
        if not self.chromium_up:
            raise EngineUnresponsiveError(session.session_id)
        raw = await cdp_call(
            session.mux, "Storage.getCookies", {"browserContextId": session.context_id}
        )
        cookies = [_cdp_cookie_to_storage_state(c) for c in raw["cookies"]]
        origins = await self._dump_origins(session)
        return {"cookies": cookies, "origins": origins}

    async def _dump_origins(self, session: HostSession) -> list[OriginState]:
        targets = await cdp_call(session.mux, "Target.getTargets")
        page_ids = [
            ti["targetId"]
            for ti in targets["targetInfos"]
            if ti["type"] == "page" and ti.get("browserContextId") == session.context_id
        ]
        origins: list[OriginState] = []
        for target_id in page_ids:
            attached = await cdp_call(
                session.mux, "Target.attachToTarget", {"targetId": target_id, "flatten": True}
            )
            page_session = attached["sessionId"]
            try:
                result = await cdp_call(
                    session.mux,
                    "Runtime.evaluate",
                    {
                        "expression": _LOCAL_STORAGE_DUMP_JS,
                        "returnByValue": True,
                    },
                    session_id=page_session,
                )
            finally:
                await cdp_call(session.mux, "Target.detachFromTarget", {"sessionId": page_session})
            value = result["result"].get("value")
            if value and value.get("origin") and value.get("localStorage"):
                origins.append({"origin": value["origin"], "localStorage": value["localStorage"]})
        return origins

    async def _engine_responsive(self, timeout: float) -> bool:
        """Whether the engine answers a CDP round-trip on the root connection within timeout."""
        root_mux = self._root_mux
        if not self.chromium_up or root_mux is None:
            return False
        try:
            await cdp_call(root_mux, "Target.getTargets", timeout=timeout)
        except Exception as exc:
            log.error(
                f"{LogTag.BROWSER} browser host CDP is unresponsive",
                error_type=type(exc).__name__,
            )
            return False
        return True

    async def _focused_page_meta(self, session: HostSession) -> tuple[str | None, str | None]:
        """Read the session's page url and title; none while a heavy page holds its connection."""
        try:
            targets = await cdp_call(
                session.mux, "Target.getTargets", timeout=BROWSER_HOST_LIVENESS_TIMEOUT_SECONDS
            )
        except CDPTimeoutError:
            return None, None
        for ti in targets["targetInfos"]:
            if ti["type"] == "page" and ti.get("browserContextId") == session.context_id:
                return ti.get("url"), ti.get("title")
        return None, None

    async def _launch(self) -> None:
        if browser_host_settings.BROWSER_ENGINE is BrowserEngine.OBSCURA:
            args, env = self._obscura_command(), obscura_serve_env()
        else:
            args, env = self._chromium_command(), None
        self._proc = await asyncio.create_subprocess_exec(
            *args, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        self._sampler = ProcessSampler.for_pid(self._proc.pid)
        self._root_ws_url = await self._await_cdp_ready()
        root_mux = CdpMux(self._root_ws_url)
        await root_mux.start()
        self._root_mux = root_mux

    async def _watch_loop(self) -> None:
        """Relaunch the engine the moment its process exits, not on the reaper's sweep.

        One supervisor for the host's lifetime: it awaits the current process,
        and after a recovery relaunches a new one it loops round and watches that
        one too. Recovery is idempotent with the reaper's own backstop.
        """
        while True:
            if self._stopping.is_set():
                return
            proc = self._proc
            if proc is None:
                return
            await proc.wait()
            if self._stopping.is_set():
                return
            log.error(
                f"{LogTag.BROWSER} browser engine process exited",
                browser={"operation": "crash_detect", "returncode": proc.returncode},
            )
            await self._recover_crash()

    def _chromium_command(self) -> list[str]:
        """Build the full headless-shell argv, incl. the fresh user-data-dir it needs."""
        if self._chromium_path is None:
            raise RuntimeError("chromium_path not set")  # pragma: no mutate
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
        args.append(f"--js-flags=--max-old-space-size={_JS_HEAP_MB}")
        # Size the window to the viewport so pages paint edge-to-edge instead of into
        # an 800x600 default (which leaves whitespace around the content in the view).
        args.append(f"--window-size={BROWSER_VIEWPORT_WIDTH},{BROWSER_VIEWPORT_HEIGHT}")
        if self._user_agent is not None:
            args.append(f"--user-agent={self._user_agent}")
        if not browser_host_settings.BROWSER_HOST_HEADED:
            # The shell build is headless by construction and only understands the
            # bare flag; `--headless=new` selects a mode that binary does not have.
            is_shell = Path(self._chromium_path).name in _HEADLESS_SHELL_BINARIES
            args.append("--headless" if is_shell else "--headless=new")
        return args

    def _obscura_command(self) -> list[str]:
        """Obscura's argv. It is a CDP *server* — serve, not a chrome debug flag.

        It publishes its DevTools endpoint at /json/version on the port we
        name (never ephemeral, so we can poll for it), stealthed, and always kept
        off the private network.
        """
        return obscura_serve_argv(browser_host_settings.OBSCURA_PORT)

    async def _await_cdp_ready(self) -> str:
        if browser_host_settings.BROWSER_ENGINE is BrowserEngine.OBSCURA:
            return await self._poll_devtools_endpoint(browser_host_settings.OBSCURA_PORT, "Obscura")
        port = await self._read_devtools_port()
        return await self._poll_devtools_endpoint(port, "Chromium")

    async def _poll_devtools_endpoint(self, port: int, engine: str) -> str:
        """Poll /json/version until it yields the root webSocketDebuggerUrl.

        Shared by both engines: Chromium and Obscura alike publish their DevTools
        websocket here, so once the port is known the discovery is identical.
        """
        deadline = time.monotonic() + _CDP_READY_TIMEOUT_SECONDS
        async with httpx.AsyncClient() as client:
            while time.monotonic() < deadline:  # pragma: no mutate
                try:
                    resp = await client.get(f"http://127.0.0.1:{port}/json/version", timeout=2.0)
                    resp.raise_for_status()
                    return str(resp.json()["webSocketDebuggerUrl"])
                except (httpx.HTTPError, KeyError):
                    await asyncio.sleep(_CDP_READY_POLL_SECONDS)
        raise RuntimeError(f"{engine} did not expose its CDP endpoint in time")

    async def _read_devtools_port(self) -> int:
        if self._user_data_dir is None:
            raise RuntimeError("user_data_dir not set")  # pragma: no mutate

        port_file = Path(self._user_data_dir) / "DevToolsActivePort"
        deadline = time.monotonic() + _CDP_READY_TIMEOUT_SECONDS
        while time.monotonic() < deadline:  # pragma: no mutate
            if self._proc is not None and self._proc.returncode is not None:
                raise RuntimeError(
                    "Chromium exited before publishing its DevTools port"  # pragma: no mutate
                )
            if port_file.exists():
                # Chromium creates the file, then writes the port asynchronously, so
                # it can be empty between exists() and the flush: read defensively
                # and keep polling instead of crashing the launch on a partial write.
                port_lines = port_file.read_text().splitlines()
                if port_lines and (first_line := port_lines[0].strip()).isdigit():
                    return int(first_line)
            await asyncio.sleep(_CDP_READY_POLL_SECONDS)
        raise RuntimeError("Chromium did not write DevToolsActivePort in time")  # pragma: no mutate

    async def _shutdown_chromium(self) -> None:
        if self._root_mux is not None:
            try:
                await self._root_mux.close()
            except Exception as exc:  # a dead socket on shutdown is not actionable
                log.warning(
                    f"{LogTag.BROWSER} browser host CDP stop failed",
                    error_type=type(exc).__name__,
                )
            self._root_mux = None
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
                await self._recycle_if_bloated()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # a bad sweep must not kill the reaper
                log.error(
                    f"{LogTag.BROWSER} browser host reaper sweep failed",
                    error_type=type(exc).__name__,
                )

    def engine_rss_mb(self) -> float | None:
        """Resident memory of the engine process and its children, or None when it is not running."""
        if self._proc is None or self._proc.returncode is not None:
            return None
        try:
            root = psutil.Process(self._proc.pid)
            total = root.memory_info().rss
            for child in root.children(recursive=True):
                try:
                    total += child.memory_info().rss
                except psutil.Error:
                    continue
        except psutil.Error:
            return None
        return total / _BYTES_PER_MB

    async def _recycle_if_bloated(self) -> None:
        """Relaunch an idle engine whose memory has outgrown BROWSER_ENGINE_RECYCLE_MB.

        A long-lived engine keeps memory from every context it has disposed and
        slows with it; with no session open a relaunch costs nobody anything.
        """
        limit = browser_host_settings.BROWSER_ENGINE_RECYCLE_MB
        if limit is None or self._sessions:
            return
        rss = self.engine_rss_mb()
        if rss is None or rss <= limit:
            return
        async with self._recover_lock:
            if self._stopping.is_set() or self._sessions:
                return
            log.warning(
                f"{LogTag.BROWSER} browser engine recycled over its idle memory limit",
                browser={"operation": "recycle", "rss_mb": round(rss), "limit_mb": limit},
            )
            await self._shutdown_chromium()
            await self._launch()

    async def _reap_idle(self) -> None:
        ttl = float(browser_host_settings.BROWSER_HOST_IDLE_TTL_SECONDS)
        used, limit = memory_usage_mb()
        # Under memory pressure, reclaim idle sessions sooner to free room for new
        # ones instead of waiting out the full idle TTL.
        soft_mb = limit * browser_host_settings.BROWSER_HOST_MEMORY_SOFT_WATERMARK
        # A limit of 0 means none was detected; no real limit sits between 0 and 1 MB.
        if limit > 0 and used > soft_mb:  # pragma: no mutate
            ttl = max(_MIN_PRESSURE_IDLE_TTL_SECONDS, ttl / _PRESSURE_IDLE_TTL_DIVISOR)
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
            await self._close_session_connection(session)
            log.set(browser={"session_id": session_id, "operation": "idle_reap"})
            log.info(f"{LogTag.BROWSER} browser context reaped (idle)")

    async def _recover_crash(self) -> None:
        async with self._recover_lock:
            # The watcher and the reaper both route here; whichever loses the race
            # finds the engine already back up (or a stop in progress) and does nothing.
            if self._stopping.is_set() or self.chromium_up:
                return
            dead_count = len(self._sessions)
            for session in self._sessions.values():
                session.dead = True
                # The engine is gone, so these sockets are already broken; closing
                # them fails their waiters instead of leaving readers on a dead pipe.
                await session.mux.close()
            self._sessions.clear()
            log.error(
                f"{LogTag.BROWSER} browser engine crashed; relaunching",
                browser={"operation": "crash_recover", "dead_sessions": dead_count},
            )
            await self._shutdown_chromium()
            await self._launch()


_LOCAL_STORAGE_DUMP_JS = (
    "(() => ({ origin: location.origin, localStorage: Object.keys(localStorage)"
    ".map(k => ({ name: k, value: localStorage.getItem(k) })) }))()"
)


def _build_local_storage_restore_js(origin: str, entries: list[LocalStorageEntry]) -> str:
    """Build the restore counterpart of _LOCAL_STORAGE_DUMP_JS for one origin.

    Guards on location.origin so it only writes on the matching origin, and sets
    each key IF-ABSENT so a value the page updated during the session is never
    clobbered and the script is safe to re-run on every navigation. Origin and
    entries go through json.dumps so they become well-formed JS literals.
    """
    return (
        "(() => {"
        f" if (location.origin !== {json.dumps(origin)}) return;"
        f" const entries = {json.dumps(entries)};"
        " for (const e of entries) {"
        " if (localStorage.getItem(e.name) === null) localStorage.setItem(e.name, e.value); } })()"
    )
