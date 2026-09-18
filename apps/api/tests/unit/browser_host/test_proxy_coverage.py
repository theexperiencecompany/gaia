"""Coverage for proxy.py helpers not hit by test_proxy.py."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import copy
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from app.browser_host import proxy as proxy_mod
from app.browser_host.proxy import (
    _CDP_REFUSED_CODE,
    LogTag,
    _event_context_id,
    _filter_downstream,
    _refusal_reason,
    _refusal_reply,
    _refused_navigation_url,
    _rewrite_upstream,
)
from tests.unit.browser_host.conftest import FakeMux, make_session

# ---------------------------------------------------------------------------
# _refused_navigation_url edge cases
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_refused_navigation_url_missing_params_returns_none() -> None:
    assert _refused_navigation_url({"method": "Page.navigate"}) is None
    assert _refused_navigation_url({"method": "Page.navigate", "params": None}) is None
    assert _refused_navigation_url({"method": "Page.navigate", "params": "oops"}) is None


@pytest.mark.unit
def test_refused_navigation_url_url_not_str_returns_none() -> None:
    assert _refused_navigation_url({"method": "Page.navigate", "params": {"url": 123}}) is None
    assert _refused_navigation_url({"method": "Page.navigate", "params": {"url": None}}) is None


@pytest.mark.unit
def test_refused_navigation_url_empty_url_returns_none() -> None:
    assert _refused_navigation_url({"method": "Page.navigate", "params": {"url": ""}}) is None


@pytest.mark.unit
def test_refused_navigation_url_relative_url_not_refused() -> None:
    # empty scheme => relative, allowed
    assert (
        _refused_navigation_url({"method": "Page.navigate", "params": {"url": "/relative/path"}})
        is None
    )
    assert (
        _refused_navigation_url({"method": "Page.navigate", "params": {"url": "relative/path"}})
        is None
    )
    assert _refused_navigation_url({"method": "Page.navigate", "params": {"url": "#hash"}}) is None
    assert (
        _refused_navigation_url({"method": "Page.navigate", "params": {"url": "?query=1"}}) is None
    )


@pytest.mark.unit
def test_refused_navigation_url_about_blank_not_refused() -> None:
    assert (
        _refused_navigation_url({"method": "Page.navigate", "params": {"url": "about:blank"}})
        is None
    )
    assert (
        _refused_navigation_url({"method": "Target.createTarget", "params": {"url": "about:blank"}})
        is None
    )


@pytest.mark.unit
def test_refused_navigation_url_non_navigation_method_never_refused() -> None:
    for meth in ["Page.enable", "Runtime.evaluate", "Target.getTargets", "Browser.getVersion"]:
        assert (
            _refused_navigation_url({"method": meth, "params": {"url": "file:///etc/passwd"}})
            is None
        )


@pytest.mark.unit
def test_refused_navigation_url_refuses_foreign_schemes() -> None:
    for url in [
        "file:///etc/passwd",
        "chrome://settings",
        "chrome-extension://abc",
        "data:text/html,<h1>hi</h1>",
        "ftp://example.com/file",
        "javascript:alert(1)",
        "ws://example.com",
        "wss://example.com",
        "blob:https://example.com/uuid",
    ]:
        assert (
            _refused_navigation_url({"method": "Page.navigate", "params": {"url": url}}) == url
        ), f"should refuse {url}"


@pytest.mark.unit
def test_refused_navigation_url_case_insensitive_scheme() -> None:
    assert (
        _refused_navigation_url(
            {"method": "Page.navigate", "params": {"url": "FILE:///etc/passwd"}}
        )
        == "FILE:///etc/passwd"
    )
    assert (
        _refused_navigation_url({"method": "Page.navigate", "params": {"url": "CHROME://settings"}})
        == "CHROME://settings"
    )


@pytest.mark.unit
def test_refused_navigation_url_allows_http_https_case_insensitive() -> None:
    for url in [
        "http://example.com",
        "https://example.com",
        "HTTP://EXAMPLE.COM",
        "HTTPS://EXAMPLE.COM",
    ]:
        assert _refused_navigation_url({"method": "Page.navigate", "params": {"url": url}}) is None


@pytest.mark.unit
def test_refused_navigation_url_target_create_target_same_rules() -> None:
    assert (
        _refused_navigation_url({"method": "Target.createTarget", "params": {"url": "file:///x"}})
        == "file:///x"
    )
    assert (
        _refused_navigation_url(
            {"method": "Target.createTarget", "params": {"url": "https://example.com"}}
        )
        is None
    )


@pytest.mark.unit
def test_refused_navigation_url_missing_url_key_returns_none() -> None:
    assert _refused_navigation_url({"method": "Page.navigate", "params": {}}) is None


# ---------------------------------------------------------------------------
# _refusal_reason
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "method",
    [
        "Browser.setDownloadBehavior",
        "Page.setDownloadBehavior",
        "Target.createBrowserContext",
        "Target.disposeBrowserContext",
    ],
)
def test_refusal_reason_refused_methods(method: str) -> None:
    reason = _refusal_reason({"id": 1, "method": method, "params": {}})
    assert reason is not None
    assert method in reason
    assert "refused" in reason.lower()


@pytest.mark.unit
def test_refusal_reason_includes_download_message() -> None:
    reason = _refusal_reason({"id": 1, "method": "Browser.setDownloadBehavior", "params": {}})
    assert reason is not None and "downloads are denied" in reason


@pytest.mark.unit
def test_refusal_reason_includes_context_lifecycle_message() -> None:
    reason = _refusal_reason({"id": 1, "method": "Target.createBrowserContext", "params": {}})
    assert reason is not None and "context lifecycle" in reason


@pytest.mark.unit
def test_refusal_reason_navigation_refused() -> None:
    msg = {"id": 1, "method": "Page.navigate", "params": {"url": "file:///etc/passwd"}}
    reason = _refusal_reason(msg)
    assert reason is not None
    assert "file:///etc/passwd" in reason
    assert "only http and https" in reason


@pytest.mark.unit
def test_refusal_reason_navigation_allowed_returns_none() -> None:
    assert (
        _refusal_reason(
            {"id": 1, "method": "Page.navigate", "params": {"url": "https://example.com"}}
        )
        is None
    )
    assert (
        _refusal_reason(
            {"id": 1, "method": "Target.createTarget", "params": {"url": "https://example.com"}}
        )
        is None
    )


@pytest.mark.unit
def test_refusal_reason_ordinary_method_returns_none() -> None:
    assert _refusal_reason({"id": 1, "method": "Page.enable", "params": {}}) is None
    assert _refusal_reason({"id": 1, "method": "Runtime.evaluate", "params": {}}) is None
    assert _refusal_reason({"id": 1, "method": "Target.getTargets", "params": {}}) is None


@pytest.mark.unit
def test_refusal_reason_refused_methods_take_precedence_over_navigation() -> None:
    # even if url is http, the method itself is refused
    assert (
        _refusal_reason(
            {
                "id": 1,
                "method": "Target.createBrowserContext",
                "params": {"url": "https://example.com"},
            }
        )
        is not None
    )


@pytest.mark.unit
def test_refusal_reason_missing_method_returns_none_or_navigation_check() -> None:
    # missing method => not in refused set, and not in navigation set
    assert _refusal_reason({"id": 1, "params": {"url": "file:///etc/passwd"}}) is None


# ---------------------------------------------------------------------------
# _refusal_reply
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_refusal_reply_with_int_id() -> None:
    raw = _refusal_reply(42, "nope")
    obj = json.loads(raw)
    assert obj["id"] == 42
    assert obj["error"]["code"] == _CDP_REFUSED_CODE
    assert obj["error"]["message"] == "nope"


@pytest.mark.unit
def test_refusal_reply_with_none_id() -> None:
    raw = _refusal_reply(None, "reason")
    obj = json.loads(raw)
    assert obj["id"] is None
    assert obj["error"]["code"] == -32000


@pytest.mark.unit
def test_refusal_reply_code_is_minus_32000() -> None:
    raw = _refusal_reply(1, "x")
    assert json.loads(raw)["error"]["code"] == -32000


# ---------------------------------------------------------------------------
# _event_context_id
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_event_context_id_returns_context_when_present() -> None:
    assert _event_context_id({"targetInfo": {"browserContextId": "ctx-1"}}) == "ctx-1"


@pytest.mark.unit
def test_event_context_id_returns_none_when_missing() -> None:
    assert _event_context_id({}) is None
    assert _event_context_id({"targetInfo": {}}) is None
    assert _event_context_id({"targetInfo": None}) is None
    assert _event_context_id({"targetInfo": "not-a-dict"}) is None


@pytest.mark.unit
def test_event_context_id_returns_none_when_not_str() -> None:
    assert _event_context_id({"targetInfo": {"browserContextId": 123}}) is None
    assert _event_context_id({"targetInfo": {"browserContextId": None}}) is None


# ---------------------------------------------------------------------------
# _rewrite_upstream
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_rewrite_upstream_tracks_gettargets_id() -> None:
    ids: set[int] = set()
    msg = {"id": 7, "method": "Target.getTargets", "params": {}}
    assert _rewrite_upstream(msg, "ctx1", ids) == msg
    assert 7 in ids


@pytest.mark.unit
def test_rewrite_upstream_gettargets_non_int_id_not_tracked() -> None:
    ids: set[int] = set()
    msg = {"id": "not-int", "method": "Target.getTargets", "params": {}}
    _rewrite_upstream(msg, "ctx1", ids)
    assert ids == set()
    msg2 = {"method": "Target.getTargets", "params": {}}
    _rewrite_upstream(msg2, "ctx1", ids)
    assert ids == set()


@pytest.mark.unit
def test_rewrite_upstream_pins_create_target_no_params() -> None:
    ids: set[int] = set()
    msg: dict = {"id": 1, "method": "Target.createTarget"}
    assert _rewrite_upstream(msg, "my-ctx", ids)["params"]["browserContextId"] == "my-ctx"


@pytest.mark.unit
def test_rewrite_upstream_pins_create_target_overwrites_existing() -> None:
    ids: set[int] = set()
    msg: dict = {
        "id": 1,
        "method": "Target.createTarget",
        "params": {"url": "https://example.com", "browserContextId": "other-ctx"},
    }
    out = _rewrite_upstream(msg, "my-ctx", ids)
    assert out["params"]["browserContextId"] == "my-ctx"
    assert out["params"]["url"] == "https://example.com"


@pytest.mark.unit
def test_rewrite_upstream_create_target_with_existing_params_preserved() -> None:
    ids: set[int] = set()
    msg: dict = {"id": 2, "method": "Target.createTarget", "params": {"url": "https://example.com"}}
    out = _rewrite_upstream(msg, "ctx-123", ids)
    assert out["params"]["browserContextId"] == "ctx-123"
    assert out["params"]["url"] == "https://example.com"


@pytest.mark.unit
def test_rewrite_upstream_create_target_non_dict_params_not_pinned() -> None:
    ids: set[int] = set()
    msg: dict = {"id": 1, "method": "Target.createTarget", "params": "not-a-dict"}
    # params not a dict => left as-is, not pinned
    assert _rewrite_upstream(msg, "ctx-1", ids)["params"] == "not-a-dict"


@pytest.mark.unit
def test_rewrite_upstream_other_methods_pass_through() -> None:
    ids: set[int] = set()
    msg: dict = {"id": 5, "method": "Page.navigate", "params": {"url": "https://example.com"}}
    assert _rewrite_upstream(msg, "ctx1", ids) == msg
    assert ids == set()


@pytest.mark.unit
def test_rewrite_upstream_multiple_gettargets_ids() -> None:
    ids: set[int] = set()
    _rewrite_upstream({"id": 1, "method": "Target.getTargets", "params": {}}, "ctx1", ids)
    _rewrite_upstream({"id": 2, "method": "Target.getTargets", "params": {}}, "ctx1", ids)
    assert ids == {1, 2}


# ---------------------------------------------------------------------------
# _filter_downstream
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_filter_downstream_trims_gettargets_to_context() -> None:
    ids = {42}
    frame = {
        "id": 42,
        "result": {
            "targetInfos": [
                {"targetId": "a", "browserContextId": "ctx1"},
                {"targetId": "b", "browserContextId": "other"},
                {"targetId": "c", "browserContextId": "ctx1"},
                {"targetId": "d"},  # no context id -> not this context, trimmed out
            ]
        },
    }
    out = _filter_downstream(frame, "ctx1", ids)
    assert out is not None
    assert [ti["targetId"] for ti in out["result"]["targetInfos"]] == ["a", "c"]
    assert 42 not in ids  # discarded after handling


@pytest.mark.unit
def test_filter_downstream_gettargets_no_targetinfos_returns_frame() -> None:
    ids = {10}
    frame = {"id": 10, "result": {"something": "else"}}
    assert _filter_downstream(frame, "ctx1", ids) == frame
    assert 10 not in ids


@pytest.mark.unit
def test_filter_downstream_gettargets_result_not_dict_returns_frame() -> None:
    ids = {11}
    frame = {"id": 11, "result": "not-a-dict"}
    assert _filter_downstream(frame, "ctx1", ids) == frame
    assert 11 not in ids


@pytest.mark.unit
def test_filter_downstream_gettargets_targetinfos_not_list_returns_frame() -> None:
    ids = {12}
    frame = {"id": 12, "result": {"targetInfos": "not-a-list"}}
    assert _filter_downstream(frame, "ctx1", ids) == frame


@pytest.mark.unit
def test_filter_downstream_untracked_id_passes_through() -> None:
    """Only a getTargets THIS proxy sent is trimmed; any other reply is passed on verbatim."""
    ids: set[int] = set()
    frame = {
        "id": 99,
        "result": {
            "targetInfos": [
                {"targetId": "a", "browserContextId": "other"},
                {"targetId": "b", "browserContextId": "ctx1"},
            ]
        },
    }
    untouched = copy.deepcopy(frame)

    out = _filter_downstream(frame, "ctx1", ids)

    # The frame is filtered in place, so the copy taken before the call is the
    # only thing that can tell a pass-through from a trim.
    assert out == untouched


@pytest.mark.unit
def test_filter_downstream_drops_cross_context_events() -> None:
    ids: set[int] = set()
    for method in ["Target.attachedToTarget", "Target.targetCreated", "Target.targetInfoChanged"]:
        frame = {"method": method, "params": {"targetInfo": {"browserContextId": "other-ctx"}}}
        assert _filter_downstream(frame, "my-ctx", ids) is None, method


@pytest.mark.unit
def test_filter_downstream_keeps_same_context_events() -> None:
    ids: set[int] = set()
    for method in ["Target.attachedToTarget", "Target.targetCreated", "Target.targetInfoChanged"]:
        frame = {"method": method, "params": {"targetInfo": {"browserContextId": "my-ctx"}}}
        assert _filter_downstream(frame, "my-ctx", ids) == frame


@pytest.mark.unit
def test_filter_downstream_keeps_event_with_no_context_id() -> None:
    ids: set[int] = set()
    for method in ["Target.attachedToTarget", "Target.targetCreated", "Target.targetInfoChanged"]:
        frame = {"method": method, "params": {"targetInfo": {}}}
        assert _filter_downstream(frame, "my-ctx", ids) == frame
        frame2 = {"method": method, "params": {}}
        assert _filter_downstream(frame2, "my-ctx", ids) == frame2


@pytest.mark.unit
def test_filter_downstream_non_scoped_event_always_passes() -> None:
    ids: set[int] = set()
    frame = {"method": "Page.frameNavigated", "params": {"targetInfo": {"browserContextId": "o"}}}
    assert _filter_downstream(frame, "my-ctx", ids) == frame
    frame2 = {"method": "Runtime.consoleAPICalled", "params": {}}
    assert _filter_downstream(frame2, "my-ctx", ids) == frame2


@pytest.mark.unit
def test_filter_downstream_non_gettargets_response_passes() -> None:
    ids: set[int] = set()
    frame = {"id": 5, "result": {"frameId": "frame1"}}
    assert _filter_downstream(frame, "ctx1", ids) == frame


@pytest.mark.unit
def test_filter_downstream_scoped_event_missing_params_key_passes_through() -> None:
    """A scoped event with no params key at all, not merely an empty dict, must still resolve to raw without raising: _event_context_id gets a dict default for a missing key, never None."""
    ids: set[int] = set()
    for method in ["Target.attachedToTarget", "Target.targetCreated", "Target.targetInfoChanged"]:
        frame = {"method": method}
        assert _filter_downstream(frame, "my-ctx", ids) == frame, method


@pytest.mark.unit
def test_filter_downstream_empty_targetinfos_kept_empty() -> None:
    ids = {1}
    out = _filter_downstream({"id": 1, "result": {"targetInfos": []}}, "ctx1", ids)
    assert out is not None
    assert out["result"]["targetInfos"] == []


# ---------------------------------------------------------------------------
# run_cdp_proxy — driven against the shared FakeMux, never a websocket of its own
# ---------------------------------------------------------------------------


_WSDisconnect = type("WebSocketDisconnect", (Exception,), {})

# A script entry is either a frame the client sends or the engine speaking at
# that point, so a test emits where it means to rather than at subscribe time.
_ClientStep = str | Callable[[], None]


def _client_ws(*script: _ClientStep) -> MagicMock:
    """Build a client socket that plays the script, then disconnects the way a real peer does."""
    remaining = list(script)

    async def _receive() -> str:
        while remaining:
            step = remaining.pop(0)
            if callable(step):
                step()
                continue
            return step
        raise _WSDisconnect()

    client_ws = MagicMock()
    client_ws.receive_text = AsyncMock(side_effect=_receive)
    client_ws.send_text = AsyncMock()
    return client_ws


def _sent(client_ws: MagicMock) -> list[dict[str, Any]]:
    return [json.loads(call[0][0]) for call in client_ws.send_text.call_args_list]


async def _never_speaks() -> str:
    """Stand in for a connected client that is simply sitting idle."""
    await asyncio.Event().wait()
    raise AssertionError("an idle client never sends")


@pytest.mark.unit
async def test_run_cdp_proxy_refuses_and_forwards() -> None:
    """The upstream refusal and the downstream context filter, over one mux."""
    host = MagicMock()
    mux = FakeMux()
    client_ws = _client_ws(
        json.dumps(
            {"id": 1, "method": "Browser.setDownloadBehavior", "params": {"behavior": "allow"}}
        ),
        json.dumps({"id": 2, "method": "Page.navigate", "params": {"url": "https://example.com"}}),
        lambda: mux.emit(
            {
                "method": "Target.targetCreated",
                "params": {"targetInfo": {"browserContextId": "other", "targetId": "x"}},
            },
            {
                "method": "Target.targetCreated",
                "params": {"targetInfo": {"browserContextId": "ctx-1", "targetId": "y"}},
            },
        ),
    )

    await proxy_mod.run_cdp_proxy(host, make_session(mux=mux, context_id="ctx-1"), client_ws)

    sent = _sent(client_ws)
    assert sent[0]["id"] == 1
    assert sent[0]["error"]["code"] == _CDP_REFUSED_CODE
    # Only Page.navigate reaches the engine; the refused command never does.
    assert [frame["method"] for frame in mux.forwarded] == ["Page.navigate"]
    # The foreign-context event is dropped, this session's own event is delivered.
    delivered = [frame for frame in sent if frame.get("method") == "Target.targetCreated"]
    assert [frame["params"]["targetInfo"]["targetId"] for frame in delivered] == ["y"]


@pytest.mark.unit
async def test_run_cdp_proxy_forwards_the_clients_own_frame_through_the_mux() -> None:
    """The mux owns id rewriting, so the proxy hands it the client's frame as-is."""
    mux = FakeMux()
    client_ws = _client_ws(json.dumps({"id": 77, "method": "Page.enable", "params": {}}))

    await proxy_mod.run_cdp_proxy(MagicMock(), make_session(mux=mux), client_ws)

    assert mux.forwarded == [{"id": 77, "method": "Page.enable", "params": {}}]


