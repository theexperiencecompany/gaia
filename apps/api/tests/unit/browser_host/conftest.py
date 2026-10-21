"""Shared setup and fakes for the browser-host unit tests.

Admission is memory-based (it reads the real cgroup or system memory), which
would make every create depend on the machine; every test defaults to ample
headroom and no admission wait, and the admission tests set their own.

FakeMux stands in for one session's engine connection and FakeEngine for the
engine behind it: contexts, pages, cookies and localStorage are real state, so a
test asserts what the engine ends up holding. StubEngine stands in for a
launched engine process, so the host never spawns one.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any, ClassVar, cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.browser_host import host as host_mod, proxy, storage
from app.browser_host.cdp_mux import CdpCommandError, CdpMux, sinks_for
from app.browser_host.engine import Engine
from app.browser_host.host import BrowserHost, HostSession, LaunchEngine, MemoryProbe
from app.constants.browser import BrowserEngine, EngineExit

FAKE_ROOT_WS_URL = "ws://127.0.0.1:9222/devtools/browser/fake"
# The browser's own context, where CDP puts anything that names no browserContextId.
DEFAULT_CONTEXT = ""
_DOWNLOAD_BEHAVIORS = frozenset({"deny", "allow", "allowAndName", "default"})

Sink = Callable[[dict[str, Any]], None]


@pytest.fixture(autouse=True)
def _no_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub the proxy's DNS-resolving guard so no unit test touches real DNS."""
    monkeypatch.setattr(proxy, "assert_public_http_url", AsyncMock())


@pytest.fixture(autouse=True)
def _no_admission_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(host_mod, "_ADMISSION_WAIT_SECONDS", 0.0)


class AdmissionProbe:
    """A memory probe with headroom for any number of sessions, counting how often admission asks it."""

    def __init__(self, used_mb: float = 100.0, limit_mb: float = 100_000.0) -> None:
        self.reading = (used_mb, limit_mb)
        self.asked = 0
        self._asked = asyncio.Event()

    def __call__(self) -> tuple[float, float]:
        self.asked += 1
        self._asked.set()
        return self.reading

    async def until_asked(self, times: int) -> None:
        """Return once admission has asked times times; a create that asked is then queued or admitted."""
        async with asyncio.timeout(2):
            while self.asked < times:
                self._asked.clear()
                await self._asked.wait()


