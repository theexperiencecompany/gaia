"""Regression: the CDP proxy did not allowlist navigation schemes.

Before the fix, Page.navigate/Target.createTarget requests reached
Chromium unfiltered. The agent renders attacker-influenced pages, so a
prompt-injected link could steer the browser at file:///etc/passwd or
chrome://settings — Network.setBlockedURLs only filters subresources,
never a top-level navigation, so this has to be enforced in the proxy itself.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
import copy
import json
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from app.browser_host import proxy
from app.browser_host.proxy import (
    _filter_downstream,
    _navigation_url,
    _refusal_reason,
    _refusal_reply,
    _refused_navigation_url,
    _refused_private_target,
    _rewrite_upstream,
    run_cdp_proxy,
)
from app.constants.log_tags import LogTag
from tests.helpers import captured_wide_event


@pytest.mark.unit
@pytest.mark.parametrize(
    ("method", "url", "expected_refusal"),
    [
        ("Page.navigate", "file:///etc/passwd", "file:///etc/passwd"),
        ("Target.createTarget", "chrome://settings", "chrome://settings"),
        ("Page.navigate", "https://example.com", None),
        ("Target.createTarget", "http://example.com", None),
        ("Page.navigate", "about:blank", None),
        ("Page.navigate", None, None),
        ("Page.enable", "file:///etc/passwd", None),
    ],
    ids=[
        "file-scheme-refused",
        "chrome-scheme-refused",
        "https-allowed",
        "http-allowed",
        "about-blank-allowed",
        "navigate-with-no-url-allowed",
        "non-navigation-method-never-refused",
    ],
)
def test_refused_navigation_url(method: str, url: str | None, expected_refusal: str | None) -> None:
    params: dict[str, Any] = {} if url is None else {"url": url}
    message = {"id": 1, "method": method, "params": params}

    assert _refused_navigation_url(message) == expected_refusal


@pytest.mark.unit
@pytest.mark.parametrize(
    "method",
    ["Browser.setDownloadBehavior", "Page.setDownloadBehavior"],
)
def test_setdownloadbehavior_is_refused(method: str) -> None:
    """A client cannot re-enable downloads the host denied at context creation, even though DownloadsWatchdog sends behavior allow on every run."""
    message = {
        "id": 7,
        "method": method,
        "params": {"behavior": "allow", "downloadPath": "/tmp/browser-use-downloads"},
    }

    reason = _refusal_reason(message)

    assert reason is not None
    assert "downloads are denied" in reason


@pytest.mark.unit
def test_ordinary_command_is_forwarded() -> None:
    """The refusal check must not block anything browser-use legitimately sends."""
    assert _refusal_reason({"id": 8, "method": "Page.enable", "params": {}}) is None
    assert (
        _refusal_reason(
            {"id": 9, "method": "Page.navigate", "params": {"url": "https://example.com"}}
        )
        is None
    )


def test_context_lifecycle_is_refused() -> None:
    """A session must not mint or dispose contexts itself — the host owns the context lifecycle so untracked contexts can't escape capacity/reaper math."""
    for method in ("Target.createBrowserContext", "Target.disposeBrowserContext"):
        msg = {"id": 1, "method": method, "params": {}}
        reason = _refusal_reason(msg)
        assert reason is not None
        assert "context lifecycle" in reason


# ---------------------------------------------------------------------------
# _refused_private_target — the SSRF guard on explicit navigations
# ---------------------------------------------------------------------------


async def test_a_target_resolving_to_a_private_address_is_refused(monkeypatch) -> None:
    guard = AsyncMock(
        side_effect=ValueError("refusing to connect to non-public address 169.254.169.254")
    )
    monkeypatch.setattr(proxy, "assert_public_http_url", guard)

    reason = await _refused_private_target(
        {"id": 3, "method": "Page.navigate", "params": {"url": "http://metadata.internal/latest"}}
    )

    assert reason == (
        "navigation to http://metadata.internal/latest refused: "
        "refusing to connect to non-public address 169.254.169.254"
    )
    guard.assert_awaited_once_with("http://metadata.internal/latest")


