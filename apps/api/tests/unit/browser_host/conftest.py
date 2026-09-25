"""Shared setup and fakes for the browser-host unit tests.

Admission is memory-based (ChromiumHost._reserve_slot reads the real cgroup /
system memory), which would make every create test depend on the machine's live
memory. Default every test to ample headroom and no backpressure wait so the
existing behaviour tests stay hermetic and fast; the memory-gate tests override
chromium.memory_usage_mb themselves to simulate pressure.

FakeMux stands in for a session's one engine connection. make_host deliberately
leaves the host's root connection unset, so any session work that regressed to
the shared connection fails loudly instead of silently crossing connections. The
live view's paced capture is parked by default so it cannot tick mid-test.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any, ClassVar, cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.browser_host import chromium, proxy, screencast
from app.browser_host.cdp_mux import CdpMux, sinks_for
from app.browser_host.chromium import ChromiumHost, HostSession

FAKE_ROOT_WS_URL = "ws://127.0.0.1:9222/devtools/browser/fake"
# Longer than any test runs: the live view's paced capture must only fire for the
# tests that drive it, never as a real 0.5s tick landing mid-assertion.
_NEVER_SECONDS = 3600.0


@pytest.fixture(autouse=True)
def _no_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub the proxy's DNS-resolving guard so no unit test touches real DNS."""
    monkeypatch.setattr(proxy, "assert_public_http_url", AsyncMock())