@pytest.mark.unit
async def test_run_cdp_proxy_delivers_a_reply_from_the_sink_to_the_client() -> None:
    mux = FakeMux()
    client_ws = _client_ws(lambda: mux.emit({"id": 77, "result": {"frameId": "f1"}}))

    await proxy_mod.run_cdp_proxy(MagicMock(), make_session(mux=mux), client_ws)

    assert _sent(client_ws) == [{"id": 77, "result": {"frameId": "f1"}}]


@pytest.mark.unit
async def test_run_cdp_proxy_returns_when_the_engine_drops_the_connection() -> None:
    """An idle client has nothing to fail on, so the mux closing is what ends the proxy."""
    mux = FakeMux()
    client_ws = MagicMock()
    client_ws.send_text = AsyncMock()
    client_ws.receive_text = _never_speaks

    proxying = asyncio.create_task(
        proxy_mod.run_cdp_proxy(MagicMock(), make_session(mux=mux), client_ws)
    )
    mux.close_signal.set()  # the engine hung up

    await asyncio.wait_for(proxying, timeout=1.0)


@pytest.mark.unit
async def test_run_cdp_proxy_claims_no_cdp_session_on_the_mux() -> None:
    """The agent's client takes the open stream, so it must claim nothing when it subscribes."""
    mux = FakeMux()
    claimed: list[list[str | None]] = []
    client_ws = _client_ws(lambda: claimed.append(mux.owned_sessions))

    await proxy_mod.run_cdp_proxy(MagicMock(), make_session(mux=mux), client_ws)

    assert claimed == [[None]]