async def test_a_public_target_is_forwarded(monkeypatch) -> None:
    guard = AsyncMock()
    monkeypatch.setattr(proxy, "assert_public_http_url", guard)

    assert (
        await _refused_private_target(
            {"id": 3, "method": "Target.createTarget", "params": {"url": "https://example.com"}}
        )
        is None
    )
    guard.assert_awaited_once_with("https://example.com")


async def test_non_navigations_relative_urls_and_foreign_schemes_skip_the_resolver(
    monkeypatch,
) -> None:
    guard = AsyncMock()
    monkeypatch.setattr(proxy, "assert_public_http_url", guard)

    for message in (
        {"id": 1, "method": "Page.enable", "params": {}},
        {"id": 2, "method": "Page.navigate", "params": {"url": "/relative/path"}},
        {"id": 3, "method": "Page.navigate", "params": {"url": "file:///etc/passwd"}},
        {"id": 4, "method": "Page.navigate", "params": {"url": "about:blank"}},
    ):
        assert await _refused_private_target(message) is None
    guard.assert_not_awaited()


def test_navigation_url_is_the_target_or_none_for_blank_missing_or_non_string() -> None:
    assert _navigation_url({"method": "Page.navigate", "params": {"url": "https://a.test"}}) == (
        "https://a.test"
    )
    assert _navigation_url({"method": "Page.navigate", "params": {"url": ""}}) is None
    assert _navigation_url({"method": "Page.navigate", "params": {"url": "about:blank"}}) is None
    assert _navigation_url({"method": "Page.navigate", "params": {"url": 123}}) is None
    assert _navigation_url({"method": "Page.navigate", "params": {}}) is None
    assert _navigation_url({"method": "Page.enable", "params": {"url": "https://a.test"}}) is None


def test_refusal_reason_names_the_foreign_scheme_navigation_it_refuses() -> None:
    assert (
        _refusal_reason(
            {"id": 1, "method": "Page.navigate", "params": {"url": "file:///etc/passwd"}}
        )
        == "navigation to file:///etc/passwd refused: only http and https are allowed"
    )


# Context isolation: one engine carries every user's context, and a session's
# client must only ever see and create targets inside its own.

_OWN = "ctx-own"
_FOREIGN = "ctx-foreign"


def _target(context_id: str | None, target_id: str) -> dict[str, Any]:
    info: dict[str, Any] = {"targetId": target_id, "type": "page"}
    if context_id is not None:
        info["browserContextId"] = context_id
    return info


def test_a_gettargets_reply_lists_only_this_sessions_targets() -> None:
    asked: set[int] = set()
    _rewrite_upstream({"id": 5, "method": "Target.getTargets"}, _OWN, asked)

    reply = _filter_downstream(
        {
            "id": 5,
            "result": {
                "targetInfos": [
                    _target(_OWN, "mine"),
                    _target(_FOREIGN, "theirs"),
                    _target(None, "x"),
                ]
            },
        },
        _OWN,
        asked,
    )

    assert reply == {"id": 5, "result": {"targetInfos": [_target(_OWN, "mine")]}}
    # Answered once: the id is free for the client's next, unrelated command.
    assert asked == set()


def test_a_reply_to_a_command_that_was_not_gettargets_is_passed_untouched() -> None:
    asked: set[int] = set()
    _rewrite_upstream({"id": 5, "method": "Target.getTargets"}, _OWN, asked)
    other = {"id": 6, "result": {"targetInfos": [_target(_FOREIGN, "theirs")]}}

    assert _filter_downstream(copy.deepcopy(other), _OWN, asked) == other
    assert asked == {5}


def test_a_gettargets_id_that_is_not_an_int_is_never_tracked() -> None:
    asked: set[int] = set()

    _rewrite_upstream({"id": "5", "method": "Target.getTargets"}, _OWN, asked)

    assert asked == set()