class FakeMux:
    """Stand-in for one session's CdpMux, covering its whole surface.

    Records every (method, params, session_id) sent and every frame forwarded,
    answers from a per-method map (or queue), and pushes frames at subscribers
    via emit, routed by the mux's own sinks_for so the two cannot drift.
    """

    _DEFAULTS: ClassVar[dict[str, dict[str, Any]]] = {
        "Target.createBrowserContext": {"browserContextId": "ctx-low"},
        "Target.createTarget": {"targetId": "t-low"},
        "Target.getTargets": {"targetInfos": []},
        "Storage.getCookies": {"cookies": []},
        "Runtime.evaluate": {"result": {"value": None}},
    }

    def __init__(
        self,
        responses: dict[str, dict[str, Any]] | None = None,
        *,
        queues: dict[str, list[dict[str, Any]]] | None = None,
        hang_on: str | None = None,
    ) -> None:
        self.responses: dict[str, dict[str, Any]] = {**self._DEFAULTS, **(responses or {})}
        self.queues: dict[str, list[dict[str, Any]]] = {
            method: list(items) for method, items in (queues or {}).items()
        }
        self.hang_on = hang_on
        self.hang_started = asyncio.Event()
        self.hanging = 0
        # Raised by every call once set: an engine that has stopped answering.
        self.send_error: Exception | None = None
        self.calls: list[tuple[str, dict[str, Any] | None, str | None]] = []
        self.forwarded: list[dict[str, Any]] = []
        self.sinks: list[tuple[Sink, str | None]] = []
        self.attached: list[str] = []
        self.detached: list[str] = []
        self.urls: list[str] = []
        self.started = 0
        self.close_count = 0
        self.close_signal = asyncio.Event()
        self._attach_ids = 0

    async def _hang(self) -> None:
        """Never answer, counting the calls left hanging."""
        self.hanging += 1
        self.hang_started.set()
        await asyncio.Event().wait()

    async def until_hanging(self, calls: int) -> None:
        """Return once calls are left hanging at once."""
        async with asyncio.timeout(2):
            while self.hanging < calls:
                self.hang_started.clear()
                await self.hang_started.wait()

    def build(self, url: str) -> FakeMux:
        """Stand in for the CdpMux constructor: one fake, however many times it is built."""
        self.urls.append(url)
        return self

    @property
    def closed(self) -> bool:
        return self.close_signal.is_set()

    async def start(self) -> None:
        self.started += 1

    async def close(self) -> None:
        self.close_count += 1
        self.close_signal.set()

    async def wait_closed(self) -> None:
        await self.close_signal.wait()

    def subscribe(self, sink: Sink) -> Callable[[], None]:
        entry: tuple[Sink, str | None] = (sink, None)
        self.sinks.append(entry)

        def _remove() -> None:
            if entry in self.sinks:
                self.sinks.remove(entry)

        return _remove

    async def attach(self, target_id: str, owner: Sink) -> str:
        await self.send_raw("Target.attachToTarget", {"targetId": target_id, "flatten": True})
        self._attach_ids += 1
        session_id = f"attach-{self._attach_ids}"
        self.sinks.append((owner, session_id))
        self.attached.append(session_id)
        return session_id

    async def detach(self, session_id: str) -> None:
        try:
            await self.send_raw("Target.detachFromTarget", {"sessionId": session_id})
        finally:
            self.sinks = [entry for entry in self.sinks if entry[1] != session_id]
            self.detached.append(session_id)

    def emit(self, *frames: dict[str, Any]) -> None:
        """Push frames at the subscribers entitled to them, routed by the real rule."""
        for frame in frames:
            for sink in sinks_for(self.sinks, frame):
                sink(frame)

    async def send_raw(
        self, method: str, params: dict[str, Any] | None = None, session_id: str | None = None
    ) -> dict[str, Any]:
        self.calls.append((method, params, session_id))
        if self.send_error is not None:
            raise self.send_error
        if method == self.hang_on:
            await self._hang()
        queue = self.queues.get(method)
        if queue:
            return queue.pop(0)
        return self.responses.get(method, {})

    async def forward(self, frame: dict[str, Any], reply_to: Sink) -> None:
        self.forwarded.append(frame)

    @property
    def methods(self) -> list[str]:
        return [method for method, _, _ in self.calls]

    def params_for(self, method: str) -> list[dict[str, Any] | None]:
        return [params for sent, params, _ in self.calls if sent == method]


