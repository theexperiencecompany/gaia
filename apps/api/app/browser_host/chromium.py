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
from dataclasses import dataclass
from pathlib import Path
import subprocess
import tempfile
import time
from typing import Any
import uuid

from browser_use.browser.profile import CHROME_DEFAULT_ARGS
from cdp_use.client import CDPClient
import httpx
from playwright.sync_api import sync_playwright

from app.config.settings import settings
from app.constants.log_tags import LogTag
from shared.py.wide_events import log

# Extra flags on top of browser-use's CHROME_DEFAULT_ARGS: never phone home for
# component updates, and the two flags a containerized Chromium needs to run.
_HOST_EXTRA_ARGS: tuple[str, ...] = (
    "--disable-component-update",
    "--no-sandbox",
    "--disable-dev-shm-usage",
    # Render at a normal laptop resolution — the headless default (~800x600)
    # makes sites collapse to their mobile layout and screenshots look broken.
    "--window-size=1280,900",
    "--force-device-scale-factor=1",
)
# Poll budget for Chromium to publish its DevTools endpoint after launch.
_CDP_READY_TIMEOUT_SECONDS = 30.0
_CDP_READY_POLL_SECONDS = 0.2
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


class AtCapacityError(RuntimeError):
    """Raised when the host already holds ``BROWSER_HOST_MAX_SESSIONS`` contexts."""


class SessionNotFoundError(KeyError):
    """Raised when a session id is not (or no longer) live on the host."""


def _resolve_chromium_path() -> str:
    """The Chromium binary: the configured override, else Playwright's bundled one.

    Playwright's resolver uses its sync API, which refuses to run inside a
    running event loop — callers must invoke this in a worker thread.
    """
    override = settings.BROWSER_HOST_CHROMIUM_PATH
    if override:
        return str(override)

    with sync_playwright() as p:
        return p.chromium.executable_path