@pytest.mark.parametrize(
    "result",
    [None, "not-a-dict", {}, {"targetInfos": "not-a-list"}],
    ids=["no-result", "non-dict-result", "no-target-infos", "non-list-target-infos"],
)
def test_a_malformed_gettargets_reply_is_passed_on_rather_than_crashing(result: Any) -> None:
    asked = {5}
    reply: dict[str, Any] = {"id": 5, "error": {"code": -1}}
    if result is not None:
        reply["result"] = result
    expected = json.loads(json.dumps(reply))

    assert _filter_downstream(reply, _OWN, asked) == expected
    assert asked == set()


@pytest.mark.parametrize(
    "method", ["Target.attachedToTarget", "Target.targetCreated", "Target.targetInfoChanged"]
)
def test_a_target_event_from_another_context_is_dropped(method: str) -> None:
    event = {"method": method, "params": {"targetInfo": _target(_FOREIGN, "theirs")}}

    assert _filter_downstream(event, _OWN, set()) is None


@pytest.mark.parametrize(
    "method", ["Target.attachedToTarget", "Target.targetCreated", "Target.targetInfoChanged"]
)
def test_a_target_event_from_this_context_is_delivered(method: str) -> None:
    event = {"method": method, "params": {"targetInfo": _target(_OWN, "mine")}}

    assert _filter_downstream(event, _OWN, set()) == event


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"targetInfo": "not-a-dict"},
        {"targetInfo": _target(None, "browser-wide")},
        {"targetInfo": {"targetId": "t", "browserContextId": 7}},
    ],
    ids=["no-target-info", "non-dict-target-info", "no-context", "non-string-context"],
)
def test_a_target_event_naming_no_context_is_delivered(params: dict[str, Any]) -> None:
    event = {"method": "Target.targetCreated", "params": params}

    assert _filter_downstream(event, _OWN, set()) == event


def test_a_target_event_without_params_is_delivered() -> None:
    event = {"method": "Target.targetInfoChanged"}

    assert _filter_downstream(dict(event), _OWN, set()) == event


def test_a_non_target_event_naming_another_context_is_delivered() -> None:
    """Only the target lifecycle events are context-scoped; everything else is session-routed already."""
    event = {"method": "Page.frameNavigated", "params": {"targetInfo": _target(_FOREIGN, "t")}}

    assert _filter_downstream(event, _OWN, set()) == event


def test_createtarget_is_pinned_to_this_context_even_when_the_client_names_another() -> None:
    message = {
        "id": 1,
        "method": "Target.createTarget",
        "params": {"url": "https://a.test", "browserContextId": _FOREIGN},
    }

    rewritten = _rewrite_upstream(message, _OWN, set())

    assert rewritten["params"] == {"url": "https://a.test", "browserContextId": _OWN}


def test_createtarget_without_params_is_still_pinned_to_this_context() -> None:
    rewritten = _rewrite_upstream({"id": 1, "method": "Target.createTarget"}, _OWN, set())

    assert rewritten["params"] == {"browserContextId": _OWN}


def test_other_commands_are_forwarded_unchanged() -> None:
    message = {"id": 1, "method": "Page.navigate", "params": {"url": "https://a.test"}}

    assert _rewrite_upstream(copy.deepcopy(message), _OWN, set()) == message


def test_a_refusal_is_a_cdp_error_reply_to_the_callers_id() -> None:
    assert json.loads(_refusal_reply(9, "no")) == {
        "id": 9,
        "error": {"code": -32000, "message": "no"},
    }


# ---------------------------------------------------------------------------
# run_cdp_proxy end to end, over a fake engine mux and a fake client socket
# ---------------------------------------------------------------------------


class WebSocketDisconnect(Exception):
    """Stands in for Starlette's disconnect: pumps.is_disconnect matches it by name."""


class _FakeClient:
    """The browser-use side: frames the test feeds in, frames the proxy sends back."""

    def __init__(self) -> None:
        self._inbound: asyncio.Queue[str | None] = asyncio.Queue()
        self.received: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    def send(self, frame: dict[str, Any]) -> None:
        self._inbound.put_nowait(json.dumps(frame))

    def hang_up(self) -> None:
        self._inbound.put_nowait(None)

    async def receive_text(self) -> str:
        raw = await self._inbound.get()
        if raw is None:
            raise WebSocketDisconnect
        return raw

    async def send_text(self, raw: str) -> None:
        self.received.put_nowait(json.loads(raw))

    async def next_frame(self) -> dict[str, Any]:
        return await asyncio.wait_for(self.received.get(), timeout=1.0)


