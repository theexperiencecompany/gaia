"""Tests for app.services.browser.host_client — async httpx wrapper over browser host."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services.browser import host_client
from app.services.browser.exceptions import (
    BrowserConcurrencyLimit,
    BrowserSessionGone,
    BrowserUnavailableError,
)

# Every call names the host it talks to: the primary engine or the fallback.
_HOST = "http://browser-host:8930"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_response(
    *,
    status_code: int = 200,
    json_data: dict | None = None,
    raise_for_status_side_effect=None,
    url: str = "http://browser-host:8930/sessions",
) -> MagicMock:
    """Bare mock that quacks like httpx.Response for the paths we exercise."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json = MagicMock(return_value=json_data or {})
    resp.request = MagicMock()
    resp.request.url = url
    if raise_for_status_side_effect is not None:
        resp.raise_for_status = MagicMock(side_effect=raise_for_status_side_effect)
    else:
        resp.raise_for_status = MagicMock(return_value=None)
    return resp


def _http_status_error(
    status_code: int = 500, url: str = "http://browser-host:8930/sessions"
) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", url)
    response = httpx.Response(status_code=status_code, request=request)
    return httpx.HTTPStatusError(f"server error {status_code}", request=request, response=response)


def _make_client_mock(response: MagicMock) -> MagicMock:
    """Return an async-context-manager mock whose HTTP verb returns *response*."""
    client = AsyncMock()
    client.post = AsyncMock(return_value=response)
    client.get = AsyncMock(return_value=response)
    client.delete = AsyncMock(return_value=response)
    # async with support
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=client)
    mock_cm.__aexit__ = AsyncMock(return_value=False)
    # host_client does `async with httpx.AsyncClient(...) as client:`, so the
    # patched class must be a mock that returns mock_cm (with __aenter__) when
    # called; this returns the inner client + cm, and the test wires the class.
    return client, mock_cm


def _patch_async_client(monkeypatch_or_patch, response: MagicMock, *, verb: str = "post"):
    """Patch host_client.httpx.AsyncClient so an async with block calling the given verb returns response."""
    inner = AsyncMock()
    getattr(inner, verb).return_value = response
    # For other verbs we still provide a default
    for v in ("post", "get", "delete"):
        if v != verb:
            getattr(inner, v).return_value = response
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=inner)
    cm.__aexit__ = AsyncMock(return_value=False)
    cls_mock = MagicMock(return_value=cm)
    # httpx.AsyncClient is used as `async with httpx.AsyncClient(...) as c:`, so
    # AsyncClient(...) must return an object with __aenter__; cls_mock does that
    # via return_value=cm, making it work as the context-manager factory.
    return inner, cm, cls_mock


# ---------------------------------------------------------------------------
# _host_headers
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHostHeaders:
    def test_no_key_returns_empty(self, monkeypatch):
        monkeypatch.setattr(host_client.settings, "BROWSER_HOST_KEY", None)
        assert host_client._host_headers() == {}

    def test_with_key_returns_header(self, monkeypatch):
        monkeypatch.setattr(host_client.settings, "BROWSER_HOST_KEY", "secret123")
        assert host_client._host_headers() == {"X-Host-Key": "secret123"}


# ---------------------------------------------------------------------------
# _raise_for_status
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRaiseForStatus:
    def test_http_error_wrapped_as_unavailable(self):
        err = _http_status_error(500)
        resp = _mock_response(
            status_code=500,
            raise_for_status_side_effect=err,
            url="http://browser-host:8930/sessions/abc",
        )
        with pytest.raises(BrowserUnavailableError, match="500") as exc_info:
            host_client._raise_for_status(resp)
        assert exc_info.value.__cause__ is err


