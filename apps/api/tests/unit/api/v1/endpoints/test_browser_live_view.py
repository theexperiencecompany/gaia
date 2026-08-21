"""Coverage for app/api/v1/endpoints/browser_live_view.py

Exercises every endpoint and helper with real function calls, mocking only
external services (Redis registry, takeover tokens, WebSockets, auth deps).
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException, Request, WebSocket, status
from fastapi.responses import HTMLResponse
from jose import JWTError
import pytest
import websockets

from app.api.v1.endpoints import browser_live_view as blv
from app.schemas.browser import LiveCodeRecord, ReplayRecord
from app.services.browser.registry import SessionRegistryEntry

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_request(
    cookies: dict[str, str] | None = None, headers: dict[str, str] | None = None
) -> MagicMock:
    req = MagicMock(spec=Request)
    req.cookies = cookies or {}
    req.headers = headers or {}
    return req


def _make_ws(
    cookies: dict[str, str] | None = None, headers: dict[str, str] | None = None
) -> MagicMock:
    ws = MagicMock(spec=WebSocket)
    ws.cookies = cookies or {}
    ws.headers = headers or {}
    ws.close = AsyncMock()
    ws.accept = AsyncMock()
    ws.send_bytes = AsyncMock()
    ws.send_text = AsyncMock()
    ws.receive_text = AsyncMock()
    return ws


# ---------------------------------------------------------------------------
# replay_page
# ---------------------------------------------------------------------------


class TestReplayPage:
    async def test_success(self) -> None:
        record = ReplayRecord(
            session_id="s1", steps=2, shots=["https://cdn/1.png", "https://cdn/2.png"]
        )
        with (
            patch.object(blv, "resolve_replay_code", new=AsyncMock(return_value=record)),
            patch.object(
                blv, "render_replay_page", return_value="<html>replay</html>"
            ) as mock_render,
        ):
            resp = await blv.replay_page("code123")
            assert isinstance(resp, HTMLResponse)
            assert resp.body.decode() == "<html>replay</html>"
            mock_render.assert_called_once_with(record)

    async def test_not_found(self) -> None:
        with patch.object(blv, "resolve_replay_code", new=AsyncMock(return_value=None)):
            with pytest.raises(HTTPException) as exc:
                await blv.replay_page("badcode")
            assert exc.value.status_code == status.HTTP_404_NOT_FOUND


# ---------------------------------------------------------------------------
# live_view_page
# ---------------------------------------------------------------------------


class TestLiveViewPage:
    async def test_via_live_code_success(self) -> None:
        with (
            patch.object(blv, "_resolve_target_page", new=AsyncMock(return_value=("sess1", "u1"))),
            patch.object(blv.registry, "session_owner", new=AsyncMock(return_value="u1")),
            patch.object(blv, "render_live_view_page", return_value="<html>live</html>"),
        ):
            req = _make_request()
            resp = await blv.live_view_page("code123", req, t=None)
            assert isinstance(resp, HTMLResponse)

    async def test_via_live_code_owner_mismatch_403(self) -> None:
        with (
            patch.object(blv, "_resolve_target_page", new=AsyncMock(return_value=("sess1", "u1"))),
            patch.object(blv.registry, "session_owner", new=AsyncMock(return_value="other")),
        ):
            req = _make_request()
            with pytest.raises(HTTPException) as exc:
                await blv.live_view_page("code123", req, t=None)
            assert exc.value.status_code == status.HTTP_403_FORBIDDEN

    async def test_via_live_code_no_owner_403(self) -> None:
        with (
            patch.object(blv, "_resolve_target_page", new=AsyncMock(return_value=("sess1", "u1"))),
            patch.object(blv.registry, "session_owner", new=AsyncMock(return_value=None)),
        ):
            req = _make_request()
            with pytest.raises(HTTPException) as exc:
                await blv.live_view_page("code123", req, t=None)
            assert exc.value.status_code == status.HTTP_403_FORBIDDEN

    async def test_resolve_target_page_via_code(self) -> None:
        rec = LiveCodeRecord(session_id="sess1", user_id="u1")
        with patch.object(blv, "resolve_live_code", new=AsyncMock(return_value=rec)):
            sid, uid = await blv._resolve_target_page("code123", _make_request(), None)
            assert sid == "sess1"
            assert uid == "u1"

    async def test_resolve_target_page_via_token_fallback(self) -> None:
        with (
            patch.object(blv, "resolve_live_code", new=AsyncMock(return_value=None)),
            patch.object(blv, "_authorize_page", new=AsyncMock(return_value="u2")),
        ):
            sid, uid = await blv._resolve_target_page("sess-raw", _make_request(), "tok")
            assert sid == "sess-raw"
            assert uid == "u2"


# ---------------------------------------------------------------------------
# _authorize_page / _verify_scoped_token
# ---------------------------------------------------------------------------


class TestAuthorizePage:
    async def test_with_token_success(self) -> None:
        claims: dict[str, object] = {"session_id": "sess1", "user_id": "u1", "exp": 9999999999.0}
        with patch.object(blv, "_verify_scoped_token", return_value=claims):
            uid = await blv._authorize_page(_make_request(), "sess1", token="tok123")
            assert uid == "u1"

    async def test_with_token_verifies_scoped(self) -> None:
        claims = {"session_id": "sess1", "user_id": "u1", "exp": 9999999999.0}
        with patch.object(blv, "verify_takeover_token", return_value=claims):
            out = blv._verify_scoped_token("tok", "sess1")
            assert out["user_id"] == "u1"

    async def test_verify_scoped_token_invalid_raises_401(self) -> None:
        with patch.object(blv, "verify_takeover_token", side_effect=JWTError("bad")):
            with pytest.raises(HTTPException) as exc:
                blv._verify_scoped_token("bad", "sess1")
            assert exc.value.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_verify_scoped_token_mismatch_raises_403(self) -> None:
        claims = {"session_id": "other", "user_id": "u1", "exp": 9999999999.0}
        with patch.object(blv, "verify_takeover_token", return_value=claims):
            with pytest.raises(HTTPException) as exc:
                blv._verify_scoped_token("tok", "sess1")
            assert exc.value.status_code == status.HTTP_403_FORBIDDEN

    async def test_with_cookie_success(self) -> None:
        req = _make_request()
        with patch.object(blv, "get_current_user", new=AsyncMock(return_value={"user_id": "u1"})):
            uid = await blv._authorize_page(req, "sess1", token=None)
            assert uid == "u1"

    async def test_with_cookie_missing_user_id_raises_400(self) -> None:
        req = _make_request()
        with patch.object(blv, "get_current_user", new=AsyncMock(return_value={"user_id": None})):
            with pytest.raises(HTTPException) as exc:
                await blv._authorize_page(req, "sess1", token=None)
            assert exc.value.status_code == status.HTTP_400_BAD_REQUEST

    async def test_with_cookie_empty_user_id_raises_400(self) -> None:
        req = _make_request()
        with patch.object(blv, "get_current_user", new=AsyncMock(return_value={})):
            with pytest.raises(HTTPException) as exc:
                await blv._authorize_page(req, "sess1", token=None)
            assert exc.value.status_code == status.HTTP_400_BAD_REQUEST


# ---------------------------------------------------------------------------
# _authorize_ws
# ---------------------------------------------------------------------------


class TestAuthorizeWs:
    async def test_token_success(self) -> None:
        claims: dict[str, object] = {"session_id": "sess1", "user_id": "u1", "exp": 9999999999.0}
        with (
            patch.object(blv, "verify_takeover_token", return_value=claims),
            patch.object(blv, "takeover_token_ttl_seconds", return_value=100.0),
        ):
            ws = _make_ws()
            result = await blv._authorize_ws(ws, "sess1", token="tok")
            assert result is not None
            uid, ttl = result
            assert uid == "u1"
            assert ttl == 100.0

    async def test_token_expired_clamped_to_zero(self) -> None:
        claims: dict[str, object] = {"session_id": "sess1", "user_id": "u1", "exp": 100.0}
        with (
            patch.object(blv, "verify_takeover_token", return_value=claims),
            patch.object(blv, "takeover_token_ttl_seconds", return_value=-50.0),
        ):
            ws = _make_ws()
            result = await blv._authorize_ws(ws, "sess1", token="tok")
            assert result is not None
            _, ttl = result
            assert ttl == 0.0

    async def test_token_invalid_closes_1008(self) -> None:
        with patch.object(blv, "verify_takeover_token", side_effect=JWTError("bad")):
            ws = _make_ws()
            result = await blv._authorize_ws(ws, "sess1", token="bad")
            assert result is None
            ws.close.assert_awaited_once_with(code=status.WS_1008_POLICY_VIOLATION)

    async def test_token_session_mismatch_closes_1008(self) -> None:
        claims: dict[str, object] = {"session_id": "other", "user_id": "u1", "exp": 9999999999.0}
        with patch.object(blv, "verify_takeover_token", return_value=claims):
            ws = _make_ws()
            result = await blv._authorize_ws(ws, "sess1", token="tok")
            assert result is None
            ws.close.assert_awaited_once_with(code=status.WS_1008_POLICY_VIOLATION)

    async def test_cookie_success(self) -> None:
        ws = _make_ws()
        with patch.object(
            blv, "get_current_user_ws", new=AsyncMock(return_value={"user_id": "u1"})
        ):
            result = await blv._authorize_ws(ws, "sess1", token=None)
            assert result is not None
            assert result[0] == "u1"
            assert result[1] is None

    async def test_cookie_missing_user_id_returns_none(self) -> None:
        ws = _make_ws()
        with patch.object(
            blv, "get_current_user_ws", new=AsyncMock(return_value={"user_id": None})
        ):
            result = await blv._authorize_ws(ws, "sess1", token=None)
            assert result is None

    async def test_cookie_empty_dict_returns_none(self) -> None:
        ws = _make_ws()
        with patch.object(blv, "get_current_user_ws", new=AsyncMock(return_value={})):
            result = await blv._authorize_ws(ws, "sess1", token=None)
            assert result is None

    async def test_cookie_no_user_returns_none(self) -> None:
        ws = _make_ws()
        with patch.object(blv, "get_current_user_ws", new=AsyncMock(return_value={})):
            result = await blv._authorize_ws(ws, "sess1", token=None)
            assert result is None
            ws.close.assert_not_called()


# ---------------------------------------------------------------------------
# _resolve_target_ws
# ---------------------------------------------------------------------------


class TestResolveTargetWs:
    async def test_via_code_returns_no_ttl(self) -> None:
        rec = LiveCodeRecord(session_id="sess1", user_id="u1")
        with patch.object(blv, "resolve_live_code", new=AsyncMock(return_value=rec)):
            result = await blv._resolve_target_ws(_make_ws(), "code123", None)
            assert result == ("sess1", "u1", None)

    async def test_via_token(self) -> None:
        with (
            patch.object(blv, "resolve_live_code", new=AsyncMock(return_value=None)),
            patch.object(blv, "_authorize_ws", new=AsyncMock(return_value=("u1", 100.0))),
        ):
            result = await blv._resolve_target_ws(_make_ws(), "sess1", "tok")
            assert result == ("sess1", "u1", 100.0)

    async def test_via_token_auth_fails_returns_none(self) -> None:
        with (
            patch.object(blv, "resolve_live_code", new=AsyncMock(return_value=None)),
            patch.object(blv, "_authorize_ws", new=AsyncMock(return_value=None)),
        ):
            result = await blv._resolve_target_ws(_make_ws(), "sess1", "tok")
            assert result is None


# ---------------------------------------------------------------------------
# live_view_ws
# ---------------------------------------------------------------------------


class TestLiveViewWs:
    async def test_code_path_no_owner_closes_1008(self) -> None:
        ws = _make_ws()
        with (
            patch.object(
                blv, "_resolve_target_ws", new=AsyncMock(return_value=("sess1", "u1", None))
            ),
            patch.object(blv.registry, "get_session_entry", new=AsyncMock(return_value=None)),
        ):
            await blv.live_view_ws(ws, "sess1", t=None)
            ws.close.assert_awaited_once_with(code=status.WS_1008_POLICY_VIOLATION)

    async def test_code_path_wrong_owner_closes_1008(self) -> None:
        ws = _make_ws()
        entry = SessionRegistryEntry(owner="other", live_ws="ws://host/live/1")
        with (
            patch.object(
                blv, "_resolve_target_ws", new=AsyncMock(return_value=("sess1", "u1", None))
            ),
            patch.object(blv.registry, "get_session_entry", new=AsyncMock(return_value=entry)),
        ):
            await blv.live_view_ws(ws, "sess1", t=None)
            ws.close.assert_awaited_once_with(code=status.WS_1008_POLICY_VIOLATION)

    async def test_code_path_no_live_ws_closes_4404(self) -> None:
        ws = _make_ws()
        entry = SessionRegistryEntry(owner="u1", live_ws=None)
        with (
            patch.object(
                blv, "_resolve_target_ws", new=AsyncMock(return_value=("sess1", "u1", None))
            ),
            patch.object(blv.registry, "get_session_entry", new=AsyncMock(return_value=entry)),
        ):
            await blv.live_view_ws(ws, "sess1", t=None)
            ws.close.assert_awaited_once_with(code=blv._WS_SESSION_GONE)

    async def test_code_path_success_proxies(self) -> None:
        ws = _make_ws()
        ws.accept = AsyncMock()
        entry = SessionRegistryEntry(owner="u1", live_ws="ws://host/live/1")
        with (
            patch.object(
                blv, "_resolve_target_ws", new=AsyncMock(return_value=("sess1", "u1", None))
            ),
            patch.object(blv.registry, "get_session_entry", new=AsyncMock(return_value=entry)),
            patch.object(blv, "_proxy_live_view", new=AsyncMock()) as mock_proxy,
        ):
            await blv.live_view_ws(ws, "sess1", t=None)
            ws.accept.assert_awaited_once()
            mock_proxy.assert_awaited_once_with(ws, "ws://host/live/1", None)

    async def test_code_path_success_with_ttl(self) -> None:
        ws = _make_ws()
        ws.accept = AsyncMock()
        entry = SessionRegistryEntry(owner="u1", live_ws="ws://host/live/1")
        with (
            patch.object(
                blv, "_resolve_target_ws", new=AsyncMock(return_value=("sess1", "u1", 42.0))
            ),
            patch.object(blv.registry, "get_session_entry", new=AsyncMock(return_value=entry)),
            patch.object(blv, "_proxy_live_view", new=AsyncMock()) as mock_proxy,
        ):
            await blv.live_view_ws(ws, "sess1", t="tok")
            mock_proxy.assert_awaited_once_with(ws, "ws://host/live/1", 42.0)

    async def test_resolve_returns_none_already_closed(self) -> None:
        ws = _make_ws()
        with patch.object(blv, "_resolve_target_ws", new=AsyncMock(return_value=None)):
            await blv.live_view_ws(ws, "sess1", t="bad")
            ws.accept.assert_not_called()

    async def test_no_live_ws_entry_none_closes_4404(self) -> None:
        ws = _make_ws()
        entry = SessionRegistryEntry(owner="u1", live_ws=None)
        with (
            patch.object(
                blv, "_resolve_target_ws", new=AsyncMock(return_value=("sess1", "u1", None))
            ),
            patch.object(blv.registry, "get_session_entry", new=AsyncMock(return_value=entry)),
        ):
            await blv.live_view_ws(ws, "sess1")
            ws.close.assert_awaited_once()
            assert ws.close.call_args[1]["code"] == 4404

    async def test_no_live_ws_empty_string_closes_4404(self) -> None:
        ws = _make_ws()
        entry = SessionRegistryEntry(owner="u1", live_ws="")
        with (
            patch.object(
                blv, "_resolve_target_ws", new=AsyncMock(return_value=("sess1", "u1", None))
            ),
            patch.object(blv.registry, "get_session_entry", new=AsyncMock(return_value=entry)),
        ):
            await blv.live_view_ws(ws, "sess1")
            ws.close.assert_awaited_once_with(code=blv._WS_SESSION_GONE)


# ---------------------------------------------------------------------------
# _proxy_live_view
# ---------------------------------------------------------------------------


class TestProxyLiveView:
    async def test_success_without_ttl(self) -> None:
        client_ws = _make_ws()
        client_ws.close = AsyncMock()
        mock_host_ws = AsyncMock()
        mock_host_ws.__aenter__ = AsyncMock(return_value=mock_host_ws)
        mock_host_ws.__aexit__ = AsyncMock(return_value=False)
        with (
            patch.object(blv.websockets, "connect", return_value=mock_host_ws),
            patch.object(blv, "pump_until_first_close", new=AsyncMock()) as mock_pump,
        ):
            await blv._proxy_live_view(client_ws, "ws://host/live/1", None)
            assert mock_pump.call_count == 1
            assert len(mock_pump.call_args[0]) == 2
            client_ws.close.assert_awaited_once()

    async def test_success_with_ttl(self) -> None:
        client_ws = _make_ws()
        client_ws.close = AsyncMock()
        mock_host_ws = AsyncMock()
        mock_host_ws.__aenter__ = AsyncMock(return_value=mock_host_ws)
        mock_host_ws.__aexit__ = AsyncMock(return_value=False)
        with (
            patch.object(blv.websockets, "connect", return_value=mock_host_ws),
            patch.object(blv, "pump_until_first_close", new=AsyncMock()) as mock_pump,
        ):
            await blv._proxy_live_view(client_ws, "ws://host/live/1", 60.0)
            assert len(mock_pump.call_args[0]) == 3

    async def test_host_unreachable_oserror(self) -> None:
        client_ws = _make_ws()
        client_ws.close = AsyncMock()
        with patch.object(blv.websockets, "connect", side_effect=OSError("refused")):
            await blv._proxy_live_view(client_ws, "ws://host/live/1", None)
            client_ws.close.assert_awaited_once()

    async def test_host_unreachable_websocket_exception(self) -> None:
        client_ws = _make_ws()
        client_ws.close = AsyncMock()
        with patch.object(
            blv.websockets, "connect", side_effect=websockets.exceptions.WebSocketException("boom")
        ):
            await blv._proxy_live_view(client_ws, "ws://host/live/1", None)
            client_ws.close.assert_awaited_once()

    async def test_connect_max_size_none(self) -> None:
        client_ws = _make_ws()
        client_ws.close = AsyncMock()
        mock_host_ws = AsyncMock()
        mock_host_ws.__aenter__ = AsyncMock(return_value=mock_host_ws)
        mock_host_ws.__aexit__ = AsyncMock(return_value=False)
        with (
            patch.object(blv.websockets, "connect", return_value=mock_host_ws) as mock_connect,
            patch.object(blv, "pump_until_first_close", new=AsyncMock()),
        ):
            await blv._proxy_live_view(client_ws, "ws://host/live/1", None)
            mock_connect.assert_called_once_with("ws://host/live/1", max_size=None)

    async def test_client_ws_close_suppressed_on_error(self) -> None:
        client_ws = _make_ws()
        client_ws.close = AsyncMock(side_effect=RuntimeError("close boom"))
        mock_host_ws = AsyncMock()
        mock_host_ws.__aenter__ = AsyncMock(return_value=mock_host_ws)
        mock_host_ws.__aexit__ = AsyncMock(return_value=False)
        with (
            patch.object(blv.websockets, "connect", return_value=mock_host_ws),
            patch.object(blv, "pump_until_first_close", new=AsyncMock()),
        ):
            await blv._proxy_live_view(client_ws, "ws://host/live/1", None)


# ---------------------------------------------------------------------------
# _pump_host_to_client / _pump_client_to_host / _expire_after
# ---------------------------------------------------------------------------


class TestPumps:
    async def test_pump_host_to_client_bytes_and_text(self) -> None:
        class FakeHostWs:
            def __init__(self, msgs: list[object]) -> None:
                self.msgs = msgs

            def __aiter__(self):
                return self

            async def __anext__(self):
                if not self.msgs:
                    raise StopAsyncIteration
                return self.msgs.pop(0)

        host_ws = FakeHostWs([b"bytes-frame", "text-frame"])
        client_ws = _make_ws()
        await blv._pump_host_to_client(host_ws, client_ws)
        client_ws.send_bytes.assert_awaited_once_with(b"bytes-frame")
        client_ws.send_text.assert_awaited_once_with("text-frame")

    async def test_pump_host_to_client_empty(self) -> None:
        class EmptyHost:
            def __aiter__(self):
                return self

            async def __anext__(self):
                raise StopAsyncIteration

        host_ws = EmptyHost()
        client_ws = _make_ws()
        await blv._pump_host_to_client(host_ws, client_ws)
        client_ws.send_bytes.assert_not_called()
        client_ws.send_text.assert_not_called()

    async def test_pump_client_to_host(self) -> None:
        client_ws = _make_ws()
        client_ws.receive_text = AsyncMock(side_effect=["hello", asyncio.CancelledError()])
        host_ws = MagicMock()
        host_ws.send = AsyncMock()
        with pytest.raises(asyncio.CancelledError):
            await blv._pump_client_to_host(client_ws, host_ws)
        host_ws.send.assert_awaited_once_with("hello")

    async def test_pump_client_to_host_multiple(self) -> None:
        client_ws = _make_ws()
        client_ws.receive_text = AsyncMock(side_effect=["a", "b", asyncio.CancelledError()])
        host_ws = MagicMock()
        host_ws.send = AsyncMock()
        with pytest.raises(asyncio.CancelledError):
            await blv._pump_client_to_host(client_ws, host_ws)
        assert host_ws.send.await_count == 2

    async def test_expire_after_sleeps(self) -> None:
        with patch.object(blv.asyncio, "sleep", new=AsyncMock()) as mock_sleep:
            await blv._expire_after(10.0)
            mock_sleep.assert_awaited_once_with(10.0)

    async def test_expire_after_negative_clamped(self) -> None:
        with patch.object(blv.asyncio, "sleep", new=AsyncMock()) as mock_sleep:
            await blv._expire_after(-5.0)
            mock_sleep.assert_awaited_once_with(0.0)

    async def test_expire_after_zero(self) -> None:
        with patch.object(blv.asyncio, "sleep", new=AsyncMock()) as mock_sleep:
            await blv._expire_after(0.0)
            mock_sleep.assert_awaited_once_with(0.0)


# ---------------------------------------------------------------------------
# Additional live_view_page branches
# ---------------------------------------------------------------------------


class TestLiveViewPageExtra:
    async def test_via_token_path(self) -> None:
        with (
            patch.object(blv, "resolve_live_code", new=AsyncMock(return_value=None)),
            patch.object(
                blv,
                "verify_takeover_token",
                return_value={"session_id": "sess1", "user_id": "u1", "exp": 9999999999.0},
            ),
            patch.object(blv, "get_current_user", new=AsyncMock(return_value={"user_id": "u1"})),
            patch.object(blv.registry, "session_owner", new=AsyncMock(return_value="u1")),
            patch.object(blv, "render_live_view_page", return_value="<html>"),
        ):
            req = _make_request()
            resp = await blv.live_view_page("sess1", req, t="tok123")
            assert isinstance(resp, HTMLResponse)

    async def test_via_cookie_path(self) -> None:
        with (
            patch.object(blv, "resolve_live_code", new=AsyncMock(return_value=None)),
            patch.object(blv, "get_current_user", new=AsyncMock(return_value={"user_id": "u1"})),
            patch.object(blv.registry, "session_owner", new=AsyncMock(return_value="u1")),
            patch.object(blv, "render_live_view_page", return_value="<html>"),
        ):
            req = _make_request()
            resp = await blv.live_view_page("sess1", req, t=None)
            assert isinstance(resp, HTMLResponse)

    async def test_invalid_token_raises_401(self) -> None:
        with (
            patch.object(blv, "resolve_live_code", new=AsyncMock(return_value=None)),
            patch.object(blv, "verify_takeover_token", side_effect=JWTError("bad")),
        ):
            req = _make_request()
            with pytest.raises(HTTPException) as exc:
                await blv.live_view_page("sess1", req, t="bad")
            assert exc.value.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_token_session_mismatch_raises_403(self) -> None:
        with (
            patch.object(blv, "resolve_live_code", new=AsyncMock(return_value=None)),
            patch.object(
                blv,
                "verify_takeover_token",
                return_value={"session_id": "other", "user_id": "u1", "exp": 9999999999.0},
            ),
        ):
            req = _make_request()
            with pytest.raises(HTTPException) as exc:
                await blv.live_view_page("sess1", req, t="tok")
            assert exc.value.status_code == status.HTTP_403_FORBIDDEN


# ---------------------------------------------------------------------------
# Router sanity
# ---------------------------------------------------------------------------


class TestRouter:
    def test_routes_exist(self) -> None:
        paths = {getattr(r, "path", None) for r in blv.router.routes}
        assert "/replays/{code}" in paths
        assert "/live/{code}" in paths

    def test_ws_route_exists(self) -> None:
        assert any(getattr(r, "path", None) == "/live/{code}" for r in blv.router.routes)


# ---------------------------------------------------------------------------
# Exact log calls, exception details, and seam call arguments — closes the
# remaining surviving mutants (string literals, dict keys, argument order).
# ---------------------------------------------------------------------------


class TestReplayPageDetails:
    async def test_not_found_detail_message(self) -> None:
        with patch.object(blv, "resolve_replay_code", new=AsyncMock(return_value=None)):
            with pytest.raises(HTTPException) as exc:
                await blv.replay_page("badcode")
            assert exc.value.detail == "Recap not found or expired"

    async def test_logs_operation_and_session_id_and_calls_resolve_with_code(self) -> None:
        record = ReplayRecord(session_id="s1", steps=1, shots=["https://cdn/1.png"])
        with (
            patch.object(
                blv, "resolve_replay_code", new=AsyncMock(return_value=record)
            ) as mock_resolve,
            patch.object(blv, "render_replay_page", return_value="<html>"),
            patch.object(blv, "log") as mock_log,
        ):
            await blv.replay_page("code123")
            mock_resolve.assert_called_once_with("code123")
            mock_log.set.assert_any_call(browser={"operation": "replay_page"})
            mock_log.set.assert_any_call(browser={"session_id": "s1"})
            mock_log.info.assert_called_once_with(
                f"{blv.LogTag.BROWSER} browser replay page served"
            )


class TestLiveViewPageDetails:
    async def test_forbidden_detail_message(self) -> None:
        with (
            patch.object(blv, "_resolve_target_page", new=AsyncMock(return_value=("sess1", "u1"))),
            patch.object(blv.registry, "session_owner", new=AsyncMock(return_value="other")),
        ):
            req = _make_request()
            with pytest.raises(HTTPException) as exc:
                await blv.live_view_page("code123", req, t=None)
            assert exc.value.detail == "Not authorized for this session"

    async def test_logs_operation_before_resolution(self) -> None:
        with (
            patch.object(blv, "_resolve_target_page", new=AsyncMock(return_value=("sess1", "u1"))),
            patch.object(blv.registry, "session_owner", new=AsyncMock(return_value=None)),
            patch.object(blv, "log") as mock_log,
        ):
            req = _make_request()
            with pytest.raises(HTTPException):
                await blv.live_view_page("code123", req, t=None)
            mock_log.set.assert_called_once_with(browser={"operation": "live_view_page"})

    async def test_success_renders_with_session_id_and_logs(self) -> None:
        with (
            patch.object(blv, "_resolve_target_page", new=AsyncMock(return_value=("sess1", "u1"))),
            patch.object(blv.registry, "session_owner", new=AsyncMock(return_value="u1")),
            patch.object(
                blv, "render_live_view_page", return_value="<html>live</html>"
            ) as mock_render,
            patch.object(blv, "log") as mock_log,
        ):
            req = _make_request()
            resp = await blv.live_view_page("code123", req, t=None)
            mock_render.assert_called_once_with("sess1")
            assert resp.body.decode() == "<html>live</html>"
            mock_log.set.assert_any_call(browser={"session_id": "sess1"})
            mock_log.info.assert_called_once_with(
                f"{blv.LogTag.BROWSER} browser live view page served"
            )

    async def test_owner_none_and_user_id_none_still_forbidden(self) -> None:
        # `owner is None` must short-circuit the `or` before `owner != user_id` is even
        # reached — pins the boundary against an `is None` -> `is not None` mutation,
        # which only differs from the original when owner and user_id are BOTH None
        # (otherwise `owner != user_id` alone still yields the same 403).
        with (
            patch.object(blv, "_resolve_target_page", new=AsyncMock(return_value=("sess1", None))),
            patch.object(blv.registry, "session_owner", new=AsyncMock(return_value=None)),
        ):
            req = _make_request()
            with pytest.raises(HTTPException) as exc:
                await blv.live_view_page("code123", req, t=None)
            assert exc.value.status_code == status.HTTP_403_FORBIDDEN


class TestResolveTargetPageArgs:
    async def test_authorize_page_called_with_exact_args(self) -> None:
        with (
            patch.object(blv, "resolve_live_code", new=AsyncMock(return_value=None)),
            patch.object(blv, "_authorize_page", new=AsyncMock(return_value="u2")) as mock_auth,
        ):
            req = _make_request()
            sid, uid = await blv._resolve_target_page("sess-raw", req, "tok")
            mock_auth.assert_called_once_with(req, "sess-raw", "tok")
            assert sid == "sess-raw"
            assert uid == "u2"

    async def test_record_found_short_circuits_authorize_page(self) -> None:
        # Pins `record is not None` -> `record is None`: with the mutant, a found
        # record would fall through and still call _authorize_page.
        rec = LiveCodeRecord(session_id="sess1", user_id="u1")
        with (
            patch.object(blv, "resolve_live_code", new=AsyncMock(return_value=rec)),
            patch.object(blv, "_authorize_page", new=AsyncMock()) as mock_auth,
        ):
            sid, uid = await blv._resolve_target_page("code123", _make_request(), "tok")
            assert sid == "sess1"
            assert uid == "u1"
            mock_auth.assert_not_called()

    async def test_resolve_live_code_called_with_exact_code(self) -> None:
        with patch.object(
            blv, "resolve_live_code", new=AsyncMock(return_value=None)
        ) as mock_resolve:
            with patch.object(blv, "_authorize_page", new=AsyncMock(return_value="u2")):
                await blv._resolve_target_page("sess-raw", _make_request(), "tok")
            mock_resolve.assert_called_once_with("sess-raw")


class TestAuthorizePageDetails:
    async def test_verify_scoped_token_called_with_exact_args(self) -> None:
        claims: dict[str, object] = {"session_id": "sess1", "user_id": "u1", "exp": 9999999999.0}
        with patch.object(blv, "_verify_scoped_token", return_value=claims) as mock_verify:
            await blv._authorize_page(_make_request(), "sess1", token="tok123")
            mock_verify.assert_called_once_with("tok123", "sess1")

    async def test_missing_user_id_detail_message(self) -> None:
        req = _make_request()
        with patch.object(blv, "get_current_user", new=AsyncMock(return_value={"user_id": None})):
            with pytest.raises(HTTPException) as exc:
                await blv._authorize_page(req, "sess1", token=None)
            assert exc.value.detail == "User id required"

    async def test_empty_string_user_id_raises_400(self) -> None:
        req = _make_request()
        with patch.object(blv, "get_current_user", new=AsyncMock(return_value={"user_id": ""})):
            with pytest.raises(HTTPException) as exc:
                await blv._authorize_page(req, "sess1", token=None)
            assert exc.value.status_code == status.HTTP_400_BAD_REQUEST

    async def test_non_string_user_id_converted_to_str(self) -> None:
        req = _make_request()
        with patch.object(blv, "get_current_user", new=AsyncMock(return_value={"user_id": 42})):
            uid = await blv._authorize_page(req, "sess1", token=None)
            assert uid == "42"
            assert isinstance(uid, str)

    async def test_empty_string_token_falls_through_to_cookie_path(self) -> None:
        # Pins `if token:` against an `if not token:` mutation: "" is falsy but not
        # None, so it must take the cookie path, not the token path.
        req = _make_request()
        with (
            patch.object(blv, "_verify_scoped_token") as mock_verify,
            patch.object(blv, "get_current_user", new=AsyncMock(return_value={"user_id": "u1"})),
        ):
            uid = await blv._authorize_page(req, "sess1", token="")
            assert uid == "u1"
            mock_verify.assert_not_called()


class TestVerifyScopedTokenDetails:
    async def test_invalid_token_detail_message(self) -> None:
        with patch.object(blv, "verify_takeover_token", side_effect=JWTError("bad")):
            with pytest.raises(HTTPException) as exc:
                blv._verify_scoped_token("bad", "sess1")
            assert exc.value.detail == "Invalid or expired link"

    async def test_mismatch_detail_message(self) -> None:
        claims: dict[str, object] = {"session_id": "other", "user_id": "u1", "exp": 9999999999.0}
        with patch.object(blv, "verify_takeover_token", return_value=claims):
            with pytest.raises(HTTPException) as exc:
                blv._verify_scoped_token("tok", "sess1")
            assert exc.value.detail == "Link does not match this session"

    def test_matching_session_returns_claims_unmodified(self) -> None:
        claims: dict[str, object] = {"session_id": "sess1", "user_id": "u1", "exp": 123.0}
        with patch.object(blv, "verify_takeover_token", return_value=claims):
            out = blv._verify_scoped_token("tok", "sess1")
            assert out == claims

    def test_verify_takeover_token_called_with_exact_token(self) -> None:
        claims: dict[str, object] = {"session_id": "sess1", "user_id": "u1", "exp": 123.0}
        with patch.object(blv, "verify_takeover_token", return_value=claims) as mock_verify:
            blv._verify_scoped_token("tok-abc", "sess1")
            mock_verify.assert_called_once_with("tok-abc")


class TestResolveTargetWsArgs:
    async def test_authorize_ws_called_with_exact_args(self) -> None:
        ws = _make_ws()
        with (
            patch.object(blv, "resolve_live_code", new=AsyncMock(return_value=None)),
            patch.object(
                blv, "_authorize_ws", new=AsyncMock(return_value=("u1", 100.0))
            ) as mock_auth,
        ):
            result = await blv._resolve_target_ws(ws, "sess-raw", "tok")
            mock_auth.assert_called_once_with(ws, "sess-raw", "tok")
            assert result == ("sess-raw", "u1", 100.0)

    async def test_record_found_short_circuits_authorize_ws(self) -> None:
        # Pins `record is not None` -> `record is None`: with the mutant, a found
        # record would fall through and still call _authorize_ws.
        rec = LiveCodeRecord(session_id="sess1", user_id="u1")
        with (
            patch.object(blv, "resolve_live_code", new=AsyncMock(return_value=rec)),
            patch.object(blv, "_authorize_ws", new=AsyncMock()) as mock_auth,
        ):
            result = await blv._resolve_target_ws(_make_ws(), "code123", "tok")
            assert result == ("sess1", "u1", None)
            mock_auth.assert_not_called()

    async def test_resolve_live_code_called_with_exact_code(self) -> None:
        with patch.object(
            blv, "resolve_live_code", new=AsyncMock(return_value=None)
        ) as mock_resolve:
            with patch.object(blv, "_authorize_ws", new=AsyncMock(return_value=("u1", 100.0))):
                await blv._resolve_target_ws(_make_ws(), "sess-raw", "tok")
            mock_resolve.assert_called_once_with("sess-raw")


class TestAuthorizeWsDetails:
    async def test_invalid_token_warns_with_message(self) -> None:
        with patch.object(blv, "verify_takeover_token", side_effect=JWTError("bad")):
            ws = _make_ws()
            with patch.object(blv, "log") as mock_log:
                await blv._authorize_ws(ws, "sess1", token="bad")
                mock_log.warning.assert_called_once_with(
                    f"{blv.LogTag.BROWSER} browser live view rejected invalid takeover token"
                )

    async def test_empty_string_token_falls_through_to_cookie_path(self) -> None:
        # Pins `if token:` against an `if not token:` mutation: "" is falsy but not
        # None, so it must take the cookie path, not the token path.
        ws = _make_ws()
        with (
            patch.object(blv, "verify_takeover_token") as mock_verify,
            patch.object(blv, "get_current_user_ws", new=AsyncMock(return_value={"user_id": "u1"})),
        ):
            result = await blv._authorize_ws(ws, "sess1", token="")
            assert result == ("u1", None)
            mock_verify.assert_not_called()

    async def test_verify_takeover_token_called_with_exact_token(self) -> None:
        claims: dict[str, object] = {"session_id": "sess1", "user_id": "u1", "exp": 9999999999.0}
        with (
            patch.object(blv, "verify_takeover_token", return_value=claims) as mock_verify,
            patch.object(blv, "takeover_token_ttl_seconds", return_value=100.0),
        ):
            ws = _make_ws()
            await blv._authorize_ws(ws, "sess1", token="tok-xyz")
            mock_verify.assert_called_once_with("tok-xyz")

    async def test_takeover_token_ttl_seconds_called_with_exact_claims(self) -> None:
        claims: dict[str, object] = {"session_id": "sess1", "user_id": "u1", "exp": 9999999999.0}
        with (
            patch.object(blv, "verify_takeover_token", return_value=claims),
            patch.object(blv, "takeover_token_ttl_seconds", return_value=100.0) as mock_ttl,
        ):
            ws = _make_ws()
            await blv._authorize_ws(ws, "sess1", token="tok")
            mock_ttl.assert_called_once_with(claims)

    async def test_get_current_user_ws_called_with_exact_websocket(self) -> None:
        ws = _make_ws()
        with patch.object(
            blv, "get_current_user_ws", new=AsyncMock(return_value={"user_id": "u1"})
        ) as mock_get_user:
            await blv._authorize_ws(ws, "sess1", token=None)
            mock_get_user.assert_called_once_with(ws)

    async def test_session_mismatch_warns_with_message(self) -> None:
        claims: dict[str, object] = {"session_id": "other", "user_id": "u1", "exp": 9999999999.0}
        with patch.object(blv, "verify_takeover_token", return_value=claims):
            ws = _make_ws()
            with patch.object(blv, "log") as mock_log:
                await blv._authorize_ws(ws, "sess1", token="tok")
                mock_log.warning.assert_called_once_with(
                    f"{blv.LogTag.BROWSER} browser live view token session mismatch"
                )

    async def test_cookie_non_string_user_id_converted_to_str(self) -> None:
        ws = _make_ws()
        with patch.object(blv, "get_current_user_ws", new=AsyncMock(return_value={"user_id": 7})):
            result = await blv._authorize_ws(ws, "sess1", token=None)
            assert result == ("7", None)


class TestLiveViewWsDetails:
    async def test_logs_operation_before_resolution(self) -> None:
        ws = _make_ws()
        with (
            patch.object(blv, "_resolve_target_ws", new=AsyncMock(return_value=None)),
            patch.object(blv, "log") as mock_log,
        ):
            await blv.live_view_ws(ws, "sess1", t="bad")
            mock_log.set.assert_called_once_with(browser={"operation": "live_view_ws"})

    async def test_ownership_denied_warns_with_exact_session_id(self) -> None:
        ws = _make_ws()
        with (
            patch.object(
                blv, "_resolve_target_ws", new=AsyncMock(return_value=("sess1", "u1", None))
            ),
            patch.object(blv.registry, "get_session_entry", new=AsyncMock(return_value=None)),
            patch.object(blv, "log") as mock_log,
        ):
            await blv.live_view_ws(ws, "sess1", t=None)
            mock_log.set.assert_any_call(browser={"session_id": "sess1"})
            mock_log.warning.assert_called_once_with(
                f"{blv.LogTag.BROWSER} browser live view ownership denied", session_id="sess1"
            )

    async def test_no_host_stream_warns_with_exact_session_id(self) -> None:
        ws = _make_ws()
        entry = SessionRegistryEntry(owner="u1", live_ws=None)
        with (
            patch.object(
                blv, "_resolve_target_ws", new=AsyncMock(return_value=("sess1", "u1", None))
            ),
            patch.object(blv.registry, "get_session_entry", new=AsyncMock(return_value=entry)),
            patch.object(blv, "log") as mock_log,
        ):
            await blv.live_view_ws(ws, "sess1", t=None)
            mock_log.warning.assert_called_once_with(
                f"{blv.LogTag.BROWSER} browser live view has no host stream", session_id="sess1"
            )

    async def test_success_logs_proxy_opened(self) -> None:
        ws = _make_ws()
        entry = SessionRegistryEntry(owner="u1", live_ws="ws://host/live/1")
        with (
            patch.object(
                blv, "_resolve_target_ws", new=AsyncMock(return_value=("sess1", "u1", None))
            ),
            patch.object(blv.registry, "get_session_entry", new=AsyncMock(return_value=entry)),
            patch.object(blv, "_proxy_live_view", new=AsyncMock()),
            patch.object(blv, "log") as mock_log,
        ):
            await blv.live_view_ws(ws, "sess1", t=None)
            mock_log.info.assert_called_once_with(
                f"{blv.LogTag.BROWSER} browser live view proxy opened"
            )

    async def test_resolve_target_ws_called_with_exact_args(self) -> None:
        ws = _make_ws()
        with patch.object(
            blv, "_resolve_target_ws", new=AsyncMock(return_value=None)
        ) as mock_resolve:
            await blv.live_view_ws(ws, "sess1", t="tok")
            mock_resolve.assert_called_once_with(ws, "sess1", "tok")

    async def test_get_session_entry_called_with_exact_session_id(self) -> None:
        ws = _make_ws()
        with (
            patch.object(
                blv, "_resolve_target_ws", new=AsyncMock(return_value=("sess1", "u1", None))
            ),
            patch.object(
                blv.registry, "get_session_entry", new=AsyncMock(return_value=None)
            ) as mock_get_entry,
        ):
            await blv.live_view_ws(ws, "code123", t=None)
            mock_get_entry.assert_called_once_with("sess1")


class TestProxyLiveViewDetails:
    async def test_pumps_called_with_correct_argument_order(self) -> None:
        client_ws = _make_ws()
        client_ws.close = AsyncMock()
        mock_host_ws = AsyncMock()
        mock_host_ws.__aenter__ = AsyncMock(return_value=mock_host_ws)
        mock_host_ws.__aexit__ = AsyncMock(return_value=False)
        with (
            patch.object(blv.websockets, "connect", return_value=mock_host_ws),
            patch.object(blv, "_pump_host_to_client", new=MagicMock()) as mock_h2c,
            patch.object(blv, "_pump_client_to_host", new=MagicMock()) as mock_c2h,
            patch.object(blv, "pump_until_first_close", new=AsyncMock()) as mock_pump,
        ):
            await blv._proxy_live_view(client_ws, "ws://host/live/1", None)
            mock_h2c.assert_called_once_with(mock_host_ws, client_ws)
            mock_c2h.assert_called_once_with(client_ws, mock_host_ws)
            assert mock_pump.call_args[0] == (
                mock_h2c.return_value,
                mock_c2h.return_value,
            )

    async def test_ttl_direction_appended_last(self) -> None:
        client_ws = _make_ws()
        client_ws.close = AsyncMock()
        mock_host_ws = AsyncMock()
        mock_host_ws.__aenter__ = AsyncMock(return_value=mock_host_ws)
        mock_host_ws.__aexit__ = AsyncMock(return_value=False)
        with (
            patch.object(blv.websockets, "connect", return_value=mock_host_ws),
            patch.object(blv, "_expire_after", new=MagicMock()) as mock_expire,
            patch.object(blv, "pump_until_first_close", new=AsyncMock()) as mock_pump,
        ):
            await blv._proxy_live_view(client_ws, "ws://host/live/1", 60.0)
            mock_expire.assert_called_once_with(60.0)
            assert len(mock_pump.call_args[0]) == 3
            assert mock_pump.call_args[0][2] is mock_expire.return_value

    async def test_host_unreachable_logs_exact_error_type(self) -> None:
        client_ws = _make_ws()
        client_ws.close = AsyncMock()
        with (
            patch.object(blv.websockets, "connect", side_effect=OSError("refused")),
            patch.object(blv, "log") as mock_log,
        ):
            await blv._proxy_live_view(client_ws, "ws://host/live/1", None)
            mock_log.warning.assert_called_once_with(
                f"{blv.LogTag.BROWSER} browser live view host unreachable", error_type="OSError"
            )

    async def test_host_unreachable_websocket_exception_logs_exact_error_type(self) -> None:
        client_ws = _make_ws()
        client_ws.close = AsyncMock()
        with (
            patch.object(
                blv.websockets,
                "connect",
                side_effect=websockets.exceptions.WebSocketException("boom"),
            ),
            patch.object(blv, "log") as mock_log,
        ):
            await blv._proxy_live_view(client_ws, "ws://host/live/1", None)
            mock_log.warning.assert_called_once_with(
                f"{blv.LogTag.BROWSER} browser live view host unreachable",
                error_type="WebSocketException",
            )

    async def test_logs_proxy_closed_on_success(self) -> None:
        client_ws = _make_ws()
        client_ws.close = AsyncMock()
        mock_host_ws = AsyncMock()
        mock_host_ws.__aenter__ = AsyncMock(return_value=mock_host_ws)
        mock_host_ws.__aexit__ = AsyncMock(return_value=False)
        with (
            patch.object(blv.websockets, "connect", return_value=mock_host_ws),
            patch.object(blv, "pump_until_first_close", new=AsyncMock()),
            patch.object(blv, "log") as mock_log,
        ):
            await blv._proxy_live_view(client_ws, "ws://host/live/1", None)
            mock_log.info.assert_called_once_with(
                f"{blv.LogTag.BROWSER} browser live view proxy closed"
            )
