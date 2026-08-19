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


def _make_request(cookies: dict[str, str] | None = None, headers: dict[str, str] | None = None) -> MagicMock:
    req = MagicMock(spec=Request)
    req.cookies = cookies or {}
    req.headers = headers or {}
    return req


def _make_ws(cookies: dict[str, str] | None = None, headers: dict[str, str] | None = None) -> MagicMock:
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
        record = ReplayRecord(session_id="s1", steps=2, shots=["https://cdn/1.png", "https://cdn/2.png"])
        with (
            patch.object(blv, "resolve_replay_code", new=AsyncMock(return_value=record)),
            patch.object(blv, "render_replay_page", return_value="<html>replay</html>") as mock_render,
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
        with patch.object(blv, "_verify_scoped_token", return_value=claims):  # type: ignore[return-value]
            uid = await blv._authorize_page(_make_request(), "sess1", token="tok123")
            assert uid == "u1"

    async def test_with_token_verifies_scoped(self) -> None:
        claims = {"session_id": "sess1", "user_id": "u1", "exp": 9999999999.0}
        with patch.object(blv, "verify_takeover_token", return_value=claims):  # type: ignore[return-value]
            out = blv._verify_scoped_token("tok", "sess1")
            assert out["user_id"] == "u1"

    async def test_verify_scoped_token_invalid_raises_401(self) -> None:
        with patch.object(blv, "verify_takeover_token", side_effect=JWTError("bad")):
            with pytest.raises(HTTPException) as exc:
                blv._verify_scoped_token("bad", "sess1")
            assert exc.value.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_verify_scoped_token_mismatch_raises_403(self) -> None:
        claims = {"session_id": "other", "user_id": "u1", "exp": 9999999999.0}
        with patch.object(blv, "verify_takeover_token", return_value=claims):  # type: ignore[return-value]
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
            patch.object(blv, "verify_takeover_token", return_value=claims),  # type: ignore[return-value]
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
            patch.object(blv, "verify_takeover_token", return_value=claims),  # type: ignore[return-value]
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
        with patch.object(blv, "verify_takeover_token", return_value=claims):  # type: ignore[return-value]
            ws = _make_ws()
            result = await blv._authorize_ws(ws, "sess1", token="tok")
            assert result is None
            ws.close.assert_awaited_once_with(code=status.WS_1008_POLICY_VIOLATION)

    async def test_cookie_success(self) -> None:
        ws = _make_ws()
        with patch.object(blv, "get_current_user_ws", new=AsyncMock(return_value={"user_id": "u1"})):
            result = await blv._authorize_ws(ws, "sess1", token=None)
            assert result is not None
            assert result[0] == "u1"
            assert result[1] is None

    async def test_cookie_missing_user_id_returns_none(self) -> None:
        ws = _make_ws()
        with patch.object(blv, "get_current_user_ws", new=AsyncMock(return_value={"user_id": None})):
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
            patch.object(blv, "_resolve_target_ws", new=AsyncMock(return_value=("sess1", "u1", None))),
            patch.object(blv.registry, "get_session_entry", new=AsyncMock(return_value=None)),
        ):
            await blv.live_view_ws(ws, "sess1", t=None)
            ws.close.assert_awaited_once_with(code=status.WS_1008_POLICY_VIOLATION)

    async def test_code_path_wrong_owner_closes_1008(self) -> None:
        ws = _make_ws()
        entry = SessionRegistryEntry(owner="other", live_ws="ws://host/live/1")
        with (
            patch.object(blv, "_resolve_target_ws", new=AsyncMock(return_value=("sess1", "u1", None))),
            patch.object(blv.registry, "get_session_entry", new=AsyncMock(return_value=entry)),
        ):
            await blv.live_view_ws(ws, "sess1", t=None)
            ws.close.assert_awaited_once_with(code=status.WS_1008_POLICY_VIOLATION)

    async def test_code_path_no_live_ws_closes_4404(self) -> None:
        ws = _make_ws()
        entry = SessionRegistryEntry(owner="u1", live_ws=None)
        with (
            patch.object(blv, "_resolve_target_ws", new=AsyncMock(return_value=("sess1", "u1", None))),
            patch.object(blv.registry, "get_session_entry", new=AsyncMock(return_value=entry)),
        ):
            await blv.live_view_ws(ws, "sess1", t=None)
            ws.close.assert_awaited_once_with(code=blv._WS_SESSION_GONE)

    async def test_code_path_success_proxies(self) -> None:
        ws = _make_ws()
        ws.accept = AsyncMock()
        entry = SessionRegistryEntry(owner="u1", live_ws="ws://host/live/1")
        with (
            patch.object(blv, "_resolve_target_ws", new=AsyncMock(return_value=("sess1", "u1", None))),
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
            patch.object(blv, "_resolve_target_ws", new=AsyncMock(return_value=("sess1", "u1", 42.0))),
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
            patch.object(blv, "_resolve_target_ws", new=AsyncMock(return_value=("sess1", "u1", None))),
            patch.object(blv.registry, "get_session_entry", new=AsyncMock(return_value=entry)),
        ):
            await blv.live_view_ws(ws, "sess1")
            ws.close.assert_awaited_once()
            assert ws.close.call_args[1]["code"] == 4404

    async def test_no_live_ws_empty_string_closes_4404(self) -> None:
        ws = _make_ws()
        entry = SessionRegistryEntry(owner="u1", live_ws="")
        with (
            patch.object(blv, "_resolve_target_ws", new=AsyncMock(return_value=("sess1", "u1", None))),
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
        with patch.object(blv.websockets, "connect", side_effect=websockets.exceptions.WebSocketException("boom")):
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

            def __aiter__(self):  # type: ignore[no-untyped-def]
                return self

            async def __anext__(self):  # type: ignore[no-untyped-def]
                if not self.msgs:
                    raise StopAsyncIteration
                return self.msgs.pop(0)

        host_ws = FakeHostWs([b"bytes-frame", "text-frame"])  # type: ignore[arg-type]
        client_ws = _make_ws()
        await blv._pump_host_to_client(host_ws, client_ws)  # type: ignore[arg-type]
        client_ws.send_bytes.assert_awaited_once_with(b"bytes-frame")
        client_ws.send_text.assert_awaited_once_with("text-frame")

    async def test_pump_host_to_client_empty(self) -> None:
        class EmptyHost:
            def __aiter__(self):  # type: ignore[no-untyped-def]
                return self

            async def __anext__(self):  # type: ignore[no-untyped-def]
                raise StopAsyncIteration

        host_ws = EmptyHost()
        client_ws = _make_ws()
        await blv._pump_host_to_client(host_ws, client_ws)  # type: ignore[arg-type]
        client_ws.send_bytes.assert_not_called()
        client_ws.send_text.assert_not_called()

    async def test_pump_client_to_host(self) -> None:
        client_ws = _make_ws()
        client_ws.receive_text = AsyncMock(side_effect=["hello", asyncio.CancelledError()])
        host_ws = MagicMock()
        host_ws.send = AsyncMock()
        with pytest.raises(asyncio.CancelledError):
            await blv._pump_client_to_host(client_ws, host_ws)  # type: ignore[arg-type]
        host_ws.send.assert_awaited_once_with("hello")

    async def test_pump_client_to_host_multiple(self) -> None:
        client_ws = _make_ws()
        client_ws.receive_text = AsyncMock(side_effect=["a", "b", asyncio.CancelledError()])
        host_ws = MagicMock()
        host_ws.send = AsyncMock()
        with pytest.raises(asyncio.CancelledError):
            await blv._pump_client_to_host(client_ws, host_ws)  # type: ignore[arg-type]
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
            patch.object(blv, "verify_takeover_token", return_value={"session_id": "sess1", "user_id": "u1", "exp": 9999999999.0}),  # type: ignore[return-value]
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
            patch.object(blv, "verify_takeover_token", return_value={"session_id": "other", "user_id": "u1", "exp": 9999999999.0}),  # type: ignore[return-value]
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
