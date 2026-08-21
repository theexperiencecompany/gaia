"""Coverage for proxy.py helpers not hit by test_proxy.py."""

from __future__ import annotations

import json

import pytest

from app.browser_host.proxy import (
    _CDP_REFUSED_CODE,
    _event_context_id,
    _filter_downstream,
    _refusal_reason,
    _refusal_reply,
    _refused_navigation_url,
    _rewrite_upstream,
)

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
    raw = _rewrite_upstream(msg, "ctx1", ids)
    assert 7 in ids
    assert json.loads(raw) == msg


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
    raw = _rewrite_upstream(msg, "my-ctx", ids)
    obj = json.loads(raw)
    assert obj["params"]["browserContextId"] == "my-ctx"


@pytest.mark.unit
def test_rewrite_upstream_pins_create_target_overwrites_existing() -> None:
    ids: set[int] = set()
    msg: dict = {
        "id": 1,
        "method": "Target.createTarget",
        "params": {"url": "https://example.com", "browserContextId": "other-ctx"},
    }
    raw = _rewrite_upstream(msg, "my-ctx", ids)
    obj = json.loads(raw)
    assert obj["params"]["browserContextId"] == "my-ctx"
    assert obj["params"]["url"] == "https://example.com"


@pytest.mark.unit
def test_rewrite_upstream_create_target_with_existing_params_preserved() -> None:
    ids: set[int] = set()
    msg: dict = {"id": 2, "method": "Target.createTarget", "params": {"url": "https://example.com"}}
    raw = _rewrite_upstream(msg, "ctx-123", ids)
    obj = json.loads(raw)
    assert obj["params"]["browserContextId"] == "ctx-123"
    assert obj["params"]["url"] == "https://example.com"


@pytest.mark.unit
def test_rewrite_upstream_create_target_non_dict_params_not_pinned() -> None:
    ids: set[int] = set()
    msg: dict = {"id": 1, "method": "Target.createTarget", "params": "not-a-dict"}
    raw = _rewrite_upstream(msg, "ctx-1", ids)
    obj = json.loads(raw)
    # params not a dict => left as-is, not pinned
    assert obj["params"] == "not-a-dict"


@pytest.mark.unit
def test_rewrite_upstream_other_methods_pass_through() -> None:
    ids: set[int] = set()
    msg: dict = {"id": 5, "method": "Page.navigate", "params": {"url": "https://example.com"}}
    raw = _rewrite_upstream(msg, "ctx1", ids)
    assert json.loads(raw) == msg
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
    raw = json.dumps(
        {
            "id": 42,
            "result": {
                "targetInfos": [
                    {"targetId": "a", "browserContextId": "ctx1"},
                    {"targetId": "b", "browserContextId": "other"},
                    {"targetId": "c", "browserContextId": "ctx1"},
                    {
                        "targetId": "d"
                    },  # no context id -> filtered out because None != ctx1? Actually kept only == ctx1
                ]
            },
        }
    )
    out = _filter_downstream(raw, "ctx1", ids)
    assert out is not None
    obj = json.loads(out)
    assert len(obj["result"]["targetInfos"]) == 2
    assert all(ti["browserContextId"] == "ctx1" for ti in obj["result"]["targetInfos"])
    assert 42 not in ids  # discarded after handling


@pytest.mark.unit
def test_filter_downstream_gettargets_no_targetinfos_returns_raw() -> None:
    ids = {10}
    raw = json.dumps({"id": 10, "result": {"something": "else"}})
    out = _filter_downstream(raw, "ctx1", ids)
    assert out == raw
    assert 10 not in ids


@pytest.mark.unit
def test_filter_downstream_gettargets_result_not_dict_returns_raw() -> None:
    ids = {11}
    raw = json.dumps({"id": 11, "result": "not-a-dict"})
    out = _filter_downstream(raw, "ctx1", ids)
    assert out == raw
    assert 11 not in ids


@pytest.mark.unit
def test_filter_downstream_gettargets_targetinfos_not_list_returns_raw() -> None:
    ids = {12}
    raw = json.dumps({"id": 12, "result": {"targetInfos": "not-a-list"}})
    out = _filter_downstream(raw, "ctx1", ids)
    assert out == raw