# ---------------------------------------------------------------------------
# create_session
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCreateSession:
    async def test_success(self, monkeypatch):
        monkeypatch.setattr(host_client.settings, "BROWSER_HOST_KEY", "k1")
        resp = _mock_response(
            status_code=200,
            json_data={
                "session_id": "s1",
                "cdp_ws": "ws://cdp",
                "live_ws": "ws://live",
                "context_id": "ctx1",
            },
        )
        inner, cm, cls_mock = _patch_async_client(None, resp, verb="post")
        with patch.object(host_client.httpx, "AsyncClient", cls_mock):
            result = await host_client.create_session(storage_state=None, host_url=_HOST)
        assert result.session_id == "s1"
        assert result.cdp_ws == "ws://cdp"
        assert result.live_ws == "ws://live"
        assert result.context_id == "ctx1"
        # Verify AsyncClient was constructed with expected args
        assert cls_mock.call_args[1]["base_url"] == _HOST
        assert cls_mock.call_args[1]["timeout"] == host_client._CREATE_TIMEOUT_SECONDS
        assert cls_mock.call_args[1]["headers"] == {"X-Host-Key": "k1"}
        inner.post.assert_awaited_once_with("/sessions", json={"storage_state": None})

    async def test_success_with_storage_state(self, monkeypatch):
        monkeypatch.setattr(host_client.settings, "BROWSER_HOST_KEY", None)
        state = {"cookies": [], "origins": []}
        resp = _mock_response(
            status_code=200,
            json_data={
                "session_id": "s1",
                "cdp_ws": "ws://cdp",
                "live_ws": "ws://live",
                "context_id": "ctx1",
            },
        )
        inner, cm, cls_mock = _patch_async_client(None, resp, verb="post")
        with patch.object(host_client.httpx, "AsyncClient", cls_mock):
            await host_client.create_session(storage_state=state, host_url=_HOST)
        inner.post.assert_awaited_once_with("/sessions", json={"storage_state": state})
        # No header when key is None
        assert cls_mock.call_args[1]["headers"] == {}

    async def test_at_capacity_raises_concurrency_limit(self, monkeypatch):
        monkeypatch.setattr(host_client.settings, "BROWSER_HOST_KEY", None)
        resp = _mock_response(status_code=429)
        inner, cm, cls_mock = _patch_async_client(None, resp, verb="post")
        with patch.object(host_client.httpx, "AsyncClient", cls_mock):
            with pytest.raises(BrowserConcurrencyLimit) as exc_info:
                await host_client.create_session(storage_state=None, host_url=_HOST)
        # Shown to the user as the reason the browser could not start.
        assert str(exc_info.value) == "The browser host is at capacity; try again shortly."

    async def test_http_error_connect_raises_unavailable(self, monkeypatch):
        monkeypatch.setattr(host_client.settings, "BROWSER_HOST_KEY", None)
        inner = AsyncMock()
        inner.post = AsyncMock(side_effect=httpx.ConnectError("refused"))
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=inner)
        cm.__aexit__ = AsyncMock(return_value=False)
        cls_mock = MagicMock(return_value=cm)
        with patch.object(host_client.httpx, "AsyncClient", cls_mock):
            with pytest.raises(BrowserUnavailableError, match="Could not reach") as exc_info:
                await host_client.create_session(storage_state=None, host_url=_HOST)
        # The message names the host that failed, so a fallback outage reads as one.
        assert _HOST in str(exc_info.value)


# ---------------------------------------------------------------------------
# delete_session
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDeleteSession:
    async def test_success_returns_storage_state(self, monkeypatch):
        monkeypatch.setattr(host_client.settings, "BROWSER_HOST_KEY", "k2")
        stored = {"cookies": [{"name": "a", "value": "b"}]}
        resp = _mock_response(status_code=200, json_data={"storage_state": stored})
        inner, cm, cls_mock = _patch_async_client(None, resp, verb="delete")
        with patch.object(host_client.httpx, "AsyncClient", cls_mock):
            result = await host_client.delete_session("sess-123", _HOST)
        assert result == stored
        assert cls_mock.call_args[1]["base_url"] == _HOST
        assert cls_mock.call_args[1]["timeout"] == host_client._DEFAULT_TIMEOUT_SECONDS
        assert cls_mock.call_args[1]["headers"] == {"X-Host-Key": "k2"}
        inner.delete.assert_awaited_once_with("/sessions/sess-123")


# ---------------------------------------------------------------------------
# get_storage_state
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetStorageState:
    async def test_success_reads_the_live_state_without_deleting(self, monkeypatch):
        monkeypatch.setattr(host_client.settings, "BROWSER_HOST_KEY", "k4")
        stored = {"cookies": [{"name": "session", "value": "signed-in"}], "origins": []}
        resp = _mock_response(status_code=200, json_data={"storage_state": stored})
        inner, cm, cls_mock = _patch_async_client(None, resp, verb="get")
        with patch.object(host_client.httpx, "AsyncClient", cls_mock):
            result = await host_client.get_storage_state("sess-123", _HOST)
        assert result == stored
        assert cls_mock.call_args[1]["base_url"] == _HOST
        assert cls_mock.call_args[1]["timeout"] == host_client._DEFAULT_TIMEOUT_SECONDS
        assert cls_mock.call_args[1]["headers"] == {"X-Host-Key": "k4"}
        inner.get.assert_awaited_once_with("/sessions/sess-123/storage-state")
        inner.delete.assert_not_awaited()

    async def test_a_gone_session_raises_session_gone(self):
        url = "http://browser-host:8930/sessions/sess-123/storage-state"
        resp = _mock_response(
            status_code=404, raise_for_status_side_effect=_http_status_error(404), url=url
        )
        inner, cm, cls_mock = _patch_async_client(None, resp, verb="get")
        with patch.object(host_client.httpx, "AsyncClient", cls_mock):
            with pytest.raises(BrowserSessionGone) as exc_info:
                await host_client.get_storage_state("sess-123", _HOST)
        assert str(exc_info.value) == f"Browser host returned 404 for {url}"