class FakeEngine(FakeMux):
    """One engine connection that answers the CDP the host speaks the way an engine does.

    Required parameters are enforced, an omitted browserContextId lands in the
    browser's default context, cookies come back in Network.Cookie's full shape,
    and a session-scoped command needs an attached session.
    """

    def __init__(self) -> None:
        super().__init__()
        self.contexts: dict[str, dict[str, Any]] = {
            DEFAULT_CONTEXT: {"download": None, "cookies": []}
        }
        self.pages: dict[str, dict[str, Any]] = {}
        self.sessions: dict[str, str] = {}
        # Page targets that refuse the storage read, as a page mid-crash does.
        self.unreadable: set[str] = set()
        self._ids = 0

    def _next(self, prefix: str) -> str:
        self._ids += 1
        return f"{prefix}-{self._ids}"

    def open_page(self, context_id: str, *, url: str, storage: dict[str, str] | None = None) -> str:
        """Put a page the user opened into a context, with its origin's localStorage."""
        target_id = self._next("page")
        self.pages[target_id] = {
            "context": context_id,
            "url": url,
            "title": "",
            "storage": dict(storage or {}),
            "scripts": [],
        }
        return target_id

    async def attach(self, target_id: str, owner: Sink) -> str:
        if target_id not in self.pages:
            raise CdpCommandError({"message": "No target with given id found"})
        session_id = self._next("attach")
        self.sessions[session_id] = target_id
        self.sinks.append((owner, session_id))
        self.attached.append(session_id)
        return session_id

    async def detach(self, session_id: str) -> None:
        self.sessions.pop(session_id, None)
        self.sinks = [entry for entry in self.sinks if entry[1] != session_id]
        self.detached.append(session_id)

    async def send_raw(
        self, method: str, params: dict[str, Any] | None = None, session_id: str | None = None
    ) -> dict[str, Any]:
        self.calls.append((method, params, session_id))
        if self.send_error is not None:
            raise self.send_error
        if method == self.hang_on:
            await self._hang()
        handler = getattr(self, "_" + method.replace(".", "_"), None)
        if handler is None:
            raise CdpCommandError({"message": f"'{method}' wasn't found"})
        result: dict[str, Any] = handler(params or {}, session_id)
        return result

    @staticmethod
    def _required(params: dict[str, Any], *names: str) -> None:
        missing = [name for name in names if name not in params]
        if missing:
            raise CdpCommandError({"message": f"Invalid parameters: missing {missing}"})

    def _context(self, params: dict[str, Any]) -> dict[str, Any]:
        context_id = params.get("browserContextId", DEFAULT_CONTEXT)
        if context_id not in self.contexts:
            raise CdpCommandError({"message": f"Failed to find browser context {context_id}"})
        return self.contexts[context_id]

    def _page_for(self, session_id: str | None) -> dict[str, Any]:
        target_id = self.sessions.get(session_id or "")
        if target_id is None:
            raise CdpCommandError({"message": f"No session with given id: {session_id}"})
        return self.pages[target_id]

    def _Target_createBrowserContext(self, params: dict[str, Any], _: str | None) -> dict[str, Any]:
        context_id = self._next("ctx")
        self.contexts[context_id] = {"download": None, "cookies": []}
        return {"browserContextId": context_id}

    def _Target_disposeBrowserContext(
        self, params: dict[str, Any], _: str | None
    ) -> dict[str, Any]:
        self._required(params, "browserContextId")
        self._context(params)
        del self.contexts[params["browserContextId"]]
        self.pages = {
            t: p for t, p in self.pages.items() if p["context"] != params["browserContextId"]
        }
        return {}

    def _Browser_setDownloadBehavior(self, params: dict[str, Any], _: str | None) -> dict[str, Any]:
        self._required(params, "behavior")
        if params["behavior"] not in _DOWNLOAD_BEHAVIORS:
            raise CdpCommandError({"message": f"Invalid behavior: {params['behavior']}"})
        self._context(params)["download"] = params["behavior"]
        return {}

    def _Target_createTarget(self, params: dict[str, Any], _: str | None) -> dict[str, Any]:
        self._required(params, "url")
        self._context(params)
        target_id = self.open_page(
            params.get("browserContextId", DEFAULT_CONTEXT), url=params["url"]
        )
        return {"targetId": target_id}

    def _Target_getTargets(self, params: dict[str, Any], _: str | None) -> dict[str, Any]:
        infos = [
            {
                "targetId": target_id,
                "type": "page",
                "url": page["url"],
                "title": page["title"],
                "browserContextId": page["context"],
            }
            for target_id, page in self.pages.items()
        ]
        return {"targetInfos": infos}

    def _Target_getTargetInfo(self, params: dict[str, Any], _: str | None) -> dict[str, Any]:
        self._required(params, "targetId")
        page = self.pages.get(params["targetId"])
        if page is None:
            raise CdpCommandError({"message": "No target with given id found"})
        return {"targetInfo": {"url": page["url"], "title": page["title"]}}

    def _Page_enable(self, params: dict[str, Any], session_id: str | None) -> dict[str, Any]:
        self._page_for(session_id)
        return {}

    def _Runtime_evaluate(self, params: dict[str, Any], session_id: str | None) -> dict[str, Any]:
        self._required(params, "expression")
        page = self._page_for(session_id)
        if self.sessions[session_id or ""] in self.unreadable:
            raise CdpCommandError({"message": "Execution context was destroyed."})
        if params["expression"] != storage._LOCAL_STORAGE_DUMP_JS:
            raise AssertionError(f"unexpected script: {params['expression']!r}")
        url = page["url"]
        origin = "/".join(url.split("/")[:3]) if "://" in url else "null"
        value = {
            "origin": origin,
            "localStorage": [{"name": k, "value": v} for k, v in page["storage"].items()],
        }
        if params.get("returnByValue") is not True:
            return {"result": {"type": "object", "objectId": "obj-1"}}
        return {"result": {"type": "object", "value": value}}

    def _Page_addScriptToEvaluateOnNewDocument(
        self, params: dict[str, Any], session_id: str | None
    ) -> dict[str, Any]:
        self._required(params, "source")
        self._page_for(session_id)["scripts"].append(params["source"])
        return {"identifier": self._next("script")}

    def _Storage_setCookies(self, params: dict[str, Any], _: str | None) -> dict[str, Any]:
        self._required(params, "cookies")
        jar = self._context(params)["cookies"]
        for cookie in params["cookies"]:
            self._required(cookie, "name", "value")
            expires = cookie.get("expires")
            stored = {
                "name": cookie["name"],
                "value": cookie["value"],
                "domain": cookie.get("domain", ""),
                "path": cookie.get("path", "/"),
                "expires": expires if expires is not None else -1,
                "httpOnly": cookie.get("httpOnly", False),
                "secure": cookie.get("secure", False),
                "session": expires is None,
            }
            if "sameSite" in cookie:
                stored["sameSite"] = cookie["sameSite"]
            jar.append(stored)
        return {}

    def _Storage_getCookies(self, params: dict[str, Any], _: str | None) -> dict[str, Any]:
        return {"cookies": [dict(c) for c in self._context(params)["cookies"]]}