@pytest.mark.unit
def test_filter_downstream_untracked_id_passes_through() -> None:
    ids: set[int] = set()
    raw = json.dumps(
        {"id": 99, "result": {"targetInfos": [{"targetId": "a", "browserContextId": "other"}]}}
    )
    out = _filter_downstream(raw, "ctx1", ids)
    assert out == raw  # not tracked, so not filtered


@pytest.mark.unit
def test_filter_downstream_drops_cross_context_events() -> None:
    ids: set[int] = set()
    for method in ["Target.attachedToTarget", "Target.targetCreated", "Target.targetInfoChanged"]:
        raw = json.dumps(
            {"method": method, "params": {"targetInfo": {"browserContextId": "other-ctx"}}}
        )
        assert _filter_downstream(raw, "my-ctx", ids) is None, method


@pytest.mark.unit
def test_filter_downstream_keeps_same_context_events() -> None:
    ids: set[int] = set()
    for method in ["Target.attachedToTarget", "Target.targetCreated", "Target.targetInfoChanged"]:
        raw = json.dumps(
            {"method": method, "params": {"targetInfo": {"browserContextId": "my-ctx"}}}
        )
        assert _filter_downstream(raw, "my-ctx", ids) == raw


@pytest.mark.unit
def test_filter_downstream_keeps_event_with_no_context_id() -> None:
    ids: set[int] = set()
    for method in ["Target.attachedToTarget", "Target.targetCreated", "Target.targetInfoChanged"]:
        raw = json.dumps({"method": method, "params": {"targetInfo": {}}})
        assert _filter_downstream(raw, "my-ctx", ids) == raw
        raw2 = json.dumps({"method": method, "params": {}})
        assert _filter_downstream(raw2, "my-ctx", ids) == raw2


@pytest.mark.unit
def test_filter_downstream_non_scoped_event_always_passes() -> None:
    ids: set[int] = set()
    raw = json.dumps(
        {"method": "Page.frameNavigated", "params": {"targetInfo": {"browserContextId": "other"}}}
    )
    assert _filter_downstream(raw, "my-ctx", ids) == raw
    raw2 = json.dumps({"method": "Runtime.consoleAPICalled", "params": {}})
    assert _filter_downstream(raw2, "my-ctx", ids) == raw2


@pytest.mark.unit
def test_filter_downstream_non_gettargets_response_passes() -> None:
    ids: set[int] = set()
    raw = json.dumps({"id": 5, "result": {"frameId": "frame1"}})
    assert _filter_downstream(raw, "ctx1", ids) == raw


@pytest.mark.unit
def test_filter_downstream_bytes_decoded_by_caller_not_here() -> None:
    # _filter_downstream takes str, bytes handling is in run_cdp_proxy
    ids: set[int] = set()
    raw = json.dumps(
        {"method": "Target.targetCreated", "params": {"targetInfo": {"browserContextId": "other"}}}
    )
    assert _filter_downstream(raw, "ctx1", ids) is None


@pytest.mark.unit
def test_filter_downstream_empty_targetinfos_kept_empty() -> None:
    ids = {1}
    raw = json.dumps({"id": 1, "result": {"targetInfos": []}})
    out = _filter_downstream(raw, "ctx1", ids)
    assert out is not None
    assert json.loads(out)["result"]["targetInfos"] == []


# ---------------------------------------------------------------------------
# run_cdp_proxy (covers lines 174-212 with mocked websockets)
# ---------------------------------------------------------------------------


class _WSDisconnect(Exception):
    pass


_WSDisconnect = type("WebSocketDisconnect", (Exception,), {})


