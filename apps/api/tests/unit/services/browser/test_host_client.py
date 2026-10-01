"""The API's client for the browser host, against an in-process httpx transport.

Every call sends the host key and its own deadline, and every failure lands as
one of three typed errors the browser tool turns into a clean message.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
import json
from typing import Any

import httpx
import pytest

from app.services.browser import host_client
from app.services.browser.exceptions import (
    BrowserConcurrencyLimit,
    BrowserSessionGone,
    BrowserUnavailableError,
)

pytestmark = pytest.mark.unit

_HOST = "http://browser-host:8930"
_STATE = {"cookies": [{"name": "a", "value": "1", "domain": "x.com"}], "origins": []}


class _Host:
    """Answers each request from a route table and records what it was sent."""

    def __init__(self, routes: dict[str, httpx.Response]) -> None:
        self.routes = routes
        self.requests: list[httpx.Request] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.routes[f"{request.method} {request.url.path}"]


@pytest.fixture
def host(monkeypatch: pytest.MonkeyPatch) -> Callable[[dict[str, httpx.Response]], _Host]:
    real = httpx.AsyncClient

    def _install(routes: dict[str, httpx.Response]) -> _Host:
        fake = _Host(routes)
        monkeypatch.setattr(
            host_client.httpx,
            "AsyncClient",
            lambda **kw: real(transport=httpx.MockTransport(fake.handle), **kw),
        )
        return fake

    monkeypatch.setattr(host_client.settings, "BROWSER_HOST_KEY", "the-key")
    return _install


async def test_a_session_is_created_with_its_seed_the_key_and_a_deadline(host: Any) -> None:
    fake = host(
        {
            "POST /sessions": httpx.Response(
                200, json={"session_id": "s1", "cdp_ws": "ws://c", "live_ws": "ws://l"}
            )
        }
    )

    created = await host_client.create_session(_STATE, _HOST)

    assert created == host_client.HostSession(session_id="s1", cdp_ws="ws://c", live_ws="ws://l")
    sent = fake.requests[0]
    assert json.loads(sent.content) == {"storage_state": _STATE}
    assert sent.headers["X-Host-Key"] == "the-key"
    assert sent.headers["X-Host-Deadline"] == "30.0"


async def test_a_host_at_capacity_is_a_concurrency_limit(host: Any) -> None:
    host({"POST /sessions": httpx.Response(429, json={"detail": "at_capacity"})})

    with pytest.raises(BrowserConcurrencyLimit):
        await host_client.create_session(None, _HOST)


async def test_a_dispose_and_a_live_read_return_the_state(host: Any) -> None:
    fake = host(
        {
            "DELETE /sessions/s1": httpx.Response(200, json={"storage_state": _STATE}),
            "GET /sessions/s1/storage-state": httpx.Response(200, json={"storage_state": _STATE}),
        }
    )

    assert await host_client.delete_session("s1", _HOST) == _STATE
    assert await host_client.get_storage_state("s1", _HOST) == _STATE
    assert [r.headers["X-Host-Deadline"] for r in fake.requests] == ["15.0", "15.0"]


async def test_renewing_a_lease_posts_to_the_sessions_lease(host: Any) -> None:
    fake = host(
        {
            "POST /sessions/s1/lease": httpx.Response(
                200, json={"session_id": "s1", "lease_seconds": 90}
            )
        }
    )

    await host_client.renew_session_lease("s1", _HOST)

    assert [str(r.url) for r in fake.requests] == [f"{_HOST}/sessions/s1/lease"]


async def test_session_info_is_read_inside_the_callers_own_deadline(host: Any) -> None:
    fake = host(
        {
            "GET /sessions/s1": httpx.Response(
                200,
                json={
                    "session_id": "s1",
                    "live": True,
                    "url": "https://x.com",
                    "title": None,
                    "metrics": {},
                },
            )
        }
    )

    info = await host_client.get_session("s1", _HOST, timeout=5.0)

    assert info == host_client.HostSessionInfo(session_id="s1", live=True, url="https://x.com")
    assert fake.requests[0].headers["X-Host-Deadline"] == "5.0"


async def test_without_a_key_none_is_sent(host: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = host({"POST /sessions/s1/lease": httpx.Response(200, json={})})
    monkeypatch.setattr(host_client.settings, "BROWSER_HOST_KEY", None)

    await host_client.renew_session_lease("s1", _HOST)

    assert "X-Host-Key" not in fake.requests[0].headers


_CALLS: list[Callable[[], Awaitable[object]]] = [
    lambda: host_client.delete_session("s1", _HOST),
    lambda: host_client.get_storage_state("s1", _HOST),
    lambda: host_client.renew_session_lease("s1", _HOST),
    lambda: host_client.get_session("s1", _HOST),
]
_ROUTES = [
    "DELETE /sessions/s1",
    "GET /sessions/s1/storage-state",
    "POST /sessions/s1/lease",
    "GET /sessions/s1",
]


@pytest.mark.parametrize(("call", "route"), list(zip(_CALLS, _ROUTES, strict=True)))
async def test_a_gone_session_is_session_gone_and_anything_else_unavailable(
    host: Any, call: Callable[[], Awaitable[object]], route: str
) -> None:
    host({route: httpx.Response(404, json={"detail": "session not found"})})
    with pytest.raises(BrowserSessionGone, match="404"):
        await call()

    host({route: httpx.Response(503, json={"detail": "browser engine unresponsive"})})
    with pytest.raises(BrowserUnavailableError, match="503") as unavailable:
        await call()
    assert not isinstance(unavailable.value, BrowserSessionGone)


async def test_an_unreachable_host_is_unavailable_naming_the_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    real = httpx.AsyncClient
    monkeypatch.setattr(
        host_client.httpx,
        "AsyncClient",
        lambda **kw: real(transport=httpx.MockTransport(_refuse), **kw),
    )

    with pytest.raises(
        BrowserUnavailableError, match=f"Could not reach the browser host at {_HOST}"
    ):
        await host_client.create_session(None, _HOST)