@pytest.mark.unit
async def test_run_cdp_proxy_never_sees_a_frame_another_subscriber_claimed() -> None:
    """Its screencast frames are screenshots nobody asked for, its load event is not this navigation."""
    host = MagicMock()
    mux = FakeMux()
    live_view: list[dict[str, Any]] = []

    def live_view_attaches_and_the_engine_speaks() -> None:
        mux.subscribe(live_view.append, owns_session="live-sess")
        mux.emit(
            {
                "method": "Page.screencastFrame",
                "sessionId": "live-sess",
                "params": {"data": "base64-jpeg"},
            },
            {"method": "Page.loadEventFired", "sessionId": "live-sess", "params": {}},
            {"method": "Page.loadEventFired", "params": {}},
        )

    client_ws = _client_ws(live_view_attaches_and_the_engine_speaks)

    await proxy_mod.run_cdp_proxy(host, make_session(mux=mux, session_id="sess-live"), client_ws)

    assert [frame["method"] for frame in live_view] == [
        "Page.screencastFrame",
        "Page.loadEventFired",
    ]
    assert _sent(client_ws) == [{"method": "Page.loadEventFired", "params": {}}]
    # Only the agent's own load event closes a navigation; the live view's does not.
    assert host.note_navigation_finished.call_args_list == [call("sess-live")]