class StubEngine:
    """A launched engine the host can drive without a process: alive until told otherwise."""

    def __init__(self, *, rss_mb: float = 100.0, kind: BrowserEngine = BrowserEngine.OBSCURA):
        self.kind = kind
        self.root_ws_url = FAKE_ROOT_WS_URL
        self.base_rss_mb = 0.0
        self.sampler = MagicMock(sample=MagicMock(return_value=(512.0, 10.0)))
        self.current_rss_mb: float | None = rss_mb
        self.answers = True
        self.asked_within: list[float] = []
        self.is_alive = True
        self.shutdowns: list[bool] = []
        self.failure = asyncio.get_running_loop().create_future()

    @property
    def alive(self) -> bool:
        return self.is_alive

    async def responsive(self, timeout: float) -> bool:
        self.asked_within.append(timeout)
        return self.is_alive and self.answers

    def rss_mb(self) -> float | None:
        return self.current_rss_mb

    async def wait_failed(self) -> EngineExit:
        reason: EngineExit = await self.failure
        return reason

    def fail(self, reason: EngineExit = EngineExit.PROCESS_EXITED) -> None:
        """Make the engine fail the way its supervisor watches for."""
        self.is_alive = False
        self.failure.set_result(reason)

    async def shutdown(self, *, graceful: bool = True) -> None:
        self.is_alive = False
        self.shutdowns.append(graceful)


def as_engine(stub: StubEngine) -> Engine:
    return cast(Engine, stub)


class Launcher:
    """Hands each engine launch the next stub, recording the launch; one past the last raises IndexError."""

    def __init__(self, *engines: StubEngine) -> None:
        self._queue = list(engines)
        self.launched: list[StubEngine] = []
        self._changed = asyncio.Condition()

    async def __call__(
        self, kind: BrowserEngine, chromium_path: str | None, user_agent: str | None
    ) -> tuple[Engine, str | None]:
        stub = self._queue.pop(0)
        self.launched.append(stub)
        async with self._changed:
            self._changed.notify_all()
        return as_engine(stub), user_agent

    async def until_launched(self, count: int) -> None:
        """Return once count engines have launched."""
        async with asyncio.timeout(2), self._changed:
            await self._changed.wait_for(lambda: len(self.launched) >= count)


def make_host(
    engine: StubEngine | None = None,
    *,
    mux: FakeMux | None = None,
    launch: LaunchEngine | None = None,
    memory: MemoryProbe | None = None,
    on_fatal: Callable[[], None] | None = None,
) -> BrowserHost:
    """Build a host on fakes: serving on engine (a fresh stub) unless it is to launch its own.

    Every connection dials mux when one is given, else a FakeEngine of its own.
    """
    host = BrowserHost(
        on_fatal=on_fatal if on_fatal is not None else MagicMock(),
        launch=launch if launch is not None else Launcher(),
        connect=mux.build if mux is not None else (lambda _url: cast(CdpMux, FakeEngine())),
        memory=memory if memory is not None else AdmissionProbe(),
    )
    if launch is None:
        host._engine = as_engine(engine if engine is not None else StubEngine())
    return host


def make_session(
    session_id: str = "s1",
    context_id: str = "ctx1",
    target_id: str = "t1",
    *,
    mux: FakeMux | None = None,
    engine: StubEngine | None = None,
) -> HostSession:
    """Build a HostSession carrying a FakeMux, since a session is a connection."""
    return HostSession(
        session_id=session_id,
        context_id=context_id,
        target_id=target_id,
        page_session="host-page",
        mux=cast(CdpMux, mux if mux is not None else FakeMux()),
        engine=as_engine(engine if engine is not None else StubEngine()),
        token="tok",
        focused_target_id=target_id,
    )
