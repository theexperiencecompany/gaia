"""Tests for the browser-host HTTP API (session lifecycle + health).

Drives the real FastAPI app through TestClient with the ChromiumHost faked, so
the route contract — status codes, error bodies, derived websocket URLs — is
exercised exactly as a caller sees it. The 429-at-capacity and 503-on-degraded
paths are what Docker/user-visible behaviour depends on, so they are pinned
here.
"""

from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException, WebSocket, WebSocketDisconnect
from fastapi.testclient import TestClient
import pytest

from app.browser_host import server as server_mod
from app.browser_host.chromium import AtCapacityError, SessionNotFoundError
from app.constants.log_tags import LogTag

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
        self.touch = MagicMock()


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


def test_touch_session_returns_200_and_touches_the_host(client) -> None:
    _, host = client
    host.get.return_value = SESSION
    resp = client[0].post("/sessions/s1/touch")
    assert resp.status_code == 200
    assert resp.json() == {"session_id": "s1"}
    host.get.assert_called_once_with("s1")
    host.touch.assert_called_once_with("s1")


def test_touch_unknown_session_404_and_never_touches(client) -> None:
    _, host = client
    host.get.return_value = None
    resp = client[0].post("/sessions/ghost/touch")
    assert resp.status_code == 404
    assert resp.json() == {"detail": "session not found"}
    host.touch.assert_not_called()


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
    _, host = client
    with pytest.raises(WebSocketDisconnect) as exc:
        with client[0].websocket_connect("/cdp/nope"):
            pass
    assert exc.value.code == 4404
    host.get.assert_called_once_with("nope")


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
        ok = test_cli.post(
            "/sessions", json={"storage_state": None}, headers={"X-Host-Key": "s3cret!" * 4}
        )
        assert ok.status_code == 200
        # Wrong key -> 401.
        bad = test_cli.post(
            "/sessions", json={"storage_state": None}, headers={"X-Host-Key": "nope"}
        )
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
        with pytest.raises(WebSocketDisconnect) as exc:
            with test_cli.websocket_connect("/cdp/s1"):
                pass
        assert exc.value.code == 4401
        with pytest.raises(WebSocketDisconnect) as exc:
            with test_cli.websocket_connect("/live/s1"):
                pass
        assert exc.value.code == 4401
    finally:
        monkeypatch.undo()


def test_live_endpoint_closes_4404_for_unknown_session(client) -> None:
    """The live-view socket gets the same app-level close code as CDP does."""
    _, host = client
    with pytest.raises(WebSocketDisconnect) as exc:
        with client[0].websocket_connect("/live/nope"):
            pass
    assert exc.value.code == 4404
    host.get.assert_called_once_with("nope")


def test_cdp_endpoint_closes_4404_for_dead_session(client) -> None:
    """A session the reaper already marked dead is unusable, not just missing."""
    _, host = client
    host.get.return_value = MagicMock(session_id="s1", dead=True)
    with pytest.raises(WebSocketDisconnect) as exc:
        with client[0].websocket_connect("/cdp/s1"):
            pass
    assert exc.value.code == 4404


def test_live_endpoint_closes_4404_for_dead_session(client) -> None:
    """The dead-session check must be reachable through the live-view route too,
    not only the CDP route -- a stale live session would otherwise be accepted
    and immediately fail to stream instead of closing cleanly."""
    _, host = client
    host.get.return_value = MagicMock(session_id="s1", dead=True)
    with pytest.raises(WebSocketDisconnect) as exc:
        with client[0].websocket_connect("/live/s1"):
            pass
    assert exc.value.code == 4404