@pytest.mark.unit
async def test_run_cdp_proxy_sends_the_clients_frame_on_the_sessions_own_connection() -> None:
    """One engine connection per session: the proxy rides session.mux and dials nothing."""
    mux = FakeMux()
    client_ws = _client_ws(json.dumps({"id": 1, "method": "Page.enable", "params": {}}))

    await proxy_mod.run_cdp_proxy(MagicMock(), make_session(mux=mux), client_ws)

    assert mux.forwarded == [{"id": 1, "method": "Page.enable", "params": {}}]
    assert mux.started == 0  # the host opened it; the proxy borrows it


@pytest.mark.unit
async def test_run_cdp_proxy_unsubscribes_its_sink_on_exit() -> None:
    mux = FakeMux()

    await proxy_mod.run_cdp_proxy(MagicMock(), make_session(mux=mux), _client_ws())

    assert mux.sinks == []


@pytest.mark.unit
async def test_run_cdp_proxy_unsubscribes_its_sink_when_a_pump_raises() -> None:
    """A real error must still leave no sink behind on the session's shared mux."""
    mux = FakeMux()
    client_ws = MagicMock()
    client_ws.receive_text = AsyncMock(side_effect=ValueError("boom"))
    client_ws.send_text = AsyncMock()

    with pytest.raises(ValueError, match="boom"):
        await proxy_mod.run_cdp_proxy(MagicMock(), make_session(mux=mux), client_ws)

    assert mux.sinks == []