@pytest.mark.unit
async def test_run_cdp_proxy_refuses_and_forwards() -> None:
    """Exercises client_to_chromium refusal and chromium_to_client filtering."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock, patch

    from app.browser_host import proxy as proxy_mod
    from app.browser_host.chromium import HostSession

    host = MagicMock()
    host.root_ws_url = "ws://fake"
    host.touch = MagicMock()
    session = HostSession(
        session_id="sess-1", context_id="ctx-1", target_id="t1", created_at=0, last_activity_at=0
    )

    client_ws = MagicMock()
    client_ws.receive_text = AsyncMock(
        side_effect=[
            json.dumps(
                {"id": 1, "method": "Browser.setDownloadBehavior", "params": {"behavior": "allow"}}
            ),
            json.dumps(
                {"id": 2, "method": "Page.navigate", "params": {"url": "https://example.com"}}
            ),
            _WSDisconnect(),
        ]
    )
    client_ws.send_text = AsyncMock()

    chromium_messages = [
        json.dumps(
            {
                "method": "Target.targetCreated",
                "params": {"targetInfo": {"browserContextId": "other", "targetId": "x"}},
            }
        ),
        json.dumps(
            {
                "method": "Target.targetCreated",
                "params": {"targetInfo": {"browserContextId": "ctx-1", "targetId": "y"}},
            }
        ),
    ]

    class FakeChromiumWS:
        def __init__(self):
            self.sent: list[str] = []
            self._iter = iter(chromium_messages)

        async def send(self, data: str) -> None:
            self.sent.append(data)

        def __aiter__(self):
            return self

        async def __anext__(self):
            try:
                return next(self._iter)
            except StopIteration:
                await asyncio.sleep(0.2)
                raise StopAsyncIteration

    fake_chromium = FakeChromiumWS()
    mock_ws_ctx = MagicMock()
    mock_ws_ctx.__aenter__ = AsyncMock(return_value=fake_chromium)
    mock_ws_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch.object(proxy_mod.websockets, "connect", return_value=mock_ws_ctx):
        await proxy_mod.run_cdp_proxy(host, session, client_ws)

    # refusal reply for Browser.setDownloadBehavior (id 1) should have been sent
    assert client_ws.send_text.call_count >= 1
    first_reply = json.loads(client_ws.send_text.call_args_list[0][0][0])
    assert first_reply["id"] == 1
    assert first_reply["error"]["code"] == -32000
    # Only Page.navigate should have been forwarded to chromium (refused one not forwarded)
    assert len(fake_chromium.sent) == 1
    forwarded = json.loads(fake_chromium.sent[0])
    assert forwarded["method"] == "Page.navigate"
    # Chromium downstream: other-context event dropped, same-context forwarded
    # so at least 2 sends to client: refusal + one chromium forward
    assert client_ws.send_text.call_count >= 2
    # find the chromium-forwarded message (method Target.targetCreated with ctx-1)
    forwarded_down = [
        json.loads(c[0][0])
        for c in client_ws.send_text.call_args_list
        if "method" in json.loads(c[0][0])
    ]
    assert any(
        m.get("params", {}).get("targetInfo", {}).get("browserContextId") == "ctx-1"
        for m in forwarded_down
    )


@pytest.mark.unit
async def test_run_cdp_proxy_handles_bytes_downstream() -> None:
    from unittest.mock import AsyncMock, MagicMock, patch

    from app.browser_host import proxy as proxy_mod
    from app.browser_host.chromium import HostSession

    host = MagicMock()
    host.root_ws_url = "ws://fake"
    host.touch = MagicMock()
    session = HostSession(
        session_id="s1", context_id="ctx-1", target_id="t1", created_at=0, last_activity_at=0
    )
    client_ws = MagicMock()
    client_ws.receive_text = AsyncMock(side_effect=[_WSDisconnect()])
    client_ws.send_text = AsyncMock()

    raw_bytes = json.dumps({"method": "Page.frameNavigated", "params": {}}).encode()
    text = raw_bytes.decode() if isinstance(raw_bytes, bytes) else raw_bytes
    assert isinstance(text, str)
    from app.browser_host.proxy import _filter_downstream

    out = _filter_downstream(text, "ctx-1", set())
    assert out == text

    class FakeChromiumBytes:
        async def send(self, data):
            pass

        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

    fake = FakeChromiumBytes()
    mock_ws_ctx = MagicMock()
    mock_ws_ctx.__aenter__ = AsyncMock(return_value=fake)
    mock_ws_ctx.__aexit__ = AsyncMock(return_value=False)
    with patch.object(proxy_mod.websockets, "connect", return_value=mock_ws_ctx):
        await proxy_mod.run_cdp_proxy(host, session, client_ws)
    host.touch.assert_not_called()


@pytest.mark.unit
async def test_run_cdp_proxy_navigation_refusal_sends_error() -> None:
    import asyncio
    from unittest.mock import AsyncMock, MagicMock, patch

    from app.browser_host import proxy as proxy_mod
    from app.browser_host.chromium import HostSession

    host = MagicMock()
    host.root_ws_url = "ws://fake"
    host.touch = MagicMock()
    session = HostSession(
        session_id="s1", context_id="ctx-1", target_id="t1", created_at=0, last_activity_at=0
    )
    client_ws = MagicMock()
    client_ws.receive_text = AsyncMock(
        side_effect=[
            json.dumps(
                {"id": 5, "method": "Page.navigate", "params": {"url": "file:///etc/passwd"}}
            ),
            _WSDisconnect(),
        ]
    )
    client_ws.send_text = AsyncMock()

    class FakeWS:
        def __init__(self):
            self.sent: list[str] = []

        async def send(self, data):
            self.sent.append(data)

        def __aiter__(self):
            return self

        async def __anext__(self):
            await asyncio.sleep(0.2)
            raise StopAsyncIteration

    fake = FakeWS()
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=fake)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    with patch.object(proxy_mod.websockets, "connect", return_value=mock_ctx):
        await proxy_mod.run_cdp_proxy(host, session, client_ws)
    assert client_ws.send_text.call_count >= 1
    reply = json.loads(client_ws.send_text.call_args_list[0][0][0])
    assert reply["id"] == 5
    assert "only http and https" in reply["error"]["message"]
    assert len(fake.sent) == 0


@pytest.mark.unit
async def test_run_cdp_proxy_rewrites_create_target_and_filters_gettargets() -> None:
    import asyncio
    from unittest.mock import AsyncMock, MagicMock, patch

    from app.browser_host import proxy as proxy_mod
    from app.browser_host.chromium import HostSession

    host = MagicMock()
    host.root_ws_url = "ws://fake"
    host.touch = MagicMock()
    session = HostSession(
        session_id="s1", context_id="ctx-1", target_id="t1", created_at=0, last_activity_at=0
    )
    client_ws = MagicMock()
    client_ws.receive_text = AsyncMock(
        side_effect=[
            json.dumps({"id": 10, "method": "Target.getTargets", "params": {}}),
            json.dumps(
                {
                    "id": 11,
                    "method": "Target.createTarget",
                    "params": {"url": "https://example.com", "browserContextId": "other"},
                }
            ),
            _WSDisconnect(),
        ]
    )
    client_ws.send_text = AsyncMock()

    class FakeChromium:
        def __init__(self):
            self.sent: list[str] = []

        async def send(self, data: str) -> None:
            self.sent.append(data)

        def __aiter__(self):
            return self

        async def __anext__(self):
            # After client sends getTargets, chromium replies with mixed targetInfos
            # Pump will have recorded getTargets id 10, so this response should be trimmed
            if not hasattr(self, "_sent_reply"):
                self._sent_reply = True
                return json.dumps(
                    {
                        "id": 10,
                        "result": {
                            "targetInfos": [
                                {"targetId": "t-ctx", "browserContextId": "ctx-1"},
                                {"targetId": "t-other", "browserContextId": "other"},
                            ]
                        },
                    }
                )
            await asyncio.sleep(0.2)
            raise StopAsyncIteration

    fake = FakeChromium()
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=fake)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    with patch.object(proxy_mod.websockets, "connect", return_value=mock_ctx):
        await proxy_mod.run_cdp_proxy(host, session, client_ws)
    # Check that createTarget was pinned to ctx-1
    create_sent = [
        json.loads(s) for s in fake.sent if json.loads(s).get("method") == "Target.createTarget"
    ]
    assert len(create_sent) == 1
    assert create_sent[0]["params"]["browserContextId"] == "ctx-1"
    # Check that getTargets response was trimmed to only ctx-1
    trimmed = [
        json.loads(c[0][0])
        for c in client_ws.send_text.call_args_list
        if json.loads(c[0][0]).get("id") == 10
    ]
    assert len(trimmed) == 1
    assert len(trimmed[0]["result"]["targetInfos"]) == 1
    assert trimmed[0]["result"]["targetInfos"][0]["browserContextId"] == "ctx-1"


@pytest.mark.unit
async def test_run_cdp_proxy_connects_with_root_url_and_unbounded_kwargs() -> None:
    """The proxy must dial Chromium's own root socket with no size/ping limits.

    ``max_size=None`` and ``ping_interval=None`` are load-bearing: a CDP frame
    (e.g. a full-page screenshot) can exceed websockets' 1MB default, and a
    ping interval would race the browser-use client's own idle handling.
    """
    from unittest.mock import AsyncMock, MagicMock, patch

    from app.browser_host import proxy as proxy_mod
    from app.browser_host.chromium import HostSession

    host = MagicMock()
    host.root_ws_url = "ws://chromium-root/devtools/browser/abc-123"
    host.touch = MagicMock()
    session = HostSession(
        session_id="s1", context_id="ctx-1", target_id="t1", created_at=0, last_activity_at=0
    )
    client_ws = MagicMock()
    client_ws.receive_text = AsyncMock(side_effect=[_WSDisconnect()])
    client_ws.send_text = AsyncMock()

    class FakeWS:
        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

    fake = FakeWS()
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=fake)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    with patch.object(proxy_mod.websockets, "connect", return_value=mock_ctx) as mock_connect:
        await proxy_mod.run_cdp_proxy(host, session, client_ws)

    mock_connect.assert_called_once_with(
        "ws://chromium-root/devtools/browser/abc-123", max_size=None, ping_interval=None
    )


@pytest.mark.unit
async def test_run_cdp_proxy_touches_session_id_on_both_directions() -> None:
    """``host.touch`` must key off the session id — not the context id or anything
    else — on every frame in either direction, so the idle reaper leaves an
    in-use session alone."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock, call, patch

    from app.browser_host import proxy as proxy_mod
    from app.browser_host.chromium import HostSession

    host = MagicMock()
    host.root_ws_url = "ws://fake"
    host.touch = MagicMock()
    session = HostSession(
        session_id="sess-XYZ",
        context_id="ctx-ABC",
        target_id="t1",
        created_at=0,
        last_activity_at=0,
    )
    client_ws = MagicMock()
    client_ws.receive_text = AsyncMock(
        side_effect=[
            json.dumps({"id": 1, "method": "Page.enable", "params": {}}),
            _WSDisconnect(),
        ]
    )
    client_ws.send_text = AsyncMock()

    class FakeChromium:
        def __init__(self) -> None:
            self._sent = False

        async def send(self, data: str) -> None:
            pass

        def __aiter__(self):
            return self

        async def __anext__(self):
            if not self._sent:
                self._sent = True
                return json.dumps({"method": "Page.frameNavigated", "params": {}})
            await asyncio.sleep(0.2)
            raise StopAsyncIteration

    fake = FakeChromium()
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=fake)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    with patch.object(proxy_mod.websockets, "connect", return_value=mock_ctx):
        await proxy_mod.run_cdp_proxy(host, session, client_ws)

    # One touch for the client->chromium frame, one for the chromium->client frame,
    # both keyed by the session id (never the context id).
    assert host.touch.call_args_list == [call("sess-XYZ"), call("sess-XYZ")]