def test_cdp_endpoint_accepts_and_bridges_live_session(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A live session is accepted and handed to the CDP proxy with the exact
    host/session it was looked up for — not just accepted-and-forgotten."""
    _, host = client
    live_session = MagicMock(session_id="exact-id-123", dead=False)
    host.get.return_value = live_session
    proxy = AsyncMock()
    monkeypatch.setattr(server_mod, "run_cdp_proxy", proxy)
    with client[0].websocket_connect("/cdp/exact-id-123"):
        pass
    host.get.assert_called_once_with("exact-id-123")
    proxy.assert_awaited_once()
    called_host, called_session, called_ws = proxy.await_args.args
    assert called_host is host
    assert called_session is live_session
    assert isinstance(called_ws, WebSocket)


def test_live_endpoint_accepts_and_bridges_live_session(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mirrors the CDP happy path: the live-view route must actually accept and
    hand off to ``run_live_view`` -- previously nothing exercised this branch
    at all, so a broken handoff here would have shipped silently."""
    _, host = client
    live_session = MagicMock(session_id="exact-id-123", dead=False)
    host.get.return_value = live_session
    live_view = AsyncMock()
    monkeypatch.setattr(server_mod, "run_live_view", live_view)
    with client[0].websocket_connect("/live/exact-id-123"):
        pass
    host.get.assert_called_once_with("exact-id-123")
    live_view.assert_awaited_once()
    called_host, called_session, called_ws = live_view.await_args.args
    assert called_host is host
    assert called_session is live_session
    assert isinstance(called_ws, WebSocket)


def test_live_endpoint_does_not_touch_host_get_when_unauthorized(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rejecting an unauthorized live-view socket must happen before any session
    lookup -- catches a mutant that reorders the auth check after the lookup."""
    test_cli, host = client
    monkeypatch.setattr(server_mod.settings, "ENV", "production")
    monkeypatch.setattr(server_mod.settings, "BROWSER_HOST_KEY", "k" * 32)
    with pytest.raises(WebSocketDisconnect) as exc:
        with test_cli.websocket_connect("/live/s1"):
            pass
    assert exc.value.code == 4401
    host.get.assert_not_called()


def test_live_endpoint_does_not_bridge_dead_session(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A dead session must close 4404 without ever reaching ``run_live_view`` --
    catches a mutant that drops or inverts the ``session.dead`` check."""
    _, host = client
    host.get.return_value = MagicMock(session_id="s1", dead=True)
    live_view = AsyncMock()
    monkeypatch.setattr(server_mod, "run_live_view", live_view)
    with pytest.raises(WebSocketDisconnect):
        with client[0].websocket_connect("/live/s1"):
            pass
    live_view.assert_not_awaited()


def test_healthz_body_reports_every_field(client) -> None:
    """The health probe surfaces session count and each sub-check, not just ``ok``
    -- the orchestrator/dashboard reads all four fields."""
    _, host = client
    host.healthz.return_value = {
        "ok": True,
        "sessions": 3,
        "chromium_up": True,
        "cdp_responsive": True,
    }
    resp = client[0].get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {
        "ok": True,
        "sessions": 3,
        "chromium_up": True,
        "cdp_responsive": True,
    }


def test_create_session_passes_storage_state_to_host(client) -> None:
    """The seed storage_state on the request must reach the host unchanged --
    dropping it would silently log a user into a blank browser."""
    _, host = client
    host.create_context.return_value = SESSION
    seed = {
        "cookies": [
            {
                "name": "sid",
                "value": "abc",
                "domain": "example.com",
                "path": "/",
                "expires": -1,
                "httpOnly": False,
                "secure": False,
                "sameSite": "Lax",
            }
        ],
        "origins": [],
    }
    resp = client[0].post("/sessions", json={"storage_state": seed})
    assert resp.status_code == 200
    host.create_context.assert_awaited_once()
    (passed_state,) = host.create_context.await_args.args
    assert passed_state is not None
    assert passed_state["cookies"][0]["name"] == "sid"
    assert passed_state["cookies"][0]["value"] == "abc"


def test_delete_session_passes_exact_session_id_to_host(client) -> None:
    _, host = client
    host.dispose_context.return_value = {"cookies": [], "origins": []}
    client[0].delete("/sessions/exact-id-123")
    host.dispose_context.assert_awaited_once_with("exact-id-123")


def test_delete_unknown_session_404_body(client) -> None:
    _, host = client
    host.dispose_context.side_effect = SessionNotFoundError()
    resp = client[0].delete("/sessions/ghost")
    assert resp.status_code == 404
    assert resp.json() == {"detail": "session not found"}


def test_get_session_passes_exact_session_id_to_host(client) -> None:
    _, host = client
    host.session_info.return_value = INFO
    client[0].get("/sessions/exact-id-123")
    host.session_info.assert_awaited_once_with("exact-id-123")


def test_get_unknown_session_404_body(client) -> None:
    _, host = client
    host.session_info.side_effect = SessionNotFoundError()
    resp = client[0].get("/sessions/ghost")
    assert resp.status_code == 404
    assert resp.json() == {"detail": "session not found"}


def test_create_session_at_capacity_body(client) -> None:
    _, host = client
    host.create_context.side_effect = AtCapacityError()
    resp = client[0].post("/sessions", json={"storage_state": None})
    assert resp.status_code == 429
    assert resp.json() == {"detail": "at_capacity"}


# --- _ws_url --------------------------------------------------------------


def test_ws_url_rewrites_https_to_wss(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        server_mod.settings, "BROWSER_HOST_URL", "https://browser-host:8930", raising=False
    )
    monkeypatch.setattr(server_mod.settings, "BROWSER_HOST_KEY", None, raising=False)
    assert server_mod._ws_url("/cdp/s1") == "wss://browser-host:8930/cdp/s1"


def test_ws_url_rewrites_http_to_ws(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        server_mod.settings, "BROWSER_HOST_URL", "http://browser-host:8930", raising=False
    )
    monkeypatch.setattr(server_mod.settings, "BROWSER_HOST_KEY", None, raising=False)
    assert server_mod._ws_url("/cdp/s1") == "ws://browser-host:8930/cdp/s1"


def test_ws_url_strips_trailing_slash_on_base(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        server_mod.settings, "BROWSER_HOST_URL", "http://browser-host:8930/", raising=False
    )
    monkeypatch.setattr(server_mod.settings, "BROWSER_HOST_KEY", None, raising=False)
    assert server_mod._ws_url("/cdp/s1") == "ws://browser-host:8930/cdp/s1"


def test_ws_url_no_key_omits_query_param(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        server_mod.settings, "BROWSER_HOST_URL", "http://browser-host:8930", raising=False
    )
    monkeypatch.setattr(server_mod.settings, "BROWSER_HOST_KEY", None, raising=False)
    assert "?" not in server_mod._ws_url("/cdp/s1")


def test_ws_url_key_appends_hk_query_param(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        server_mod.settings, "BROWSER_HOST_URL", "http://browser-host:8930", raising=False
    )
    monkeypatch.setattr(server_mod.settings, "BROWSER_HOST_KEY", "s3cret", raising=False)
    assert server_mod._ws_url("/cdp/s1") == "ws://browser-host:8930/cdp/s1?hk=s3cret"


def test_ws_url_key_uses_ampersand_when_path_already_has_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A path that already carries a query string must get ``&hk=``, not a second
    ``?`` that would produce an invalid URL."""
    monkeypatch.setattr(
        server_mod.settings, "BROWSER_HOST_URL", "http://browser-host:8930", raising=False
    )
    monkeypatch.setattr(server_mod.settings, "BROWSER_HOST_KEY", "s3cret", raising=False)
    assert (
        server_mod._ws_url("/cdp/s1?foo=bar") == "ws://browser-host:8930/cdp/s1?foo=bar&hk=s3cret"
    )


# --- _key_valid -------------------------------------------------------------


def test_key_valid_no_key_configured_allows_in_development(monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing key is fine outside production (local dev tooling)."""
    monkeypatch.setattr(server_mod.settings, "BROWSER_HOST_KEY", None, raising=False)
    monkeypatch.setattr(server_mod.settings, "ENV", "development", raising=False)
    assert server_mod._key_valid("anything") is True
    assert server_mod._key_valid(None) is True


def test_key_valid_no_key_configured_refuses_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing key must fail loud, not silently serve unauthenticated, in prod."""
    monkeypatch.setattr(server_mod.settings, "BROWSER_HOST_KEY", None, raising=False)
    monkeypatch.setattr(server_mod.settings, "ENV", "production", raising=False)
    assert server_mod._key_valid("anything") is False
    assert server_mod._key_valid(None) is False


def test_key_valid_rejects_none_candidate_when_key_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(server_mod.settings, "BROWSER_HOST_KEY", "s3cret", raising=False)
    assert server_mod._key_valid(None) is False


def test_key_valid_rejects_empty_candidate_when_key_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(server_mod.settings, "BROWSER_HOST_KEY", "s3cret", raising=False)
    assert server_mod._key_valid("") is False


def test_key_valid_rejects_wrong_candidate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server_mod.settings, "BROWSER_HOST_KEY", "s3cret", raising=False)
    assert server_mod._key_valid("wrong") is False


def test_key_valid_accepts_matching_candidate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server_mod.settings, "BROWSER_HOST_KEY", "s3cret", raising=False)
    assert server_mod._key_valid("s3cret") is True


# --- _require_host_key -------------------------------------------------------


def test_require_host_key_raises_401_with_exact_detail(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server_mod.settings, "BROWSER_HOST_KEY", "s3cret", raising=False)
    request = MagicMock()
    request.headers.get.return_value = None
    with pytest.raises(HTTPException) as exc:
        server_mod._require_host_key(request)
    assert exc.value.status_code == 401
    assert exc.value.detail == "missing or invalid host key"
    request.headers.get.assert_called_once_with("X-Host-Key")


def test_require_host_key_passes_silently_with_valid_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server_mod.settings, "BROWSER_HOST_KEY", "s3cret", raising=False)
    request = MagicMock()
    request.headers.get.return_value = "s3cret"
    server_mod._require_host_key(request)  # must not raise


# --- _ws_authorized -----------------------------------------------------------


class _FakeWebSocket:
    """Duck-types the bits of ``WebSocket`` that ``_ws_authorized`` reads."""

    def __init__(self, hk: str | None, origin: str | None = None) -> None:
        self.query_params: dict[str, str] = {"hk": hk} if hk is not None else {}
        self.headers: dict[str, object] = {"origin": origin} if origin is not None else {}


class _BadOrigin(str):
    """An Origin value whose parse blows up, to drive the except branch."""

    def split(self, *args: object, **kwargs: object) -> list[str]:
        raise ValueError("boom")


def _fake_ws(hk: str | None, origin: str | None = None) -> WebSocket:
    return cast(WebSocket, _FakeWebSocket(hk, origin))


def test_ws_authorized_rejects_missing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server_mod.settings, "BROWSER_HOST_KEY", "s3cret", raising=False)
    assert server_mod._ws_authorized(_fake_ws(None)) is False


def test_ws_authorized_rejects_wrong_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server_mod.settings, "BROWSER_HOST_KEY", "s3cret", raising=False)
    assert server_mod._ws_authorized(_fake_ws("wrong")) is False


def test_ws_authorized_accepts_valid_key_with_no_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    """Server-side clients (browser-use, the API's live-view proxy) send no
    Origin header at all -- that must not be treated as a rejection."""
    monkeypatch.setattr(server_mod.settings, "BROWSER_HOST_KEY", "s3cret", raising=False)
    assert server_mod._ws_authorized(_fake_ws("s3cret", None)) is True


def test_ws_authorized_accepts_loopback_origin_without_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(server_mod.settings, "BROWSER_HOST_KEY", "s3cret", raising=False)
    assert server_mod._ws_authorized(_fake_ws("s3cret", "https://127.0.0.1")) is True


def test_ws_authorized_accepts_loopback_origin_with_port_and_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(server_mod.settings, "BROWSER_HOST_KEY", "s3cret", raising=False)
    assert server_mod._ws_authorized(_fake_ws("s3cret", "http://localhost:3000/some/path")) is True


def test_ws_authorized_rejects_cross_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    """A valid key does not save a request whose Origin is a rendered,
    attacker-controlled page -- that is the defense-in-depth this exists for."""
    monkeypatch.setattr(server_mod.settings, "BROWSER_HOST_KEY", "s3cret", raising=False)
    assert server_mod._ws_authorized(_fake_ws("s3cret", "https://evil.example.com")) is False


def test_ws_authorized_rejects_cross_origin_even_with_loopback_substring(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Guards against a naive substring/prefix check standing in for the exact
    host comparison."""
    monkeypatch.setattr(server_mod.settings, "BROWSER_HOST_KEY", "s3cret", raising=False)
    assert (
        server_mod._ws_authorized(_fake_ws("s3cret", "https://localhost.evil.example.com")) is False
    )


def test_ws_authorized_rejects_unparsable_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    """An Origin value that blows up while being parsed is a rejection, not a
    500 -- the except clause must actually return False."""
    monkeypatch.setattr(server_mod.settings, "BROWSER_HOST_KEY", "s3cret", raising=False)
    assert server_mod._ws_authorized(_fake_ws("s3cret", _BadOrigin("http://bad"))) is False


def test_ws_authorized_accepts_loopback_origin_with_path_but_no_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only the authority is compared: a port-less Origin carrying a multi-segment
    path still resolves to ``localhost``, so the socket is allowed."""
    monkeypatch.setattr(server_mod.settings, "BROWSER_HOST_KEY", "s3cret", raising=False)
    assert server_mod._ws_authorized(_fake_ws("s3cret", "http://localhost/some/path")) is True


def test_ws_authorized_accepts_bare_ipv6_loopback_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    """``::1`` is in the allow-list, and its colons must not be mistaken for the
    port separator -- only the last one is."""
    monkeypatch.setattr(server_mod.settings, "BROWSER_HOST_KEY", "s3cret", raising=False)
    assert server_mod._ws_authorized(_fake_ws("s3cret", "http://::1:8930")) is True


def test_ws_authorized_rejects_origin_with_a_second_scheme_in_the_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``http://localhost:8080://x`` has ``localhost:8080:`` as its authority, not
    ``localhost`` -- only the FIRST ``://`` separates the scheme, so this stays a
    rejection rather than being smuggled through as loopback."""
    monkeypatch.setattr(server_mod.settings, "BROWSER_HOST_KEY", "s3cret", raising=False)
    assert server_mod._ws_authorized(_fake_ws("s3cret", "http://localhost:8080://x")) is False


def test_ws_authorized_accepts_loopback_origin_with_a_scheme_inside_its_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A ``://`` later in the path does not move the host boundary -- the host is
    read from the FIRST ``://``, so this is still loopback."""
    monkeypatch.setattr(server_mod.settings, "BROWSER_HOST_KEY", "s3cret", raising=False)
    assert server_mod._ws_authorized(_fake_ws("s3cret", "http://localhost/x://y")) is True


def test_ws_authorized_rejects_origin_with_two_port_separators(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``localhost:1:2`` is not ``localhost``: only the last colon is a port
    separator, so the leftover ``localhost:1`` fails the allow-list."""
    monkeypatch.setattr(server_mod.settings, "BROWSER_HOST_KEY", "s3cret", raising=False)
    assert server_mod._ws_authorized(_fake_ws("s3cret", "https://localhost:1:2")) is False


def test_ws_authorized_logs_exact_context_and_message_for_unparsable_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The rejection must be observable: exact wide-event field, exact message,
    and the real exception type -- that is all an operator has to go on."""
    monkeypatch.setattr(server_mod.settings, "BROWSER_HOST_KEY", "s3cret", raising=False)
    with patch.object(server_mod, "log") as mock_log:
        assert server_mod._ws_authorized(_fake_ws("s3cret", _BadOrigin("http://bad"))) is False
    mock_log.set.assert_called_once_with(browser={"operation": "ws_origin_reject"})
    mock_log.warning.assert_called_once_with(
        f"{LogTag.BROWSER} live-view WS rejected: unparsable Origin",
        error_type="ValueError",
    )


def test_ws_authorized_logs_exact_context_and_message_for_cross_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The cross-origin rejection carries its own message, distinct from the
    unparsable-Origin one, under the same wide-event operation."""
    monkeypatch.setattr(server_mod.settings, "BROWSER_HOST_KEY", "s3cret", raising=False)
    with patch.object(server_mod, "log") as mock_log:
        assert server_mod._ws_authorized(_fake_ws("s3cret", "https://evil.example.com")) is False
    mock_log.set.assert_called_once_with(browser={"operation": "ws_origin_reject"})
    mock_log.warning.assert_called_once_with(
        f"{LogTag.BROWSER} live-view WS rejected: cross-origin Origin"
    )


def test_ws_authorized_logs_nothing_when_it_allows_the_socket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An accepted socket emits no rejection event -- otherwise the operation
    field would be noise instead of a signal."""
    monkeypatch.setattr(server_mod.settings, "BROWSER_HOST_KEY", "s3cret", raising=False)
    with patch.object(server_mod, "log") as mock_log:
        assert server_mod._ws_authorized(_fake_ws("s3cret", "http://localhost:3000")) is True
    mock_log.set.assert_not_called()
    mock_log.warning.assert_not_called()


# --- _ws_url: the rewrite touches the scheme only -----------------------------


def test_ws_url_rewrites_only_the_leading_http_scheme(monkeypatch: pytest.MonkeyPatch) -> None:
    """A later ``http://`` inside the URL is data, not a scheme -- rewriting it
    too would corrupt the address."""
    monkeypatch.setattr(
        server_mod.settings, "BROWSER_HOST_URL", "http://proxy/http://inner", raising=False
    )
    monkeypatch.setattr(server_mod.settings, "BROWSER_HOST_KEY", None, raising=False)
    assert server_mod._ws_url("/cdp/s1") == "ws://proxy/http://inner/cdp/s1"


def test_ws_url_rewrites_only_the_leading_https_scheme(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        server_mod.settings, "BROWSER_HOST_URL", "https://proxy/https://inner", raising=False
    )
    monkeypatch.setattr(server_mod.settings, "BROWSER_HOST_KEY", None, raising=False)
    assert server_mod._ws_url("/cdp/s1") == "wss://proxy/https://inner/cdp/s1"


def test_ws_url_strips_only_a_trailing_slash_not_path_characters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A base URL mounted under a path prefix keeps that prefix intact -- only a
    trailing ``/`` is removed."""
    monkeypatch.setattr(
        server_mod.settings, "BROWSER_HOST_URL", "http://browser-host:8930/PREFIX", raising=False
    )
    monkeypatch.setattr(server_mod.settings, "BROWSER_HOST_KEY", None, raising=False)
    assert server_mod._ws_url("/cdp/s1") == "ws://browser-host:8930/PREFIX/cdp/s1"


# --- wide-event context on every route ----------------------------------------


def test_create_session_sets_exact_log_context(client) -> None:
    _, host = client
    host.create_context.return_value = SESSION
    with patch.object(server_mod, "log") as mock_log:
        resp = client[0].post("/sessions", json={"storage_state": None})
    assert resp.status_code == 200
    mock_log.set.assert_called_once_with(browser={"operation": "create"})


def test_create_session_at_capacity_logs_exact_warning(client) -> None:
    _, host = client
    host.create_context.side_effect = AtCapacityError()
    with patch.object(server_mod, "log") as mock_log:
        resp = client[0].post("/sessions", json={"storage_state": None})
    assert resp.status_code == 429
    mock_log.warning.assert_called_once_with(f"{LogTag.BROWSER} browser host at capacity")


def test_delete_session_sets_exact_log_context(client) -> None:
    _, host = client
    host.dispose_context.return_value = {"cookies": [], "origins": []}
    with patch.object(server_mod, "log") as mock_log:
        resp = client[0].delete("/sessions/exact-id-123")
    assert resp.status_code == 200
    mock_log.set.assert_called_once_with(
        browser={"session_id": "exact-id-123", "operation": "delete"}
    )


def test_get_session_sets_exact_log_context(client) -> None:
    _, host = client
    host.session_info.return_value = INFO
    with patch.object(server_mod, "log") as mock_log:
        resp = client[0].get("/sessions/exact-id-123")
    assert resp.status_code == 200
    mock_log.set.assert_called_once_with(browser={"session_id": "exact-id-123", "operation": "get"})


def test_healthz_sets_exact_log_context(client) -> None:
    """Health checks carry an empty ``session_id`` so the field is present on the
    wide event rather than absent for this one route."""
    _, host = client
    host.healthz.return_value = {
        "ok": True,
        "sessions": 0,
        "chromium_up": True,
        "cdp_responsive": True,
    }
    with patch.object(server_mod, "log") as mock_log:
        resp = client[0].get("/healthz")
    assert resp.status_code == 200
    mock_log.set.assert_called_once_with(browser={"operation": "healthz", "session_id": ""})


def test_cdp_endpoint_sets_exact_log_context(client) -> None:
    _, host = client
    with patch.object(server_mod, "log") as mock_log:
        with pytest.raises(WebSocketDisconnect):
            with client[0].websocket_connect("/cdp/exact-id-123"):
                pass
    mock_log.set.assert_called_once_with(
        browser={"operation": "cdp_ws", "session_id": "exact-id-123"}
    )


def test_live_endpoint_sets_exact_log_context(client) -> None:
    _, host = client
    with patch.object(server_mod, "log") as mock_log:
        with pytest.raises(WebSocketDisconnect):
            with client[0].websocket_connect("/live/exact-id-123"):
                pass
    mock_log.set.assert_called_once_with(
        browser={"operation": "live_ws", "session_id": "exact-id-123"}
    )
