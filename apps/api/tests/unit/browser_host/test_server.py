"""Tests for the browser-host HTTP API (session lifecycle + health).

Drives the real FastAPI app through TestClient with the ChromiumHost faked, so
the route contract — status codes, error bodies, derived websocket URLs — is
exercised exactly as a caller sees it. The 429-at-capacity and 503-on-degraded
paths are what Docker/user-visible behaviour depends on, so they are pinned
here.
"""

from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient
import pytest

from app.browser_host import server as server_mod
from app.browser_host.chromium import AtCapacityError, SessionNotFoundError

SESSION = MagicMock(session_id="s1", context_id="ctx-1")
INFO = {
    "session_id": "s1",
    "live": True,
    "last_activity_at": 1.0,
    "url": "https://example.com",
    "title": "Example",
}


class _HostStub:
    """A ChromiumHost-shaped object whose I/O seams are AsyncMocks."""

    def __init__(self) -> None:
        self.create_context = AsyncMock()
        self.dispose_context = AsyncMock()
        self.session_info = AsyncMock()
        self.healthz = AsyncMock()
        self.start = AsyncMock()
        self.stop = AsyncMock()
        self.get = MagicMock(return_value=None)


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch):
    host = _HostStub()
    monkeypatch.setattr(server_mod, "_host", host)
    monkeypatch.setattr(
        server_mod.settings, "BROWSER_HOST_URL", "http://browser-host:8930", raising=False
    )
    with TestClient(server_mod.app) as c:
        yield c, host


def test_create_session_returns_derived_ws_urls(client) -> None:
    _, host = client
    host.create_context.return_value = SESSION
    resp = client[0].post("/sessions", json={"storage_state": None})
    assert resp.status_code == 200
    body = resp.json()
    assert body["session_id"] == "s1"
    assert body["cdp_ws"] == "ws://browser-host:8930/cdp/s1"
    assert body["live_ws"] == "ws://browser-host:8930/live/s1"
    assert body["context_id"] == "ctx-1"


def test_create_session_at_capacity_429(client) -> None:
    _, host = client
    host.create_context.side_effect = AtCapacityError()
    resp = client[0].post("/sessions", json={"storage_state": None})
    assert resp.status_code == 429
    assert resp.json() == {"detail": "at_capacity"}


def test_delete_session_returns_storage_state(client) -> None:
    _, host = client
    host.dispose_context.return_value = {"cookies": [], "origins": []}
    resp = client[0].delete("/sessions/s1")
    assert resp.status_code == 200
    assert resp.json() == {"storage_state": {"cookies": [], "origins": []}}


def test_delete_unknown_session_404(client) -> None:
    _, host = client
    host.dispose_context.side_effect = SessionNotFoundError()
    resp = client[0].delete("/sessions/ghost")
    assert resp.status_code == 404


def test_get_session_returns_info(client) -> None:
    _, host = client
    host.session_info.return_value = INFO
    resp = client[0].get("/sessions/s1")
    assert resp.status_code == 200
    assert resp.json()["session_id"] == "s1"
    assert resp.json()["url"] == "https://example.com"


def test_get_unknown_session_404(client) -> None:
    _, host = client
    host.session_info.side_effect = SessionNotFoundError()
    resp = client[0].get("/sessions/ghost")
    assert resp.status_code == 404


def test_healthz_ok(client) -> None:
    _, host = client
    host.healthz.return_value = {
        "ok": True,
        "sessions": 1,
        "chromium_up": True,
        "cdp_responsive": True,
    }
    resp = client[0].get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_healthz_degraded_returns_503(client) -> None:
    """A wedged Chromium that answers no CDP round-trip reads as unhealthy, so
    the orchestrator restarts the host instead of leaving it half-alive."""
    _, host = client
    host.healthz.return_value = {
        "ok": False,
        "sessions": 0,
        "chromium_up": True,
        "cdp_responsive": False,
    }
    resp = client[0].get("/healthz")
    assert resp.status_code == 503
    assert resp.json()["ok"] is False


def test_cdp_endpoint_closes_4404_for_unknown_session(client) -> None:
    """A caller pointing at a session that does not exist gets the app-level
    close code, not a half-open socket."""
    from fastapi import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect) as exc:
        with client[0].websocket_connect("/cdp/nope"):
            pass
    assert exc.value.code == 4404


def test_control_plane_requires_host_key(client) -> None:
    """A rendered page in the same container can fetch() localhost:8930, so the
    host must never serve the control plane unauthenticated when production."""
    test_cli, host = client
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(server_mod.settings, "ENV", "production")
    monkeypatch.setattr(server_mod.settings, "BROWSER_HOST_KEY", "s3cret!" * 4)
    try:
        # No key -> 401 on every REST surface.
        assert test_cli.post("/sessions", json={"storage_state": None}).status_code == 401
        assert test_cli.get("/sessions/s1").status_code == 401
        assert test_cli.delete("/sessions/s1").status_code == 401
        assert test_cli.get("/healthz").status_code == 401
        # Correct key -> the session flows work (whatever the handler returns).
        host.create_context.return_value = SESSION
        ok = test_cli.post("/sessions", json={"storage_state": None}, headers={"X-Host-Key": "s3cret!" * 4})
        assert ok.status_code == 200
        # Wrong key -> 401.
        bad = test_cli.post("/sessions", json={"storage_state": None}, headers={"X-Host-Key": "nope"})
        assert bad.status_code == 401
    finally:
        monkeypatch.undo()


def test_ws_requires_host_key(client) -> None:
    """WS /cdp + /live refuse sockets without the ?hk= key (4401)."""
    test_cli, host = client
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(server_mod.settings, "ENV", "production")
    monkeypatch.setattr(server_mod.settings, "BROWSER_HOST_KEY", "k" * 32)
    try:
        from fastapi import WebSocketDisconnect

        with pytest.raises(WebSocketDisconnect) as exc:
            with test_cli.websocket_connect("/cdp/s1"):
                pass
        assert exc.value.code == 4401
    finally:
        monkeypatch.undo()