# ---------------------------------------------------------------------------
# touch_session
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTouchSession:
    async def test_success_posts_to_the_touch_endpoint(self, monkeypatch):
        monkeypatch.setattr(host_client.settings, "BROWSER_HOST_KEY", "k3")
        resp = _mock_response(status_code=200, json_data={})
        inner, cm, cls_mock = _patch_async_client(None, resp, verb="post")
        with patch.object(host_client.httpx, "AsyncClient", cls_mock):
            await host_client.touch_session("sess-123", _HOST)
        # Without the configured base_url the relative touch path would never
        # reach the host, so the keepalive would silently stop working.
        assert cls_mock.call_args[1]["base_url"] == _HOST
        assert cls_mock.call_args[1]["timeout"] == host_client._DEFAULT_TIMEOUT_SECONDS
        assert cls_mock.call_args[1]["headers"] == {"X-Host-Key": "k3"}
        inner.post.assert_awaited_once_with("/sessions/sess-123/touch")


# ---------------------------------------------------------------------------
# get_session
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetSession:
    async def test_success_with_all_fields(self, monkeypatch):
        monkeypatch.setattr(host_client.settings, "BROWSER_HOST_KEY", None)
        resp = _mock_response(
            status_code=200,
            json_data={
                "session_id": "s1",
                "live": True,
                "last_activity_at": 1234567890.0,
                "url": "https://example.com",
                "title": "Example",
            },
        )
        inner, cm, cls_mock = _patch_async_client(None, resp, verb="get")
        with patch.object(host_client.httpx, "AsyncClient", cls_mock):
            result = await host_client.get_session("s1", _HOST)
        assert result.session_id == "s1"
        assert result.live is True
        assert result.last_activity_at == 1234567890.0
        assert result.url == "https://example.com"
        assert result.title == "Example"
        assert cls_mock.call_args[1]["base_url"] == _HOST
        assert cls_mock.call_args[1]["timeout"] == host_client._DEFAULT_TIMEOUT_SECONDS
        inner.get.assert_awaited_once_with("/sessions/s1")

    async def test_success_with_null_url_title(self, monkeypatch):
        monkeypatch.setattr(host_client.settings, "BROWSER_HOST_KEY", None)
        resp = _mock_response(
            status_code=200,
            json_data={
                "session_id": "s2",
                "live": False,
                "last_activity_at": 0.0,
                "url": None,
                "title": None,
            },
        )
        inner, cm, cls_mock = _patch_async_client(None, resp, verb="get")
        with patch.object(host_client.httpx, "AsyncClient", cls_mock):
            result = await host_client.get_session("s2", _HOST)
        assert result.url is None
        assert result.title is None
        assert result.live is False

    async def test_host_key_forwarded(self, monkeypatch):
        monkeypatch.setattr(host_client.settings, "BROWSER_HOST_KEY", "my-secret")
        resp = _mock_response(
            status_code=200,
            json_data={
                "session_id": "s1",
                "live": True,
                "last_activity_at": 0.0,
                "url": None,
                "title": None,
            },
        )
        inner, cm, cls_mock = _patch_async_client(None, resp, verb="get")
        with patch.object(host_client.httpx, "AsyncClient", cls_mock):
            await host_client.get_session("s1", _HOST)
        assert cls_mock.call_args[1]["headers"] == {"X-Host-Key": "my-secret"}
        assert cls_mock.call_args[1]["base_url"] == _HOST


@pytest.mark.unit
@pytest.mark.parametrize(
    "call",
    [
        lambda: host_client.delete_session("sess-1", _HOST),
        lambda: host_client.get_storage_state("sess-1", _HOST),
        lambda: host_client.touch_session("sess-1", _HOST),
        lambda: host_client.get_session("sess-1", _HOST),
    ],
    ids=["delete_session", "get_storage_state", "touch_session", "get_session"],
)
async def test_an_unreachable_host_is_reported_as_unavailable_naming_the_host(call):
    inner = AsyncMock()
    for verb in ("post", "get", "delete"):
        setattr(inner, verb, AsyncMock(side_effect=httpx.ConnectError("refused")))
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=inner)
    cm.__aexit__ = AsyncMock(return_value=False)
    with patch.object(host_client.httpx, "AsyncClient", MagicMock(return_value=cm)):
        with pytest.raises(BrowserUnavailableError) as exc_info:
            await call()

    # Names the host, so an outage of the fallback engine reads as that outage.
    assert str(exc_info.value) == f"Could not reach the browser host at {_HOST}: refused"
