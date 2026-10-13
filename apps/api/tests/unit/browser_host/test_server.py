"""The browser-host HTTP and websocket API, driven through the real FastAPI app.

The host behind it is a stub, so this proves the route contract a caller sees:
status codes, the one error table every route shares, the caller's deadline,
the websocket URLs it hands out and who may open them.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import WebSocketDisconnect
from fastapi.testclient import TestClient
import pytest

from app.browser_host import server as server_mod
from app.browser_host.cdp_mux import CdpCommandError, CdpConnectionClosed, CDPTimeoutError
from app.browser_host.host import AtCapacityError, EngineUnresponsiveError, SessionNotFoundError
from app.browser_host.wire import HealthResponse, SessionInfo
from app.constants.browser import BrowserEngine, HostAdmissionRefusal

pytestmark = pytest.mark.unit

_KEY = "k" * 32
_TOKEN = "session-token"
_INFO = SessionInfo(session_id="s1", live=True, url="https://example.com", title="Example")


class _HostStub:
    """A BrowserHost-shaped object whose I/O seams are mocks."""

    def __init__(self) -> None:
        # The engine the session really runs on, which the client learns from the host.
        self.create_context = AsyncMock(
            return_value=MagicMock(
                session_id="s1", token=_TOKEN, engine=MagicMock(kind=BrowserEngine.CHROMIUM)
            )
        )
        self.dispose_context = AsyncMock(return_value={"cookies": [], "origins": []})
        self.storage_state = AsyncMock(return_value={"cookies": [], "origins": []})
        self.session_info = AsyncMock(return_value=_INFO)
        self.healthz = AsyncMock(
            return_value=HealthResponse(ok=True, sessions=0, engine_up=True, cdp_responsive=True)
        )
        self.renew_lease = MagicMock()
        self.get = MagicMock(return_value=None)
        self.start = AsyncMock()
        self.stop = AsyncMock()
        self.failed = False


@pytest.fixture
def host(monkeypatch: pytest.MonkeyPatch) -> _HostStub:
    stub = _HostStub()
    monkeypatch.setattr(server_mod, "_host", stub)
    monkeypatch.setattr(server_mod.browser_host_settings, "BROWSER_HOST_URL", "http://bh:8930")
    monkeypatch.setattr(server_mod.browser_host_settings, "BROWSER_HOST_KEY", _KEY)
    monkeypatch.setattr(server_mod.browser_host_settings, "BROWSER_ENGINE", BrowserEngine.CHROMIUM)
    return stub


@pytest.fixture
def client(host: _HostStub) -> Iterator[TestClient]:
    with TestClient(server_mod.app, headers={"X-Host-Key": _KEY}) as c:
        yield c


def _event(loguru: MagicMock) -> dict[str, Any]:
    event: dict[str, Any] = loguru.bind.call_args.kwargs
    return event


# --- the REST surface ---


def test_a_created_session_comes_back_as_websocket_urls_carrying_its_own_token(
    client: TestClient, host: _HostStub
) -> None:
    resp = client.post("/sessions", json={"storage_state": {"cookies": [], "origins": []}})

    assert resp.status_code == 200
    assert resp.json() == {
        "session_id": "s1",
        "cdp_ws": f"ws://bh:8930/cdp/s1?token={_TOKEN}",
        "live_ws": f"ws://bh:8930/live/s1?token={_TOKEN}",
        "engine": "chromium",
    }
    assert host.create_context.await_args.args == ({"cookies": [], "origins": []},)


def test_a_create_refused_at_capacity_is_a_429_whose_event_names_the_gate(
    client: TestClient, host: _HostStub
) -> None:
    host.create_context.side_effect = AtCapacityError(
        HostAdmissionRefusal.MEMORY,
        used_mb=900.0,
        limit_mb=1000.0,
        projected_mb=1100.0,
        sessions=3,
        pending=1,
    )
    with patch("shared.py.wide_events._loguru") as loguru:
        resp = client.post("/sessions", json={"storage_state": None})

    event = _event(loguru)
    assert resp.status_code == 429
    assert resp.json() == {"detail": "at_capacity"}
    [warning] = event["warnings"]
    assert "at capacity" in warning["msg"]
    assert warning["browser"] == {
        "admission": "memory",
        "used_mb": 900.0,
        "limit_mb": 1000.0,
        "projected_mb": 1100.0,
        "sessions": 3,
        "pending": 1,
    }
    assert (event["reason"], event["engine"]) == ("at_capacity", "chromium")
    assert event["browser"] == {
        "operation": "create",
        "admission": "memory",
        "used_mb": 900.0,
        "limit_mb": 1000.0,
        "projected_mb": 1100.0,
        "sessions": 3,
        "pending": 1,
    }


def test_a_dispose_returns_the_state_to_save(client: TestClient, host: _HostStub) -> None:
    resp = client.delete("/sessions/abc")

    assert resp.json() == {"storage_state": {"cookies": [], "origins": []}}
    host.dispose_context.assert_awaited_once_with("abc")


def test_a_live_read_returns_the_state_and_info_returns_the_page(
    client: TestClient, host: _HostStub
) -> None:
    assert client.get("/sessions/abc/storage-state").json() == {
        "storage_state": {"cookies": [], "origins": []}
    }
    host.storage_state.assert_awaited_once_with("abc")
    info = client.get("/sessions/abc").json()
    assert info == _INFO.model_dump()
    host.session_info.assert_awaited_once_with("abc")


def test_a_renewed_lease_is_acknowledged(client: TestClient, host: _HostStub) -> None:
    with patch("shared.py.wide_events._loguru") as loguru:
        resp = client.post("/sessions/abc/lease")

    assert resp.status_code == 204
    host.renew_lease.assert_called_once_with("abc")
    assert _event(loguru)["browser"] == {"session_id": "abc", "operation": "lease"}


_NOT_FOUND = (404, "session_not_found", "session not found")
_UNRESPONSIVE = (503, "engine_unresponsive", "browser engine unresponsive")


@pytest.mark.parametrize(
    ("raised", "answer"),
    [
        (SessionNotFoundError("abc"), _NOT_FOUND),
        (CdpConnectionClosed("closed"), _NOT_FOUND),
        (EngineUnresponsiveError("abc"), _UNRESPONSIVE),
        (CDPTimeoutError("Storage.getCookies"), _UNRESPONSIVE),
        (
            CdpCommandError({"message": "x"}),
            (502, "engine_refused", "browser engine refused the request"),
        ),
    ],
)
@pytest.mark.parametrize(
    "route",
    [
        ("DELETE /sessions/abc", "dispose_context", "delete"),
        ("GET /sessions/abc/storage-state", "storage_state", "storage_state"),
        ("GET /sessions/abc", "session_info", "get"),
    ],
)
def test_every_route_answers_a_failure_from_one_table(
    client: TestClient,
    host: _HostStub,
    raised: Exception,
    answer: tuple[int, str, str],
    route: tuple[str, str, str],
) -> None:
    status, reason, detail = answer
    call, stub, operation = route
    getattr(host, stub).side_effect = raised
    method, path = call.split(" ")
    with patch("shared.py.wide_events._loguru") as loguru:
        resp = client.request(method, path)

    event = _event(loguru)
    assert resp.status_code == status
    assert resp.json() == {"detail": detail}
    assert event["reason"] == reason
    assert event["error_type"] == type(raised).__name__
    assert event["status_code"] == status
    assert event["browser"] == {"session_id": "abc", "operation": operation}


def test_a_lease_for_a_gone_session_is_a_404(client: TestClient, host: _HostStub) -> None:
    host.renew_lease.side_effect = SessionNotFoundError("gone")

    assert client.post("/sessions/gone/lease").status_code == 404


def test_healthz_is_503_when_the_engine_does_not_answer(
    client: TestClient, host: _HostStub, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorded = MagicMock()
    monkeypatch.setattr(server_mod.log, "set", recorded)
    assert client.get("/healthz").json() == {
        "ok": True,
        "sessions": 0,
        "engine_up": True,
        "cdp_responsive": True,
    }
    host.healthz.return_value = HealthResponse(
        ok=False, sessions=2, engine_up=True, cdp_responsive=False
    )
    assert client.get("/healthz").status_code == 503
    recorded.assert_called_with(browser={"operation": "healthz", "session_id": ""})


# --- the caller's deadline ---


def test_work_that_outlives_the_callers_deadline_is_given_up_with_a_504(
    client: TestClient, host: _HostStub
) -> None:
    async def _never_finishes(_session_id: str) -> None:
        await asyncio.Event().wait()

    host.dispose_context.side_effect = _never_finishes

    with patch("shared.py.wide_events._loguru") as loguru:
        resp = client.delete("/sessions/abc", headers={"X-Host-Deadline": "1.05"})

    assert resp.status_code == 504
    assert resp.json() == {"detail": "the caller's deadline passed"}
    assert _event(loguru)["reason"] == "deadline_exceeded"


def test_work_inside_the_deadline_answers_normally(client: TestClient, host: _HostStub) -> None:
    resp = client.delete("/sessions/abc", headers={"X-Host-Deadline": "15"})

    assert resp.status_code == 200


async def test_the_deadline_keeps_back_a_second_for_the_answer_to_travel() -> None:
    request = MagicMock(headers={"X-Host-Deadline": "1.0"})

    async def _one_yield() -> str:
        await asyncio.sleep(0)
        return "answered"

    with pytest.raises(server_mod._DeadlineExceeded) as late:
        await server_mod._within_deadline(request, _one_yield)
    assert late.value.args == ("deadline of 1.0s passed",)


async def test_a_timeout_of_the_works_own_is_not_the_callers_deadline() -> None:
    request = MagicMock(headers={"X-Host-Deadline": "15"})

    async def _own_timeout() -> None:
        raise TimeoutError

    with pytest.raises(TimeoutError):
        await server_mod._within_deadline(request, _own_timeout)


async def test_without_a_deadline_the_work_runs_unbounded() -> None:
    request = MagicMock(headers={})

    async def _answer() -> int:
        return 7

    assert await server_mod._within_deadline(request, _answer) == 7


# --- the host key ---


@pytest.mark.parametrize("sent", [None, "", "wrong"])
def test_a_rest_call_without_the_host_key_is_refused_and_leaves_a_trail(
    host: _HostStub, sent: str | None
) -> None:
    headers = {} if sent is None else {"X-Host-Key": sent}
    with TestClient(server_mod.app) as c, patch("shared.py.wide_events._loguru") as loguru:
        resp = c.delete("/sessions/s1", headers=headers)

    event = _event(loguru)
    assert resp.status_code == 401
    assert resp.json() == {"detail": "missing or invalid host key"}
    assert (event["task"], event["method"], event["path"]) == (
        "browser_host_request",
        "DELETE",
        "/sessions/s1",
    )
    assert event["reason"] == "invalid_host_key"
    host.dispose_context.assert_not_awaited()


@pytest.mark.parametrize(("env", "allowed"), [("development", True), ("production", False)])
def test_an_unkeyed_host_serves_only_outside_production(
    monkeypatch: pytest.MonkeyPatch, env: str, allowed: bool
) -> None:
    monkeypatch.setattr(server_mod.browser_host_settings, "BROWSER_HOST_KEY", None)
    monkeypatch.setattr(server_mod.browser_host_settings, "ENV", env)

    assert server_mod._key_valid(None) is allowed
    assert server_mod._key_valid("anything") is allowed


def test_a_configured_key_must_match_exactly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server_mod.browser_host_settings, "BROWSER_HOST_KEY", _KEY)

    assert server_mod._key_valid(_KEY) is True
    assert server_mod._key_valid(_KEY[:-1]) is False
    assert server_mod._key_valid(None) is False


# --- the websockets ---


def _live_session(host: _HostStub) -> MagicMock:
    session = MagicMock(token=_TOKEN)
    host.get.return_value = session
    return session


@pytest.mark.parametrize(
    ("path", "runner", "operation"),
    [("/cdp/s1", "run_cdp_proxy", "cdp_ws"), ("/live/s1", "run_live_view", "live_ws")],
)
def test_a_socket_with_its_sessions_token_is_bridged(
    client: TestClient, host: _HostStub, path: str, runner: str, operation: str
) -> None:
    session = _live_session(host)
    bridge = AsyncMock()

    with (
        patch.object(server_mod, runner, bridge),
        client.websocket_connect(f"{path}?token={_TOKEN}"),
    ):
        pass

    host_arg, session_arg, socket_arg = bridge.await_args.args
    assert (host_arg, session_arg) == (host, session)
    assert socket_arg.url.path == path
    host.get.assert_called_with("s1")


@pytest.mark.parametrize(("path", "operation"), [("/cdp/s1", "cdp_ws"), ("/live/s1", "live_ws")])
def test_a_socket_for_a_gone_session_closes_4404(
    client: TestClient, path: str, operation: str
) -> None:
    with patch("shared.py.wide_events._loguru") as loguru:
        with pytest.raises(WebSocketDisconnect) as closed:
            with client.websocket_connect(f"{path}?token={_TOKEN}"):
                pass

    event = _event(loguru)
    assert closed.value.code == 4404
    assert (event["task"], event["engine"]) == ("browser_host_ws", "chromium")
    assert event["browser"] == {"operation": operation, "session_id": "s1"}
    assert event["reason"] == "session_not_found"


@pytest.mark.parametrize("query", ["", "?token=", "?token=other", f"?hk={_KEY}"])
@pytest.mark.parametrize("path", ["/cdp/s1", "/live/s1"])
def test_a_socket_without_its_sessions_token_closes_4401_even_with_the_host_key(
    client: TestClient, host: _HostStub, path: str, query: str
) -> None:
    _live_session(host)
    with patch("shared.py.wide_events._loguru") as loguru:
        with pytest.raises(WebSocketDisconnect) as closed:
            with client.websocket_connect(f"{path}{query}"):
                pass

    assert closed.value.code == 4401
    assert _event(loguru)["reason"] == "invalid_session_token"


def test_a_socket_opened_from_a_web_page_is_refused_even_with_its_token(
    client: TestClient, host: _HostStub, monkeypatch: pytest.MonkeyPatch
) -> None:
    _live_session(host)
    warning = MagicMock()
    monkeypatch.setattr(server_mod.log, "warning", warning)
    with patch("shared.py.wide_events._loguru") as loguru:
        with pytest.raises(WebSocketDisconnect) as closed:
            with client.websocket_connect(
                f"/live/s1?token={_TOKEN}", headers={"origin": "https://evil.example"}
            ):
                pass

    assert closed.value.code == 4401
    assert _event(loguru)["reason"] == "invalid_session_token"
    assert "cross-origin" in warning.call_args.args[0]


@pytest.mark.parametrize(
    ("origin", "allowed"),
    [
        (None, True),
        ("http://localhost", True),
        ("http://127.0.0.1:3000/path", True),
        ("http://[::1]:8000", True),
        ("localhost:3000", True),
        ("https://evil.example", False),
        ("http://localhost.evil.example", False),
        ("null", False),
    ],
)
def test_only_a_loopback_origin_or_none_may_open_a_socket(
    origin: str | None, allowed: bool
) -> None:
    websocket = MagicMock(headers={} if origin is None else {"origin": origin})

    assert server_mod._ws_origin_allowed(websocket) is allowed


@pytest.mark.parametrize(
    ("base", "expected"),
    [
        ("http://bh:8930", "ws://bh:8930/cdp/s1?token=t"),
        ("https://bh/", "wss://bh/cdp/s1?token=t"),
        ("http://bh:8930/PREFIX", "ws://bh:8930/PREFIX/cdp/s1?token=t"),
        ("http://proxy/http://inner", "ws://proxy/http://inner/cdp/s1?token=t"),
        ("https://proxy/https://inner", "wss://proxy/https://inner/cdp/s1?token=t"),
    ],
)
def test_a_websocket_url_is_the_hosts_own_address_upgraded(
    monkeypatch: pytest.MonkeyPatch, base: str, expected: str
) -> None:
    monkeypatch.setattr(server_mod.browser_host_settings, "BROWSER_HOST_URL", base)

    assert server_mod._ws_url("/cdp/s1", "t") == expected


# --- giving up for a restart ---


def test_a_host_that_lost_its_engine_for_good_shuts_its_process_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kill = MagicMock()
    monkeypatch.setattr(server_mod.os, "kill", kill)

    server_mod._exit_for_restart()

    kill.assert_called_once_with(server_mod.os.getpid(), server_mod.signal.SIGTERM)


def test_whether_the_host_failed_is_the_hosts_own_word(host: _HostStub) -> None:
    assert server_mod.host_failed() is False
    host.failed = True
    assert server_mod.host_failed() is True