class _FakeMux:
    """The session's engine connection: records what reaches the engine, emits engine frames."""

    def __init__(self) -> None:
        self.forwarded: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.sinks: list[Callable[[dict[str, Any]], None]] = []
        self._closed = asyncio.Event()

    def subscribe(self, sink: Callable[[dict[str, Any]], None]) -> Callable[[], None]:
        self.sinks.append(sink)
        return lambda: self.sinks.remove(sink)

    async def forward(
        self, message: dict[str, Any], sink: Callable[[dict[str, Any]], None]
    ) -> None:
        self.forwarded.put_nowait(message)
        self.reply_to = sink

    def emit(self, frame: dict[str, Any]) -> None:
        for sink in list(self.sinks):
            sink(frame)

    def close(self) -> None:
        self._closed.set()

    async def wait_closed(self) -> None:
        await self._closed.wait()

    async def next_forwarded(self) -> dict[str, Any]:
        return await asyncio.wait_for(self.forwarded.get(), timeout=1.0)


class _FakeHost:
    """Records the per-session activity and navigation bookkeeping the proxy reports."""

    def __init__(self) -> None:
        self.touched: list[str] = []
        self.navigations_started: list[str] = []
        self.navigations_finished: list[str] = []
        self.pages_created: list[str] = []

    def touch(self, session_id: str) -> None:
        self.touched.append(session_id)

    def note_navigation_started(self, session_id: str) -> None:
        self.navigations_started.append(session_id)

    def note_navigation_finished(self, session_id: str) -> None:
        self.navigations_finished.append(session_id)

    def note_page_created(self, session_id: str) -> None:
        self.pages_created.append(session_id)