@pytest.mark.unit
async def test_run_cdp_proxy_navigation_refusal_sends_error() -> None:
    mux = FakeMux()
    client_ws = _client_ws(
        json.dumps({"id": 5, "method": "Page.navigate", "params": {"url": "file:///etc/passwd"}})
    )

    await proxy_mod.run_cdp_proxy(MagicMock(), make_session(mux=mux), client_ws)

    reply = _sent(client_ws)[0]
    assert reply["id"] == 5
    assert "only http and https" in reply["error"]["message"]
    assert mux.forwarded == []


@pytest.mark.unit
async def test_run_cdp_proxy_rewrites_create_target_and_filters_gettargets() -> None:
    host = MagicMock()
    mux = FakeMux()
    client_ws = _client_ws(
        json.dumps({"id": 10, "method": "Target.getTargets", "params": {}}),
        # The reply can only be trimmed once the request has registered its id.
        lambda: mux.emit(
            {
                "id": 10,
                "result": {
                    "targetInfos": [
                        {"targetId": "t-ctx", "browserContextId": "ctx-1"},
                        {"targetId": "t-other", "browserContextId": "other"},
                    ]
                },
            }
        ),
        json.dumps(
            {
                "id": 11,
                "method": "Target.createTarget",
                "params": {"url": "https://example.com", "browserContextId": "other"},
            }
        ),
    )

    await proxy_mod.run_cdp_proxy(host, make_session(mux=mux, context_id="ctx-1"), client_ws)

    created = [f for f in mux.forwarded if f["method"] == "Target.createTarget"]
    assert [f["params"]["browserContextId"] for f in created] == ["ctx-1"]
    trimmed = [f for f in _sent(client_ws) if f.get("id") == 10]
    assert len(trimmed) == 1
    assert [ti["targetId"] for ti in trimmed[0]["result"]["targetInfos"]] == ["t-ctx"]