@pytest.mark.unit
async def test_run_cdp_proxy_rewrites_upstream_using_context_id_not_session_id() -> None:
    """``_rewrite_upstream`` must be called with ``session.context_id`` — pinning a
    new target to the session id (or anything else) would create the tab in the
    wrong browser context."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock, patch

    from app.browser_host import proxy as proxy_mod
    from app.browser_host.chromium import HostSession

    host = MagicMock()
    host.root_ws_url = "ws://fake"
    host.touch = MagicMock()
    session = HostSession(
        session_id="sess-XYZ",
        context_id="ctx-ABC",
        target_id="t1",
        created_at=0,
        last_activity_at=0,
    )
    client_ws = MagicMock()
    client_ws.receive_text = AsyncMock(
        side_effect=[
            json.dumps(
                {"id": 1, "method": "Target.createTarget", "params": {"url": "https://x.com"}}
            ),
            _WSDisconnect(),
        ]
    )
    client_ws.send_text = AsyncMock()

    class FakeChromium:
        def __init__(self) -> None:
            self.sent: list[str] = []

        async def send(self, data: str) -> None:
            self.sent.append(data)

        def __aiter__(self):
            return self

        async def __anext__(self):
            await asyncio.sleep(0.2)
            raise StopAsyncIteration

    fake = FakeChromium()
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=fake)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    with patch.object(proxy_mod.websockets, "connect", return_value=mock_ctx):
        await proxy_mod.run_cdp_proxy(host, session, client_ws)

    assert len(fake.sent) == 1
    sent = json.loads(fake.sent[0])
    assert sent["params"]["browserContextId"] == "ctx-ABC"


@pytest.mark.unit
async def test_run_cdp_proxy_decodes_real_bytes_frame_from_chromium() -> None:
    """Chromium's websocket may yield ``bytes`` frames; the proxy must decode
    them before filtering/forwarding, not pass raw bytes through."""
    from unittest.mock import AsyncMock, MagicMock, patch

    from app.browser_host import proxy as proxy_mod
    from app.browser_host.chromium import HostSession

    host = MagicMock()
    host.root_ws_url = "ws://fake"
    host.touch = MagicMock()
    session = HostSession(
        session_id="s1", context_id="ctx-1", target_id="t1", created_at=0, last_activity_at=0
    )
    client_ws = MagicMock()
    client_ws.receive_text = AsyncMock(side_effect=[_WSDisconnect()])
    client_ws.send_text = AsyncMock()

    payload = {"method": "Page.frameNavigated", "params": {"frameId": "abc"}}

    class FakeChromiumBytes:
        def __init__(self) -> None:
            self._sent = False

        def __aiter__(self):
            return self

        async def __anext__(self):
            if not self._sent:
                self._sent = True
                return json.dumps(payload).encode()
            raise StopAsyncIteration

    fake = FakeChromiumBytes()
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=fake)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    with patch.object(proxy_mod.websockets, "connect", return_value=mock_ctx):
        await proxy_mod.run_cdp_proxy(host, session, client_ws)

    client_ws.send_text.assert_called_once()
    forwarded = json.loads(client_ws.send_text.call_args_list[0][0][0])
    assert forwarded == payload


@pytest.mark.unit
async def test_run_cdp_proxy_logs_refusal_with_reason_and_session_id() -> None:
    """The refusal warning must carry the actual session id and the actual
    refusal reason, not a generic message."""
    from unittest.mock import AsyncMock, MagicMock, patch

    from app.browser_host import proxy as proxy_mod
    from app.browser_host.chromium import HostSession

    host = MagicMock()
    host.root_ws_url = "ws://fake"
    host.touch = MagicMock()
    session = HostSession(
        session_id="sess-warn",
        context_id="ctx-1",
        target_id="t1",
        created_at=0,
        last_activity_at=0,
    )
    client_ws = MagicMock()
    client_ws.receive_text = AsyncMock(
        side_effect=[
            json.dumps(
                {"id": 1, "method": "Browser.setDownloadBehavior", "params": {"behavior": "allow"}}
            ),
            _WSDisconnect(),
        ]
    )
    client_ws.send_text = AsyncMock()

    class FakeWS:
        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

    fake = FakeWS()
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=fake)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    with (
        patch.object(proxy_mod.websockets, "connect", return_value=mock_ctx),
        patch.object(proxy_mod.log, "warning") as mock_warning,
    ):
        await proxy_mod.run_cdp_proxy(host, session, client_ws)

    mock_warning.assert_called_once()
    _, kwargs = mock_warning.call_args
    assert kwargs["error_type"] == "RefusedCdpCommand"
    assert kwargs["browser"]["session_id"] == "sess-warn"
    assert "downloads are denied" in kwargs["browser"]["reason"]


@pytest.mark.unit
async def test_run_cdp_proxy_logs_closure_with_session_id_and_operation() -> None:
    """The closing log line must name this session and the ``cdp_proxy_closed``
    operation, so a reader can tell which session's proxy exited from logs alone."""
    from unittest.mock import AsyncMock, MagicMock, patch

    from app.browser_host import proxy as proxy_mod
    from app.browser_host.chromium import HostSession

    host = MagicMock()
    host.root_ws_url = "ws://fake"
    host.touch = MagicMock()
    session = HostSession(
        session_id="sess-closed",
        context_id="ctx-1",
        target_id="t1",
        created_at=0,
        last_activity_at=0,
    )
    client_ws = MagicMock()
    client_ws.receive_text = AsyncMock(side_effect=[_WSDisconnect()])
    client_ws.send_text = AsyncMock()

    class FakeWS:
        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

    fake = FakeWS()
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=fake)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    with (
        patch.object(proxy_mod.websockets, "connect", return_value=mock_ctx),
        patch.object(proxy_mod.log, "set") as mock_set,
        patch.object(proxy_mod.log, "info") as mock_info,
    ):
        await proxy_mod.run_cdp_proxy(host, session, client_ws)

    mock_set.assert_called_once_with(
        browser={"session_id": "sess-closed", "operation": "cdp_proxy_closed"}
    )
    mock_info.assert_called_once()
    assert "cdp proxy closed" in mock_info.call_args[0][0]


