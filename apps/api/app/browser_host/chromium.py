"""The browser host: its engines, the live session registry, admission and leases.

One engine (Obscura or Chromium) takes new sessions. Each session is an isolated
browser context on its own CDP connection, with a host-owned page session on its
page for control work. A session lives on a lease its run renews; one whose lease
runs out, whose connection drops or whose engine fails is gone from the registry
and says so to every caller. An engine grown past BROWSER_ENGINE_RECYCLE_MB is
replaced: a fresh one takes new sessions while the old one drains, and is
stopped when its last session ends.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
import secrets
from typing import Any
import uuid

from playwright.sync_api import StorageState

from app.browser_host.cdp_mux import (
    CdpCommandError,
    CdpFrame,
    CdpMux,
    CDPTimeoutError,
    cdp_attach,
    cdp_call,
)
from app.browser_host.engine import Engine, launch_engine, resolve_chromium_path
from app.browser_host.memory import memory_usage_mb
from app.browser_host.metrics import SessionMetrics
from app.browser_host.storage import dump_storage_state, seed_storage_state
from app.config.browser_host_settings import browser_host_settings
from app.constants.browser import (
    BROWSER_HOST_LIVENESS_TIMEOUT_SECONDS,
    BROWSER_SESSION_LEASE_SECONDS,
    BrowserEngine,
    HostAdmissionRefusal,
    HostSessionEnd,
)
from app.constants.log_tags import LogTag
from shared.py.wide_events import log, spawn_logged_task

# The health probe backs a container healthcheck, so it gives up well inside the
# orchestrator's own timeout rather than share the generous call budget.
_CDP_HEALTH_TIMEOUT_SECONDS = 5.0
# Reserved for each in-flight and the next session, so a burst of concurrent
# creates cannot overshoot the watermark before their memory materializes.
_SESSION_COST_FLOOR_MB = 50
# How long a create waits for a session to end and free room before it is a 429.
_ADMISSION_WAIT_SECONDS = 5.0
# A context lives exactly as long as its session's connection: Chromium disposes
# it when that connection drops, so no failure path can leave one behind.
_CTX_OPTS: dict[str, Any] = {"disposeOnDetach": True}


@dataclass(eq=False, slots=True)
class HostSession:
    """A single browser session: one isolated context, its page, and the connection carrying both."""

    session_id: str
    context_id: str
    target_id: str
    # The host's own session on the page: it carries the seeded init scripts,
    # which run only while the session that registered them stays attached.
    page_session: str
    # Obscura isolates every CDP connection, so everything driving the session rides this one.
    mux: CdpMux
    engine: Engine
    # The credential its CDP and live-view websocket URLs carry, good for this session only.
    token: str
    # The page the agent last brought to the front; the live view streams it.
    focused_target_id: str
    # Set (and replaced) whenever the focus moves, so every watcher wakes once per move.
    focus_moved: asyncio.Event = field(default_factory=asyncio.Event)
    lease: asyncio.TimerHandle | None = None
    connection_watch: asyncio.Task[None] | None = None
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


class EngineUnresponsiveError(RuntimeError):
    """Raised when no engine serves, or it does not answer on its root connection in time."""


class ChromiumHost:
    """Owns the engines and every live session on them.

    Named for its first engine; fronts Obscura or Chromium alike, selected by
    BROWSER_ENGINE, since everything past launch speaks plain CDP.
    """

    def __init__(self, on_fatal: Callable[[], None]) -> None:
        # Called once when no engine can be brought back, so the process exits and is restarted.
        self._on_fatal = on_fatal
        self.failed = False
        self._chromium_path: str | None = None
        # Chromium's own User-Agent without the headless marker, learned on its first launch.
        self._user_agent: str | None = None
        self._engine: Engine | None = None
        # Replaced engines still serving sessions; each stops when its last one ends.
        self._retiring: set[Engine] = set()
        self._supervisors: dict[Engine, asyncio.Task[None]] = {}
        self._sessions: dict[str, HostSession] = {}
        # Creates admitted but not yet registered, overall and per engine.
        self._pending_slots = 0
        self._creating: Counter[Engine] = Counter()
        self._lock = asyncio.Lock()
        # Notified whenever a session or an admitted create goes away.
        self._slot_freed = asyncio.Condition(self._lock)
        # Serializes launching, replacing and stopping engines.
        self._engine_lock = asyncio.Lock()
        self._stopping = asyncio.Event()

    # --- lifecycle ---

    async def start(self) -> None:
        """Resolve the binary, launch the engine and start supervising it."""
        if browser_host_settings.BROWSER_ENGINE is not BrowserEngine.OBSCURA:
            self._chromium_path = await asyncio.to_thread(resolve_chromium_path)
        self._engine = await self._launch()
        log.info(f"{LogTag.BROWSER} browser host started")

    async def stop(self) -> None:
        """Tear everything down: sessions' timers and watchers, then every engine."""
        self._stopping.set()
        for session in list(self._sessions.values()):
            self._cancel_lease(session)
            if session.connection_watch is not None:
                session.connection_watch.cancel()
        async with self._engine_lock:
            engines = [*self._retiring, *([self._engine] if self._engine is not None else [])]
            self._engine = None
            self._retiring.clear()
            for engine in engines:
                await self._stop_engine(engine)
        log.info(f"{LogTag.BROWSER} browser host stopped")

    @property
    def engine_up(self) -> bool:
        """Whether an engine is serving new sessions."""
        return self._engine is not None and self._engine.alive

    # --- session registry ---

    async def create_context(self, storage_state: StorageState | None) -> HostSession:
        """Create an isolated context with one blank page, seeded with storage_state when given.

        Raises AtCapacityError once admission refuses, so the caller gets a clean
        429 instead of an engine that slowly runs out of memory.
        """
        await self._reserve_slot()
        engine = self._engine
        mux: CdpMux | None = None
        try:
            if engine is None or not engine.alive:
                raise EngineUnresponsiveError("no browser engine is serving")
            self._creating[engine] += 1
            mux = CdpMux(engine.root_ws_url)
            await mux.start()
            session = await self._open_session(mux, engine, storage_state)
            async with self._lock:
                # The reservation becomes the session in one critical section, so a
                # concurrent create never sees it counted twice.
                self._sessions[session.session_id] = session
                self._pending_slots -= 1
        except BaseException:
            async with self._lock:
                self._pending_slots -= 1
                self._slot_freed.notify_all()
            if mux is not None:
                await mux.close()
            raise
        finally:
            if engine is not None:
                self._creating[engine] -= 1
        self._arm_lease(session)
        session.connection_watch = asyncio.create_task(self._watch_connection(session))
        self.sample_resources(session.session_id)
        log.set(browser={"session_id": session.session_id, "operation": "create"})
        log.info(f"{LogTag.BROWSER} browser context created")
        return session

    async def _open_session(
        self, mux: CdpMux, engine: Engine, storage_state: StorageState | None
    ) -> HostSession:
        ctx = await cdp_call(mux, "Target.createBrowserContext", _CTX_OPTS)
        context_id = str(ctx["browserContextId"])
        # Downloads are refused before the context can navigate, scoped to it alone.
        await cdp_call(
            mux, "Browser.setDownloadBehavior", {"behavior": "deny", "browserContextId": context_id}
        )
        target = await cdp_call(
            mux, "Target.createTarget", {"url": "about:blank", "browserContextId": context_id}
        )
        target_id = str(target["targetId"])
        page_session = await cdp_attach(
            mux, target_id, _ignore_host_page_events, timeout=BROWSER_HOST_LIVENESS_TIMEOUT_SECONDS
        )
        # Chromium runs a session's init scripts only once Page is enabled on it.
        await cdp_call(mux, "Page.enable", session_id=page_session)
        if storage_state:
            await seed_storage_state(mux, context_id, page_session, storage_state)
        return HostSession(
            session_id=uuid.uuid4().hex,
            context_id=context_id,
            target_id=target_id,
            page_session=page_session,
            mux=mux,
            engine=engine,
            token=secrets.token_urlsafe(),
            focused_target_id=target_id,
            metrics=SessionMetrics(page_count=1),
        )

    async def dispose_context(self, session_id: str) -> StorageState:
        """Dump the context's storage_state, then dispose it. Returns the dump."""
        session = self._get(session_id)
        # The caller is releasing it now; an expiry must not dispose it under the dump.
        self._cancel_lease(session)
        self.sample_resources(session_id)
        state: StorageState | None = None
        try:
            state = await self._dump(session)
            return state
        finally:
            # The context goes whether or not the dump answered: a hung dump used to
            # leave the session holding a slot after its caller had moved on.
            await self._end_session(session, HostSessionEnd.DISPOSED)
            if state is None:
                # The user's saved login went with it: not a clean disposal.
                log.error(
                    f"{LogTag.BROWSER} browser context disposed without saving its storage state",
                    error_type="StorageDumpFailed",
                )

    async def storage_state(self, session_id: str) -> StorageState:
        """Dump the live context's storage_state and leave it running.

        A run moving to another engine reads it to open there as the same
        signed-in browser; dispose_context is the read that ends the session.
        """
        return await self._dump(self._get(session_id))

    def renew_lease(self, session_id: str) -> None:
        """Extend the session's lease: its run is still alive."""
        self._arm_lease(self._get(session_id))

    def get(self, session_id: str) -> HostSession | None:
        """Return the live session, or None if unknown or gone."""
        return self._sessions.get(session_id)

    def sample_resources(self, session_id: str) -> None:
        """Take one RSS/CPU reading for a session (create, navigation, dispose)."""
        session = self._sessions.get(session_id)
        if session is None or session.engine.sampler is None:
            return
        reading = session.engine.sampler.sample()
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

    def note_focus(self, session_id: str, target_id: str) -> None:
        """Record the page the agent brought to the front, waking every live view of it."""
        session = self._sessions.get(session_id)
        if session is None or session.focused_target_id == target_id:
            return
        session.focused_target_id = target_id
        moved, session.focus_moved = session.focus_moved, asyncio.Event()
        moved.set()

    async def focused_target_id(self, session: HostSession) -> str | None:
        """Return the page to stream: the focused one, else the session's own, else the newest; None when none is open."""
        targets = await cdp_call(session.mux, "Target.getTargets")
        pages = [
            str(ti["targetId"])
            for ti in targets["targetInfos"]
            if ti["type"] == "page" and ti.get("browserContextId") == session.context_id
        ]
        for preferred in (session.focused_target_id, session.target_id):
            if preferred in pages:
                return preferred
        return pages[-1] if pages else None

    async def session_info(self, session_id: str) -> dict[str, Any]:
        """Build the GET /sessions/{id} view: liveness and the page url/title.

        Liveness is read on the engine's root connection, which no page's work can
        hold up; the page on the session's own, which a heavy page holds for seconds.
        """
        session = self._get(session_id)
        responsive, (url, title) = await asyncio.gather(
            session.engine.responsive(BROWSER_HOST_LIVENESS_TIMEOUT_SECONDS),
            self._focused_page_meta(session),
        )
        if not responsive:
            raise EngineUnresponsiveError(session_id)
        return {
            "session_id": session.session_id,
            "live": session.engine.alive and not session.mux.closed,
            "url": url,
            "title": title,
            "metrics": session.metrics.snapshot(),
        }

    async def healthz(self) -> dict[str, Any]:
        """Readiness for /healthz: a bounded CDP round-trip on the serving engine, not just liveness."""
        engine = self._engine
        responsive = engine is not None and await engine.responsive(_CDP_HEALTH_TIMEOUT_SECONDS)
        return {
            "ok": responsive,
            "sessions": len(self._sessions),
            "engine_up": self.engine_up,
            "cdp_responsive": responsive,
        }

    # --- internals ---

    def _get(self, session_id: str) -> HostSession:
        session = self._sessions.get(session_id)
        if session is None:
            raise SessionNotFoundError(session_id)
        return session

    async def _dump(self, session: HostSession) -> StorageState:
        if not session.engine.alive:
            # An empty state here is not the context's, and would be saved over the user's login.
            raise EngineUnresponsiveError(session.session_id)
        return await dump_storage_state(
            session.mux, session.context_id, (session.target_id, session.page_session)
        )

    def _arm_lease(self, session: HostSession) -> None:
        self._cancel_lease(session)
        session.lease = asyncio.get_running_loop().call_later(
            BROWSER_SESSION_LEASE_SECONDS, self._lease_expired, session
        )

    def _cancel_lease(self, session: HostSession) -> None:
        if session.lease is not None:
            session.lease.cancel()
            session.lease = None

    def _lease_expired(self, session: HostSession) -> None:
        session.lease = None
        spawn_logged_task(
            "browser_session_lease_expired",
            self._end_session(session, HostSessionEnd.LEASE_EXPIRED),
        )

    async def _watch_connection(self, session: HostSession) -> None:
        await session.mux.wait_closed()
        if self._sessions.get(session.session_id) is session and not self._stopping.is_set():
            spawn_logged_task(
                "browser_session_connection_lost",
                self._end_session(session, HostSessionEnd.CONNECTION_LOST),
            )

    async def _end_session(self, session: HostSession, how: HostSessionEnd) -> None:
        """Take a session off the registry and dispose its context, once, however it ended."""
        async with self._lock:
            if self._sessions.get(session.session_id) is not session:
                return
            del self._sessions[session.session_id]
            self._slot_freed.notify_all()
        self._cancel_lease(session)
        await self._close_session_connection(session)
        log.set(browser={"session_id": session.session_id, "operation": how.value})
        log.set_ns("browser", metrics=session.metrics.snapshot())
        log.info(f"{LogTag.BROWSER} browser session ended")
        await self._after_session_end(session.engine)

    async def _close_session_connection(self, session: HostSession) -> None:
        """Dispose the session's context and close its connection; a failed dispose is only logged.

        Closing the socket is what frees the session on a per-connection engine;
        disposing the context first keeps a shared-world engine tidy too.
        """
        if session.engine.alive and not session.mux.closed:
            try:
                await cdp_call(
                    session.mux,
                    "Target.disposeBrowserContext",
                    {"browserContextId": session.context_id},
                )
            except Exception as exc:  # the socket close below still frees it; teardown goes on
                log.warning(
                    f"{LogTag.BROWSER} browser host context dispose failed",
                    error_type=type(exc).__name__,
                )
        await session.mux.close()

    def _engine_idle(self, engine: Engine) -> bool:
        busy = any(s.engine is engine for s in self._sessions.values())
        return not busy and self._creating[engine] == 0

    async def _after_session_end(self, engine: Engine) -> None:
        """Stop a drained engine, or replace the serving one once it has outgrown its memory limit.

        Obscura keeps ~50 MB per disposed context, and an 11-hour engine took 57 s
        for a read a fresh one did in 0.8 s; each ended session is when it grows.
        """
        if self._stopping.is_set():
            return
        async with self._engine_lock:
            if engine in self._retiring:
                if self._engine_idle(engine):
                    self._retiring.discard(engine)
                    await self._stop_engine(engine)
                return
            limit = browser_host_settings.BROWSER_ENGINE_RECYCLE_MB
            rss = engine.rss_mb()
            if engine is not self._engine or limit is None or rss is None or rss <= limit:
                return
            try:
                replacement = await self._launch()
            except (
                Exception
            ) as exc:  # the bloated engine still serves; the next session end retries
                log.error(
                    f"{LogTag.BROWSER} browser engine replacement failed to launch",
                    error_type=type(exc).__name__,
                )
                return
            log.warning(
                f"{LogTag.BROWSER} browser engine replaced over its memory limit; draining",
                browser={"operation": "recycle", "rss_mb": round(rss), "limit_mb": limit},
            )
            self._engine = replacement
            if self._engine_idle(engine):
                await self._stop_engine(engine)
            else:
                self._retiring.add(engine)

    async def _launch(self) -> Engine:
        engine, self._user_agent = await launch_engine(
            browser_host_settings.BROWSER_ENGINE, self._chromium_path, self._user_agent
        )
        self._supervisors[engine] = asyncio.create_task(self._supervise(engine))
        return engine

    async def _stop_engine(self, engine: Engine, *, graceful: bool = True) -> None:
        """Stop an engine: its supervisor goes first, so a deliberate stop never reads as a crash."""
        supervisor = self._supervisors.pop(engine, None)
        if supervisor is not None and supervisor is not asyncio.current_task():
            supervisor.cancel()
        await engine.shutdown(graceful=graceful)

    async def _supervise(self, engine: Engine) -> None:
        failure = await engine.wait_failed()
        if self._stopping.is_set():
            return
        log.error(
            f"{LogTag.BROWSER} browser engine failed; its sessions are gone",
            error_type="EngineFailure",
            browser={"operation": "engine_failed", "reason": str(failure)},
        )
        await self._engine_lost(engine)

    async def _engine_lost(self, engine: Engine) -> None:
        async with self._lock:
            dead = [s for s in self._sessions.values() if s.engine is engine]
            for session in dead:
                del self._sessions[session.session_id]
            self._slot_freed.notify_all()
        for session in dead:
            self._cancel_lease(session)
        async with self._engine_lock:
            self._retiring.discard(engine)
            # Killed first, so its sessions' sockets drop at once instead of awaiting a frozen peer.
            await self._stop_engine(engine, graceful=False)
            await asyncio.gather(*(session.mux.close() for session in dead))
            if engine is not self._engine or self._stopping.is_set():
                return
            self._engine = None
            try:
                self._engine = await self._launch()
            except Exception as exc:
                log.error(
                    f"{LogTag.BROWSER} browser engine could not be relaunched; the host exits",
                    error_type=type(exc).__name__,
                )
                self.failed = True
                self._on_fatal()
                return
        log.set(browser={"operation": "engine_relaunched", "dead_sessions": len(dead)})

    def _estimate_session_cost_mb(self) -> float:
        """MB to reserve for the next session: the serving engine's measured average, floored.

        (engine rss - its rss at launch) / its sessions learns the real cost as
        sessions run; only the engine tree is charged, never the host around it.
        """
        floor = float(_SESSION_COST_FLOOR_MB)
        engine = self._engine
        if engine is None:
            return floor
        sessions = sum(1 for s in self._sessions.values() if s.engine is engine)
        rss = engine.rss_mb()
        if sessions == 0 or rss is None:
            return floor
        return max(floor, (rss - engine.base_rss_mb) / sessions)

    async def _reserve_slot(self) -> None:
        """Admit one session when memory allows, else wait for a session to end, then 429.

        Admits while projected usage (current plus a reservation per in-flight
        create and this one) stays under the high watermark. The ceiling is a
        backstop, not the gate; 0 disables it.
        """
        refusals: list[AtCapacityError] = []
        try:
            async with asyncio.timeout(_ADMISSION_WAIT_SECONDS), self._lock:
                while True:
                    refusal = self._admission_refusal()
                    if refusal is None:
                        self._pending_slots += 1
                        return
                    refusals.append(refusal)
                    await self._slot_freed.wait()
        except TimeoutError as exc:
            raise refusals[-1] from exc

    def _admission_refusal(self) -> AtCapacityError | None:
        """Why one more session cannot be admitted right now, or None when it can."""
        used, limit = memory_usage_mb()
        ceiling = browser_host_settings.BROWSER_HOST_MAX_SESSIONS
        sessions, pending = len(self._sessions), self._pending_slots
        over_ceiling = ceiling > 0 and sessions + pending >= ceiling
        projected = used + (pending + 1) * self._estimate_session_cost_mb()
        if (
            not over_ceiling
            and projected <= limit * browser_host_settings.BROWSER_HOST_MEMORY_HIGH_WATERMARK
        ):
            return None
        return AtCapacityError(
            HostAdmissionRefusal.SESSION_CEILING if over_ceiling else HostAdmissionRefusal.MEMORY,
            used_mb=used,
            limit_mb=limit,
            projected_mb=projected,
            sessions=sessions,
            pending=pending,
        )

    async def _focused_page_meta(self, session: HostSession) -> tuple[str | None, str | None]:
        """Read the session's page url and title; none while a heavy page holds its connection."""
        try:
            info = await cdp_call(
                session.mux,
                "Target.getTargetInfo",
                {"targetId": session.focused_target_id},
                timeout=BROWSER_HOST_LIVENESS_TIMEOUT_SECONDS,
            )
        except (CDPTimeoutError, CdpCommandError) as exc:
            # A heavy page holds its connection, or the focused tab just closed.
            log.warning(f"{LogTag.BROWSER} browser page meta unread", error_type=type(exc).__name__)
            return None, None
        target_info = info.get("targetInfo", {})
        return target_info.get("url"), target_info.get("title")


def _ignore_host_page_events(_frame: CdpFrame) -> None:
    """Own the host's page session: what it reports concerns only the agent, which has its own."""