@pytest.mark.unit
async def test_run_cdp_proxy_touches_session_id_on_both_directions() -> None:
    """host.touch must key off the session id — not the context id or anything."""
    host = MagicMock()
    mux = FakeMux()
    client_ws = _client_ws(
        json.dumps({"id": 1, "method": "Page.enable", "params": {}}),
        lambda: mux.emit({"method": "Page.frameNavigated", "params": {}}),
    )

    await proxy_mod.run_cdp_proxy(
        host, make_session(mux=mux, session_id="sess-XYZ", context_id="ctx-ABC"), client_ws
    )

    # One touch for the client->engine frame, one for the engine->client frame,
    # both keyed by the session id (never the context id).
    assert host.touch.call_args_list == [call("sess-XYZ"), call("sess-XYZ")]


@pytest.mark.unit
async def test_run_cdp_proxy_rewrites_upstream_using_context_id_not_session_id() -> None:
    """Upstream rewriting pins the target to session.context_id, never the session id."""
    mux = FakeMux()
    client_ws = _client_ws(
        json.dumps({"id": 1, "method": "Target.createTarget", "params": {"url": "https://x.com"}})
    )

    await proxy_mod.run_cdp_proxy(
        MagicMock(),
        make_session(mux=mux, session_id="sess-XYZ", context_id="ctx-ABC"),
        client_ws,
    )

    assert [f["params"]["browserContextId"] for f in mux.forwarded] == ["ctx-ABC"]