@pytest.fixture
def public_targets(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every navigation target resolves public; the SSRF guard has its own tests above."""
    monkeypatch.setattr(proxy, "assert_public_http_url", AsyncMock())


class _Proxy:
    def __init__(self) -> None:
        self.host = _FakeHost()
        self.mux = _FakeMux()
        self.client = _FakeClient()
        self.session = SimpleNamespace(session_id="s1", context_id=_OWN, mux=self.mux)
        self.task: asyncio.Task[None] | None = None
        self.event: dict[str, Any] = {}

    def start(self) -> None:
        self.task = asyncio.ensure_future(
            run_cdp_proxy(cast(Any, self.host), cast(Any, self.session), cast(Any, self.client))
        )

    async def stop(self) -> None:
        self.client.hang_up()
        assert self.task is not None
        await asyncio.wait_for(self.task, timeout=1.0)


@pytest.fixture
async def running(public_targets: None) -> AsyncIterator[_Proxy]:
    """Start a proxy inside a wide-event boundary, so what it logs is observable on bridge.event."""
    bridge = _Proxy()
    async with captured_wide_event() as event:
        bridge.event = event
        bridge.start()
        yield bridge
        if bridge.task is not None and not bridge.task.done():
            await bridge.stop()


async def test_a_client_command_reaches_the_engine_pinned_and_the_reply_comes_back(
    running: _Proxy,
) -> None:
    running.client.send({"id": 1, "method": "Target.getTargets"})
    assert await running.mux.next_forwarded() == {"id": 1, "method": "Target.getTargets"}

    running.mux.reply_to(
        {"id": 1, "result": {"targetInfos": [_target(_OWN, "mine"), _target(_FOREIGN, "theirs")]}}
    )

    assert await running.client.next_frame() == {
        "id": 1,
        "result": {"targetInfos": [_target(_OWN, "mine")]},
    }
    # Traffic both ways is activity: an idle-reaper must never take a session in use.
    assert running.host.touched.count("s1") >= 2


async def test_a_createtarget_opens_a_page_in_this_context_and_is_noted(running: _Proxy) -> None:
    running.client.send(
        {
            "id": 2,
            "method": "Target.createTarget",
            "params": {"url": "https://a.test", "browserContextId": _FOREIGN},
        }
    )

    forwarded = await running.mux.next_forwarded()

    assert forwarded["params"]["browserContextId"] == _OWN
    assert running.host.pages_created == ["s1"]
    assert running.host.navigations_started == []


async def test_a_navigation_is_timed_from_the_command_to_the_load_event(running: _Proxy) -> None:
    running.client.send({"id": 3, "method": "Page.navigate", "params": {"url": "https://a.test"}})
    await running.mux.next_forwarded()
    assert running.host.navigations_started == ["s1"]
    assert running.host.navigations_finished == []

    running.mux.emit({"method": "Page.loadEventFired", "params": {"timestamp": 1.0}})

    assert await running.client.next_frame() == {
        "method": "Page.loadEventFired",
        "params": {"timestamp": 1.0},
    }
    assert running.host.navigations_finished == ["s1"]
    assert running.host.pages_created == []


async def test_an_engine_event_from_another_context_never_reaches_the_client(
    running: _Proxy,
) -> None:
    running.mux.emit(
        {"method": "Target.targetCreated", "params": {"targetInfo": _target(_FOREIGN, "x")}}
    )
    running.mux.emit(
        {"method": "Target.targetCreated", "params": {"targetInfo": _target(_OWN, "y")}}
    )

    assert await running.client.next_frame() == {
        "method": "Target.targetCreated",
        "params": {"targetInfo": _target(_OWN, "y")},
    }
    assert running.client.received.empty()
    assert running.host.navigations_finished == []


@pytest.mark.parametrize(("sent_id", "reply_id"), [(4, 4), ("4", None), (None, None)])
async def test_a_refused_command_is_answered_and_never_reaches_the_engine(
    running: _Proxy, sent_id: Any, reply_id: int | None
) -> None:
    refused: dict[str, Any] = {"method": "Page.navigate", "params": {"url": "file:///etc/passwd"}}
    if sent_id is not None:
        refused["id"] = sent_id

    running.client.send(refused)
    reply = await running.client.next_frame()
    running.client.send({"id": 5, "method": "Page.enable"})
    # The next command is the first thing the engine sees: the refused one never went.
    assert await running.mux.next_forwarded() == {"id": 5, "method": "Page.enable"}

    reason = "navigation to file:///etc/passwd refused: only http and https are allowed"
    assert reply == {"id": reply_id, "error": {"code": -32000, "message": reason}}
    assert running.host.navigations_started == []
    assert running.event["warnings"] == [
        {
            "msg": f"{LogTag.BROWSER} browser cdp command refused",
            "error_type": "RefusedCdpCommand",
            "browser": {"session_id": "s1", "method": "Page.navigate", "reason": reason},
        }
    ]


async def test_a_navigation_to_a_private_address_is_refused(
    running: _Proxy, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        proxy, "assert_public_http_url", AsyncMock(side_effect=ValueError("private address"))
    )

    running.client.send({"id": 6, "method": "Page.navigate", "params": {"url": "http://10.0.0.1/"}})

    assert await running.client.next_frame() == {
        "id": 6,
        "error": {
            "code": -32000,
            "message": "navigation to http://10.0.0.1/ refused: private address",
        },
    }
    assert running.mux.forwarded.empty()


async def test_the_client_hanging_up_ends_the_proxy_and_releases_the_engine_stream(
    running: _Proxy,
) -> None:
    assert len(running.mux.sinks) == 1

    await running.stop()

    # Unsubscribed: the shared engine connection outlives this client and must
    # not keep feeding a queue nobody drains.
    assert running.mux.sinks == []
    assert running.event["browser"] == {"session_id": "s1", "operation": "cdp_proxy_closed"}


async def test_the_engine_closing_ends_the_proxy(running: _Proxy) -> None:
    running.mux.close()

    assert running.task is not None
    await asyncio.wait_for(running.task, timeout=1.0)
    assert running.mux.sinks == []