@pytest.fixture(autouse=True)
def _park_the_live_view_pull(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hold the screencast fallback capture still; the pull tests set their own interval."""
    monkeypatch.setattr(screencast, "_PULL_INTERVAL_SECONDS", _NEVER_SECONDS)


@pytest.fixture(autouse=True)
def _ample_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chromium, "memory_usage_mb", lambda: (100.0, 100_000.0))
    monkeypatch.setattr(chromium, "_ADMISSION_WAIT_SECONDS", 0.0)


class FakeMux:
    """Stand-in for one session's CdpMux, covering its whole surface.

    Records every (method, params, session_id) it is asked to send and every
    frame forwarded verbatim, answers from a per-method map (or a per-method
    queue when the answer must vary call to call), tracks start/close so a
    leaked connection is visible, and pushes frames at subscribers via emit,
    which routes them through the mux's own sinks_for so the two cannot drift.
    """

    # Sensible per-method answers; anything unlisted replies with an empty object,
    # which is what the real CDP layer treats as a no-payload ack.
    _DEFAULTS: ClassVar[dict[str, dict[str, Any]]] = {
        "Target.createBrowserContext": {"browserContextId": "ctx-low"},
        "Target.createTarget": {"targetId": "t-low"},
        "Target.getTargets": {"targetInfos": []},
        "Storage.getCookies": {"cookies": []},
        "Target.attachToTarget": {"sessionId": "sess-attach"},
        "Runtime.evaluate": {"result": {"value": None}},
    }

    def __init__(
        self,
        responses: dict[str, dict[str, Any]] | None = None,
        *,
        queues: dict[str, list[dict[str, Any]]] | None = None,
        hang_on: str | None = None,
        hang_call_count: int = 0,
        fail_on_first_call: dict[str, Exception] | None = None,
    ) -> None:
        self.responses: dict[str, dict[str, Any]] = {**self._DEFAULTS, **(responses or {})}
        self.queues: dict[str, list[dict[str, Any]]] = {
            method: list(items) for method, items in (queues or {}).items()
        }
        self.hang_on = hang_on
        # One event per expected call to the hanging method, so a test can await
        # "the call has started" without a real sleep or a racy poll.
        self.call_started = [asyncio.Event() for _ in range(hang_call_count)]
        self.fail_on_first_call = dict(fail_on_first_call or {})
        # Raised by every call once set, for the consumer that must survive an
        # engine that has stopped answering rather than one bad command.
        self.send_error: Exception | None = None
        self.calls: list[tuple[str, dict[str, Any] | None, str | None]] = []
        self.forwarded: list[dict[str, Any]] = []
        # The sink each forwarded frame named as the owner of its reply.
        self.reply_sinks: list[Callable[[dict[str, Any]], None]] = []
        self.urls: list[str] = []
        # Each entry is a sink and the CDP session it claims, mirroring the real
        # mux: a claimed session's frames reach its owner and nobody else.
        self.sinks: list[tuple[Callable[[dict[str, Any]], None], str | None]] = []
        self.started = 0
        self.closed = False
        self.close_count = 0
        # Set by close(), or by a test simulating the engine dropping the socket;
        # until then wait_closed() never resolves, as on a live connection.
        self.close_signal = asyncio.Event()
        self.unsubscribed: list[Callable[[dict[str, Any]], None]] = []
        self._counts: dict[str, int] = {}

    def build(self, url: str) -> FakeMux:
        """Stand in for the CdpMux constructor: one fake, however many times it is built."""
        self.urls.append(url)
        return self

    async def start(self) -> None:
        self.started += 1
        self.closed = False

    async def close(self) -> None:
        self.closed = True
        self.close_count += 1
        self.close_signal.set()

    async def wait_closed(self) -> None:
        await self.close_signal.wait()

    def subscribe(
        self, sink: Callable[[dict[str, Any]], None], *, owns_session: str | None = None
    ) -> Callable[[], None]:
        entry = (sink, owns_session)
        self.sinks.append(entry)

        def _remove() -> None:
            if entry in self.sinks:  # the real remover tolerates a second call
                self.sinks.remove(entry)
            self.unsubscribed.append(sink)

        return _remove

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
        self._counts[method] = self._counts.get(method, 0) + 1
        if method in self.fail_on_first_call and self._counts[method] == 1:
            raise self.fail_on_first_call[method]
        if method == self.hang_on:
            index = self._counts[method] - 1
            if index < len(self.call_started):
                self.call_started[index].set()
            await asyncio.Event().wait()  # never resolves
        queue = self.queues.get(method)
        if queue:
            return queue.pop(0)
        return self.responses.get(method, {})

    async def forward(
        self, frame: dict[str, Any], reply_to: Callable[[dict[str, Any]], None]
    ) -> None:
        self.forwarded.append(frame)
        self.reply_sinks.append(reply_to)

    @property
    def owned_sessions(self) -> list[str | None]:
        """The CDP session each live subscriber claimed, so a test can assert the claim."""
        return [owned for _, owned in self.sinks]

    @property
    def methods(self) -> list[str]:
        return [method for method, _, _ in self.calls]

    def params_for(self, method: str) -> list[dict[str, Any] | None]:
        return [params for sent, params, _ in self.calls if sent == method]

    def sources_for(self, method: str) -> list[str]:
        return [p["source"] for sent, p, _ in self.calls if sent == method and p is not None]


@pytest.fixture
def mux(monkeypatch: pytest.MonkeyPatch) -> FakeMux:
    """Hand back the fake connection every create_context in this test builds."""
    return install_mux(monkeypatch)


def install_mux(monkeypatch: pytest.MonkeyPatch, fake: FakeMux | None = None) -> FakeMux:
    """Make create_context build this fake instead of dialing a real engine connection."""
    fake = fake if fake is not None else FakeMux()
    monkeypatch.setattr(chromium, "CdpMux", fake.build)
    return fake


def make_host() -> ChromiumHost:
    """Build a started-looking host with NO root connection, so session work must ride its own mux."""
    host = ChromiumHost()
    host._proc = MagicMock(returncode=None)  # chromium_up == True
    host._root_ws_url = FAKE_ROOT_WS_URL
    return host


def make_session(
    session_id: str = "s1",
    context_id: str = "ctx1",
    target_id: str = "t1",
    *,
    mux: FakeMux | None = None,
    last_activity_at: float = 0.0,
) -> HostSession:
    """Build a HostSession carrying a FakeMux, since a session is now a connection.

    created_at, viewer_count and dead are not parameters: the handful of tests
    that vary one say so with dataclasses.replace at the call site.
    """
    return HostSession(
        session_id=session_id,
        context_id=context_id,
        target_id=target_id,
        mux=cast(CdpMux, mux if mux is not None else FakeMux()),
        created_at=0.0,
        last_activity_at=last_activity_at,
    )


class CdpProtocolError(RuntimeError):
    """What the real mux raises when the engine answers a command with an error object."""


_DOWNLOAD_BEHAVIORS = frozenset({"deny", "allow", "allowAndName", "default"})
# The browser's own context, where CDP puts anything that names no browserContextId.
DEFAULT_CONTEXT = ""


class FakeEngine(FakeMux):
    """One engine connection that answers the CDP the host speaks the way the engine does.

    Contexts, pages, cookies and localStorage are real state here, so a test
    asserts what the engine ends up holding rather than which frames were sent.
    Required parameters are enforced, an omitted browserContextId lands in the
    browser's default context, cookies come back in Network.Cookie's full shape,
    an object result carries a value only when asked returnByValue, and a
    session-scoped command needs a flat attach.
    """

    def __init__(self) -> None:
        super().__init__()
        self.contexts: dict[str, dict[str, Any]] = {
            DEFAULT_CONTEXT: {"download": None, "cookies": []}
        }
        self.pages: dict[str, dict[str, Any]] = {}
        # sessionId -> (targetId, flat)
        self.attached: dict[str, tuple[str, bool]] = {}
        self._ids = 0

    def _next(self, prefix: str) -> str:
        self._ids += 1
        return f"{prefix}-{self._ids}"

    def open_page(
        self,
        context_id: str,
        *,
        url: str,
        title: str = "",
        storage: dict[str, str] | None = None,
        kind: str = "page",
    ) -> str:
        """Put a target the user opened into a context, with its origin's localStorage."""
        target_id = self._next(kind)
        self.pages[target_id] = {
            "context": context_id,
            "type": kind,
            "url": url,
            "title": title,
            "storage": dict(storage or {}),
            "scripts": [],
        }
        return target_id

    async def send_raw(
        self, method: str, params: dict[str, Any] | None = None, session_id: str | None = None
    ) -> dict[str, Any]:
        self.calls.append((method, params, session_id))
        if self.send_error is not None:
            raise self.send_error
        handler = getattr(self, "_" + method.replace(".", "_"), None)
        if handler is None:
            raise CdpProtocolError(f"'{method}' wasn't found")
        result: dict[str, Any] = handler(params or {}, session_id)
        return result

    @staticmethod
    def _required(params: dict[str, Any], *names: str) -> None:
        missing = [name for name in names if name not in params]
        if missing:
            raise CdpProtocolError(f"Invalid parameters: missing {missing}")

    def _context(self, params: dict[str, Any]) -> dict[str, Any]:
        context_id = params.get("browserContextId", DEFAULT_CONTEXT)
        if context_id not in self.contexts:
            raise CdpProtocolError(f"Failed to find browser context for id {context_id}")
        return self.contexts[context_id]

    def _page_for(self, session_id: str | None) -> dict[str, Any]:
        target_id, flat = self.attached.get(session_id or "", ("", False))
        if not flat:
            raise CdpProtocolError(f"No session with given id: {session_id}")
        return self.pages[target_id]

    def _Browser_getVersion(self, params: dict[str, Any], _: str | None) -> dict[str, Any]:
        return {"userAgent": "Mozilla/5.0 Chrome/153.0.0.0 Safari/537.36"}

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
            raise CdpProtocolError(f"Invalid behavior: {params['behavior']}")
        self._context(params)["download"] = params["behavior"]
        return {}

    def _Target_createTarget(self, params: dict[str, Any], _: str | None) -> dict[str, Any]:
        self._required(params, "url")
        self._context(params)
        target_id = self._next("page")
        url = params["url"]
        self.pages[target_id] = {
            "context": params.get("browserContextId", DEFAULT_CONTEXT),
            "type": "page",
            "url": url,
            "title": "",
            "storage": {},
            "scripts": [],
        }
        return {"targetId": target_id}

    def _Target_getTargets(self, params: dict[str, Any], _: str | None) -> dict[str, Any]:
        infos = [
            {
                "targetId": target_id,
                "type": page["type"],
                "url": page["url"],
                "title": page["title"],
                "browserContextId": page["context"],
            }
            for target_id, page in self.pages.items()
        ]
        return {"targetInfos": infos}

    def _Target_attachToTarget(self, params: dict[str, Any], _: str | None) -> dict[str, Any]:
        self._required(params, "targetId")
        if params["targetId"] not in self.pages:
            raise CdpProtocolError("No target with given id found")
        session_id = self._next("attach")
        self.attached[session_id] = (params["targetId"], params.get("flatten") is True)
        return {"sessionId": session_id}

    def _Target_detachFromTarget(self, params: dict[str, Any], _: str | None) -> dict[str, Any]:
        if params.get("sessionId") not in self.attached:
            raise CdpProtocolError("No session with given id")
        del self.attached[params["sessionId"]]
        return {}

    def _Runtime_evaluate(self, params: dict[str, Any], session_id: str | None) -> dict[str, Any]:
        self._required(params, "expression")
        page = self._page_for(session_id)
        if params["expression"] != chromium._LOCAL_STORAGE_DUMP_JS:
            raise AssertionError(f"unexpected script: {params['expression']!r}")
        origin = "/".join(page["url"].split("/")[:3])
        value = {
            "origin": origin,
            "localStorage": [{"name": k, "value": v} for k, v in page["storage"].items()],
        }
        if params.get("returnByValue") is not True:
            return {"result": {"type": "object", "className": "Object", "objectId": "obj-1"}}
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
                "size": len(cookie["name"]) + len(cookie["value"]),
                "httpOnly": cookie.get("httpOnly", False),
                "secure": cookie.get("secure", False),
                "session": expires is None,
                "priority": "Medium",
            }
            if "sameSite" in cookie:
                stored["sameSite"] = cookie["sameSite"]
            jar.append(stored)
        return {}

    def _Storage_getCookies(self, params: dict[str, Any], _: str | None) -> dict[str, Any]:
        return {"cookies": [dict(c) for c in self._context(params)["cookies"]]}