@pytest.mark.unit
async def test_run_cdp_proxy_logs_refusal_with_reason_and_session_id() -> None:
    """The refusal warning carries this session's id and the actual reason."""
    mux = FakeMux()
    client_ws = _client_ws(
        json.dumps(
            {"id": 1, "method": "Browser.setDownloadBehavior", "params": {"behavior": "allow"}}
        )
    )

    with patch.object(proxy_mod.log, "warning") as mock_warning:
        await proxy_mod.run_cdp_proxy(
            MagicMock(), make_session(mux=mux, session_id="sess-warn"), client_ws
        )

    mock_warning.assert_called_once_with(
        f"{LogTag.BROWSER} browser cdp command refused",
        error_type="RefusedCdpCommand",
        browser={
            "session_id": "sess-warn",
            "reason": "Browser.setDownloadBehavior refused: downloads are denied for this session",
        },
    )


@pytest.mark.unit
async def test_run_cdp_proxy_logs_closure_with_session_id_and_operation() -> None:
    """The closing log line names this session and the cdp_proxy_closed operation."""
    with (
        patch.object(proxy_mod.log, "set") as mock_set,
        patch.object(proxy_mod.log, "info") as mock_info,
    ):
        await proxy_mod.run_cdp_proxy(
            MagicMock(),
            make_session(mux=FakeMux(), session_id="sess-closed"),
            _client_ws(),
        )

    mock_set.assert_called_once_with(
        browser={"session_id": "sess-closed", "operation": "cdp_proxy_closed"}
    )
    mock_info.assert_called_once()
    assert "cdp proxy closed" in mock_info.call_args[0][0]