@pytest.mark.unit
async def test_run_cdp_proxy_never_forwards_dropped_downstream_frame() -> None:
    """When every downstream frame is filtered out (``_filter_downstream`` returns
    ``None`` for all of them), the client socket must receive nothing at all."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock, patch

    from app.browser_host import proxy as proxy_mod
    from app.browser_host.chromium import HostSession

    host = MagicMock()
    host.root_ws_url = "ws://fake"
    host.touch = MagicMock()
    session = HostSession(
        session_id="s1", context_id="ctx-1", target_id="t1", created_at=0, last_activity_at=0
    )
    client_ws = MagicMock()
    client_ws.receive_text = AsyncMock(side_effect=[_WSDisconnect()])
    client_ws.send_text = AsyncMock()

    class FakeChromium:
        def __init__(self) -> None:
            self._sent = False

        def __aiter__(self):
            return self

        async def __anext__(self):
            if not self._sent:
                self._sent = True
                return json.dumps(
                    {
                        "method": "Target.attachedToTarget",
                        "params": {"targetInfo": {"browserContextId": "other-ctx"}},
                    }
                )
            await asyncio.sleep(0.2)
            raise StopAsyncIteration

    fake = FakeChromium()
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=fake)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    with patch.object(proxy_mod.websockets, "connect", return_value=mock_ctx):
        await proxy_mod.run_cdp_proxy(host, session, client_ws)

    client_ws.send_text.assert_not_called()


@pytest.mark.unit
async def test_run_cdp_proxy_handles_non_int_refusal_id() -> None:
    import asyncio
    from unittest.mock import AsyncMock, MagicMock, patch

    from app.browser_host import proxy as proxy_mod
    from app.browser_host.chromium import HostSession

    host = MagicMock()
    host.root_ws_url = "ws://fake"
    host.touch = MagicMock()
    session = HostSession(
        session_id="s1", context_id="ctx-1", target_id="t1", created_at=0, last_activity_at=0
    )
    client_ws = MagicMock()
    # no id field, refused method without int id should reply with null id
    client_ws.receive_text = AsyncMock(
        side_effect=[
            json.dumps({"method": "Browser.setDownloadBehavior", "params": {"behavior": "allow"}}),
            _WSDisconnect(),
        ]
    )
    client_ws.send_text = AsyncMock()

    class FakeWS:
        async def send(self, data):
            pass

        def __aiter__(self):
            return self

        async def __anext__(self):
            await asyncio.sleep(0.2)
            raise StopAsyncIteration

    fake = FakeWS()
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=fake)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    with patch.object(proxy_mod.websockets, "connect", return_value=mock_ctx):
        await proxy_mod.run_cdp_proxy(host, session, client_ws)
    assert client_ws.send_text.call_count == 1
    reply = json.loads(client_ws.send_text.call_args_list[0][0][0])
    assert reply["id"] is None
    assert reply["error"]["code"] == -32000