def _cdp_cookie_to_storage_state(cookie: dict[str, Any]) -> dict[str, Any]:
    """CDP ``Network.Cookie`` -> Playwright ``storage_state`` cookie shape."""
    out: dict[str, Any] = {
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


def _storage_state_cookie_to_cdp(cookie: dict[str, Any]) -> dict[str, Any]:
    """Playwright ``storage_state`` cookie -> CDP ``Storage.setCookies`` param."""
    out: dict[str, Any] = {
        "name": cookie["name"],
        "value": cookie["value"],
        "domain": cookie["domain"],
        "path": cookie.get("path", "/"),
        "secure": cookie.get("secure", False),
        "httpOnly": cookie.get("httpOnly", False),
    }
    expires = cookie.get("expires", -1)
    if expires and expires > 0:
        out["expires"] = expires
    same_site = cookie.get("sameSite")
    if same_site:
        out["sameSite"] = same_site
    return out


class ChromiumHost:
    """Owns the single Chromium process and every live browser context on it."""

    def __init__(self) -> None:
        self._proc: asyncio.subprocess.Process | None = None
        self._cdp: CDPClient | None = None
        self._root_ws_url: str | None = None
        self._chromium_path: str | None = None
        self._user_data_dir: str | None = None
        self._sessions: dict[str, HostSession] = {}
        self._lock = asyncio.Lock()
        self._reaper_task: asyncio.Task[None] | None = None

    # --- lifecycle ---

    async def start(self) -> None:
        """Resolve the binary, launch Chromium, connect CDP, start the reaper."""
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

    async def create_context(self, storage_state: dict[str, Any] | None) -> HostSession:
        """Create an isolated context (+ one blank page), optionally seeding cookies.

        Fails fast with :class:`AtCapacityError` once ``BROWSER_HOST_MAX_SESSIONS``
        contexts are live, so a caller gets a clean 429 instead of a Chromium that
        slowly runs out of memory.
        """
        async with self._lock:
            if len(self._sessions) >= settings.BROWSER_HOST_MAX_SESSIONS:
                raise AtCapacityError
            cdp = self._require_cdp()
            ctx = await cdp.send_raw("Target.createBrowserContext", {"disposeOnDetach": False})
            context_id: str = ctx["browserContextId"]
            target = await cdp.send_raw(
                "Target.createTarget",
                {"url": "about:blank", "browserContextId": context_id},
            )
            target_id: str = target["targetId"]

            if storage_state:
                await self._seed_cookies(context_id, storage_state)

            now = time.monotonic()
            session_id = uuid.uuid4().hex
            session = HostSession(
                session_id=session_id,
                context_id=context_id,
                target_id=target_id,
                created_at=now,
                last_activity_at=now,
            )
            self._sessions[session_id] = session

        log.set(browser={"session_id": session_id, "operation": "create"})
        log.info(f"{LogTag.BROWSER} browser context created")
        return session

    async def dispose_context(self, session_id: str) -> dict[str, Any]:
        """Dump the context's ``storage_state``, then dispose it. Returns the dump."""
        session = self._get(session_id)
        storage_state = await self._dump_storage_state(session)
        async with self._lock:
            self._sessions.pop(session_id, None)
        if self.chromium_up:
            cdp = self._require_cdp()
            await cdp.send_raw(
                "Target.disposeBrowserContext", {"browserContextId": session.context_id}
            )
        log.set(browser={"session_id": session_id, "operation": "dispose"})
        log.info(f"{LogTag.BROWSER} browser context disposed")
        return storage_state

    def get(self, session_id: str) -> HostSession | None:
        """The live session, or ``None`` if unknown/disposed."""
        return self._sessions.get(session_id)

    def touch(self, session_id: str) -> None:
        """Mark a session active now (called on any CDP/live-view traffic)."""
        session = self._sessions.get(session_id)
        if session is not None:
            session.last_activity_at = time.monotonic()

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
        }

    def healthz(self) -> dict[str, Any]:
        """Liveness snapshot for the ``/healthz`` endpoint."""
        return {
            "ok": self.chromium_up,
            "sessions": len(self._sessions),
            "chromium_up": self.chromium_up,
        }

    async def focused_target_id(self, session_id: str) -> str:
        """The target id of the context's focused page (for the screencast attach)."""
        session = self._get(session_id)
        cdp = self._require_cdp()
        targets = await cdp.send_raw("Target.getTargets", {})
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

    async def _seed_cookies(self, context_id: str, storage_state: dict[str, Any]) -> None:
        cookies = storage_state.get("cookies") or []
        if not cookies:
            return
        cdp = self._require_cdp()
        await cdp.send_raw(
            "Storage.setCookies",
            {
                "browserContextId": context_id,
                "cookies": [_storage_state_cookie_to_cdp(c) for c in cookies],
            },
        )

    async def _dump_storage_state(self, session: HostSession) -> dict[str, Any]:
        """Cookies (whole context) + localStorage (per open page) as storage_state."""
        if not self.chromium_up:
            return {"cookies": [], "origins": []}
        cdp = self._require_cdp()
        raw = await cdp.send_raw("Storage.getCookies", {"browserContextId": session.context_id})
        cookies = [_cdp_cookie_to_storage_state(c) for c in raw["cookies"]]
        origins = await self._dump_origins(session)
        return {"cookies": cookies, "origins": origins}

    async def _dump_origins(self, session: HostSession) -> list[dict[str, Any]]:
        cdp = self._require_cdp()
        targets = await cdp.send_raw("Target.getTargets", {})
        page_ids = [
            ti["targetId"]
            for ti in targets["targetInfos"]
            if ti["type"] == "page" and ti.get("browserContextId") == session.context_id
        ]
        origins: list[dict[str, Any]] = []
        for target_id in page_ids:
            attached = await cdp.send_raw(
                "Target.attachToTarget", {"targetId": target_id, "flatten": True}
            )
            page_session = attached["sessionId"]
            try:
                result = await cdp.send_raw(
                    "Runtime.evaluate",
                    {
                        "expression": _LOCAL_STORAGE_DUMP_JS,
                        "returnByValue": True,
                    },
                    session_id=page_session,
                )
            finally:
                await cdp.send_raw("Target.detachFromTarget", {"sessionId": page_session})
            value = result.get("result", {}).get("value")
            if value and value.get("origin") and value.get("localStorage"):
                origins.append({"origin": value["origin"], "localStorage": value["localStorage"]})
        return origins

    async def _focused_page_meta(self, session: HostSession) -> tuple[str | None, str | None]:
        if not self.chromium_up:
            return None, None
        cdp = self._require_cdp()
        targets = await cdp.send_raw("Target.getTargets", {})
        for ti in targets["targetInfos"]:
            if ti["type"] == "page" and ti.get("browserContextId") == session.context_id:
                return ti.get("url"), ti.get("title")
        return None, None

    async def _launch(self) -> None:
        assert self._chromium_path is not None
        self._user_data_dir = tempfile.mkdtemp(prefix="gaia-browser-host-")
        args = [
            self._chromium_path,
            "--remote-debugging-port=0",
            f"--user-data-dir={self._user_data_dir}",
        ]
        args.extend(CHROME_DEFAULT_ARGS)
        args.extend(_HOST_EXTRA_ARGS)
        if not settings.BROWSER_HOST_HEADED:
            args.append("--headless=new")
        self._proc = await asyncio.create_subprocess_exec(
            *args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        self._root_ws_url = await self._await_cdp_ready()
        cdp = CDPClient(self._root_ws_url)
        await cdp.start()
        self._cdp = cdp

    async def _await_cdp_ready(self) -> str:
        port = await self._read_devtools_port()
        deadline = time.monotonic() + _CDP_READY_TIMEOUT_SECONDS
        async with httpx.AsyncClient() as client:
            while time.monotonic() < deadline:
                try:
                    resp = await client.get(f"http://127.0.0.1:{port}/json/version", timeout=2.0)
                    resp.raise_for_status()
                    return str(resp.json()["webSocketDebuggerUrl"])
                except (httpx.HTTPError, KeyError):
                    await asyncio.sleep(_CDP_READY_POLL_SECONDS)
        raise RuntimeError("Chromium did not expose its CDP endpoint in time")

    async def _read_devtools_port(self) -> int:
        assert self._user_data_dir is not None

        port_file = Path(self._user_data_dir) / "DevToolsActivePort"
        deadline = time.monotonic() + _CDP_READY_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            if self._proc is not None and self._proc.returncode is not None:
                raise RuntimeError("Chromium exited before publishing its DevTools port")
            if port_file.exists():
                first_line = port_file.read_text().splitlines()[0].strip()
                if first_line:
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
            try:
                cdp = self._require_cdp()
                await cdp.send_raw(
                    "Target.disposeBrowserContext", {"browserContextId": session.context_id}
                )
            except Exception as exc:
                log.warning(
                    f"{LogTag.BROWSER} browser host idle dispose failed",
                    error_type=type(exc).__name__,
                    browser={"session_id": session_id, "operation": "idle_reap"},
                )
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