@pytest.mark.unit
async def test_run_cdp_proxy_never_forwards_dropped_downstream_frame() -> None:
    """A frame _filter_downstream drops must never reach the client."""
    mux = FakeMux()
    client_ws = _client_ws(
        lambda: mux.emit(
            {
                "method": "Target.attachedToTarget",
                "params": {"targetInfo": {"browserContextId": "other-ctx"}},
            }
        )
    )

    await proxy_mod.run_cdp_proxy(MagicMock(), make_session(mux=mux, context_id="ctx-1"), client_ws)

    client_ws.send_text.assert_not_called()


@pytest.mark.unit
async def test_run_cdp_proxy_handles_non_int_refusal_id() -> None:
    mux = FakeMux()
    client_ws = _client_ws(
        json.dumps({"method": "Browser.setDownloadBehavior", "params": {"behavior": "allow"}})
    )

    await proxy_mod.run_cdp_proxy(MagicMock(), make_session(mux=mux), client_ws)

    reply = _sent(client_ws)[0]
    assert reply["id"] is None
    assert reply["error"]["code"] == _CDP_REFUSED_CODE


@pytest.mark.unit
async def test_run_cdp_proxy_records_navigation_and_page_metrics_for_this_session() -> None:
    """Navigation start, page creation and finish are each recorded once, for this session."""
    host = MagicMock()
    mux = FakeMux()
    client_ws = _client_ws(
        # Two inert commands: neither may be counted as a navigation or a page.
        json.dumps({"id": 1, "method": "Page.enable", "params": {}}),
        json.dumps({"id": 4, "method": "Runtime.evaluate", "params": {}}),
        json.dumps({"id": 2, "method": "Page.navigate", "params": {"url": "https://a.test"}}),
        json.dumps({"id": 3, "method": "Target.createTarget", "params": {"url": "https://b.test"}}),
        lambda: mux.emit(
            {"method": "Page.frameNavigated", "params": {}},
            # A page's own data naming the event must not close a navigation.
            {"id": 9, "result": {"value": "Page.loadEventFired"}},
            {"method": "Page.loadEventFired", "params": {"timestamp": 1.0}},
        ),
    )

    await proxy_mod.run_cdp_proxy(host, make_session(mux=mux, session_id="sess-metrics"), client_ws)

    assert host.note_navigation_started.call_args_list == [call("sess-metrics")]
    assert host.note_page_created.call_args_list == [call("sess-metrics")]
    assert host.note_navigation_finished.call_args_list == [call("sess-metrics")]


@pytest.mark.unit
async def test_run_cdp_proxy_routes_a_forwarded_frames_reply_to_the_client_that_sent_it() -> None:
    """Two clients share one engine connection, so a reply reaches its sender's socket alone."""
    mux = FakeMux()
    bystander_ws = MagicMock()
    bystander_ws.send_text = AsyncMock()
    bystander_ws.receive_text = _never_speaks
    bystander = asyncio.create_task(
        proxy_mod.run_cdp_proxy(
            MagicMock(), make_session(mux=mux, session_id="sess-other"), bystander_ws
        )
    )
    await asyncio.sleep(0)  # let the other proxy subscribe before ours forwards anything

    def the_engine_answers() -> None:
        # The sink the forward named is what decides whose client gets this reply.
        mux.reply_sinks[-1]({"id": 77, "result": {"frameId": "f1"}})

    client_ws = _client_ws(
        json.dumps({"id": 77, "method": "Page.navigate", "params": {"url": "https://a.test"}}),
        the_engine_answers,
    )

    await proxy_mod.run_cdp_proxy(
        MagicMock(), make_session(mux=mux, session_id="sess-mine"), client_ws
    )

    assert _sent(client_ws) == [{"id": 77, "result": {"frameId": "f1"}}]
    bystander_ws.send_text.assert_not_called()
    mux.close_signal.set()
    await asyncio.wait_for(bystander, timeout=1.0)
