"""Coverage for app/api/v1/endpoints/browser_live_view.py.

Exercises every endpoint and helper with real function calls, mocking only
external services (Redis registry, takeover tokens, WebSockets, auth deps).
"""

from __future__ import annotations

import asyncio
from functools import partial
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI, HTTPException, WebSocket, status
from fastapi.responses import HTMLResponse
from httpx import ASGITransport, AsyncClient
from jose import JWTError
import pytest
from starlette.websockets import WebSocketState
from tests.helpers import captured_wide_event
import websockets

from app.api.v1.endpoints import browser_live_view as blv
from app.models.user_models import AuthenticatedUser
from app.schemas.browser import LiveCodeRecord, ReplayRecord
from app.services.browser.live_code import mint_live_code, revoke_handoff_live_code
from app.services.browser.registry import SessionRegistryEntry
from app.services.browser.shot_store import store_step_screenshot

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_ws(
    cookies: dict[str, str] | None = None, headers: dict[str, str] | None = None
) -> MagicMock:
    ws = MagicMock(spec=WebSocket)
    ws.cookies = cookies or {}
    ws.headers = headers or {}
    ws.client_state = WebSocketState.CONNECTED
    ws.application_state = WebSocketState.CONNECTED
    ws.close = AsyncMock()
    ws.accept = AsyncMock()
    ws.send_bytes = AsyncMock()
    ws.send_text = AsyncMock()
    ws.receive_text = AsyncMock()
    return ws


# ---------------------------------------------------------------------------
# step_screenshot — the Redis backend's serving half
# ---------------------------------------------------------------------------


@pytest.fixture
def shot_backend(monkeypatch: pytest.MonkeyPatch, fake_redis: object) -> None:
    """Run the real shot store against this test's own Redis."""
    monkeypatch.setattr(
        "app.services.browser.links.settings.BROWSER_LIVE_VIEW_BASE_URL", "https://browser.test"
    )


def _shots_app() -> FastAPI:
    app = FastAPI()
    app.include_router(blv.router)
    return app


@pytest.mark.usefixtures("shot_backend")
class TestStepScreenshot:
    async def test_a_frame_the_worker_stored_is_served_by_the_url_it_returned(self) -> None:
        url = await store_step_screenshot(b"\xff\xd8jpeg-payload", "sess-1", 2)
        assert url is not None

        transport = ASGITransport(app=_shots_app())
        async with AsyncClient(transport=transport, base_url="https://browser.test") as client:
            resp = await client.get(url.removeprefix("https://browser.test"))

        assert resp.status_code == 200
        assert resp.content == b"\xff\xd8jpeg-payload"
        assert resp.headers["content-type"] == "image/jpeg"

    @pytest.mark.parametrize("index", [1, 2])
    async def test_an_unknown_code_or_frame_is_404(self, index: int) -> None:
        url = await store_step_screenshot(b"jpeg", "sess-1", 1)
        assert url is not None
        code = url.split("/shots/")[1].split("/")[0] if index == 2 else "never-minted"

        async with captured_wide_event() as event:
            with pytest.raises(HTTPException) as exc:
                await blv.step_screenshot(code, index)
        assert (exc.value.status_code, exc.value.detail) == (
            status.HTTP_404_NOT_FOUND,
            "Screenshot not found or expired",
        )
        assert event["browser"]["operation"] == "step_screenshot"

    @pytest.mark.parametrize("index", ["..", "%2e%2e", "-", "1.jpg", "step_1"])
    async def test_a_non_integer_index_is_refused_by_the_route_itself(self, index: str) -> None:
        url = await store_step_screenshot(b"jpeg", "sess-1", 1)
        assert url is not None
        code = url.split("/shots/")[1].split("/")[0]

        transport = ASGITransport(app=_shots_app())
        async with AsyncClient(transport=transport, base_url="https://browser.test") as client:
            resp = await client.get(f"/shots/{code}/{index}.jpg")

        assert resp.status_code == 422


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
            blv, "get_current_user_ws", new=AsyncMock(return_value=AuthenticatedUser(user_id="u1"))
        ):
            result = await blv._authorize_ws(ws, "sess1", token=None)
            assert result is not None
            assert result[0] == "u1"
            assert result[1] is None


# ---------------------------------------------------------------------------
# _resolve_target_ws
# ---------------------------------------------------------------------------


class TestResolveTargetWs:
    async def test_via_code_ends_with_the_code(self) -> None:
        rec = LiveCodeRecord(session_id="sess1", user_id="u1")
        with patch.object(blv, "resolve_live_code", new=AsyncMock(return_value=rec)):
            result = await blv._resolve_target_ws(_make_ws(), "code123", None)
        assert result is not None
        session_id, user_id, ends = result
        assert (session_id, user_id) == ("sess1", "u1")
        assert isinstance(ends, partial)
        assert (ends.func, ends.args) == (blv.live_code_ended, ("code123",))

    async def test_via_token(self) -> None:
        with (
            patch.object(blv, "resolve_live_code", new=AsyncMock(return_value=None)),
            patch.object(blv, "_authorize_ws", new=AsyncMock(return_value=("u1", 100.0))),
        ):
            result = await blv._resolve_target_ws(_make_ws(), "sess1", "tok")
        assert result is not None
        session_id, user_id, ends = result
        assert (session_id, user_id) == ("sess1", "u1")
        assert isinstance(ends, partial)
        assert (ends.func, ends.args) == (blv._expire_after, (100.0,))

    async def test_via_cookie_has_no_end_of_its_own(self) -> None:
        with (
            patch.object(blv, "resolve_live_code", new=AsyncMock(return_value=None)),
            patch.object(blv, "_authorize_ws", new=AsyncMock(return_value=("u1", None))),
        ):
            result = await blv._resolve_target_ws(_make_ws(), "sess1", None)
        assert result == ("sess1", "u1", None)

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
            await blv._proxy_live_view(client_ws, "ws://host/live/1", MagicMock())
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

    async def test_a_viewer_that_already_left_is_not_closed_again(self) -> None:
        client_ws = _make_ws()
        client_ws.application_state = WebSocketState.DISCONNECTED
        mock_host_ws = AsyncMock()
        mock_host_ws.__aenter__ = AsyncMock(return_value=mock_host_ws)
        mock_host_ws.__aexit__ = AsyncMock(return_value=False)
        with (
            patch.object(blv.websockets, "connect", return_value=mock_host_ws),
            patch.object(blv, "pump_until_first_close", new=AsyncMock()) as pump,
        ):
            await blv._proxy_live_view(client_ws, "ws://host/live/1", None)

        client_ws.close.assert_not_awaited()
        assert pump.call_args.kwargs == {"sockets": (client_ws,)}


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
# Router sanity
# ---------------------------------------------------------------------------


class TestRouter:
    def test_routes_exist(self) -> None:
        paths = {getattr(r, "path", None) for r in blv.router.routes}
        assert "/replays/{code}" in paths
        assert "/live/{code}" in paths
        assert "/shots/{code}/{index}.jpg" in paths

    def test_ws_route_exists(self) -> None:
        assert any(getattr(r, "path", None) == "/live/{code}" for r in blv.router.routes)


# ---------------------------------------------------------------------------
# Exact log calls, exception details, and seam arguments: string literals,
# dict keys, argument order.


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
            assert result is not None
            assert result[:2] == ("sess-raw", "u1")

    async def test_record_found_short_circuits_authorize_ws(self) -> None:
        # Pins `record is not None` -> `record is None`: with the mutant, a found
        # record would fall through and still call _authorize_ws.
        rec = LiveCodeRecord(session_id="sess1", user_id="u1")
        with (
            patch.object(blv, "resolve_live_code", new=AsyncMock(return_value=rec)),
            patch.object(blv, "_authorize_ws", new=AsyncMock()) as mock_auth,
        ):
            result = await blv._resolve_target_ws(_make_ws(), "code123", "tok")
            assert result is not None
            assert result[:2] == ("sess1", "u1")
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
            patch.object(
                blv,
                "get_current_user_ws",
                new=AsyncMock(return_value=AuthenticatedUser(user_id="u1")),
            ),
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
            blv, "get_current_user_ws", new=AsyncMock(return_value=AuthenticatedUser(user_id="u1"))
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

    async def test_the_end_direction_is_appended_last(self) -> None:
        client_ws = _make_ws()
        client_ws.close = AsyncMock()
        mock_host_ws = AsyncMock()
        mock_host_ws.__aenter__ = AsyncMock(return_value=mock_host_ws)
        mock_host_ws.__aexit__ = AsyncMock(return_value=False)
        ends = MagicMock()
        with (
            patch.object(blv.websockets, "connect", return_value=mock_host_ws),
            patch.object(blv, "pump_until_first_close", new=AsyncMock()) as mock_pump,
        ):
            await blv._proxy_live_view(client_ws, "ws://host/live/1", ends)
            ends.assert_called_once_with()
            assert len(mock_pump.call_args[0]) == 3
            assert mock_pump.call_args[0][2] is ends.return_value

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


class _SilentHost:
    """A host live stream that stays open and sends nothing until it is closed."""

    def __init__(self) -> None:
        self._closed = asyncio.Event()

    async def __aenter__(self) -> _SilentHost:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        self._closed.set()

    def __aiter__(self) -> _SilentHost:
        return self

    async def __anext__(self) -> bytes:
        await self._closed.wait()
        raise StopAsyncIteration

    async def send(self, _message: str) -> None:
        return None


async def test_a_bot_link_socket_closes_the_moment_its_handoff_settles(
    fake_redis: object,
) -> None:
    """Settled, nobody is to watch or drive that browser any more, an open socket included."""
    code = await mint_live_code("sess1", "u1", "h1")
    viewer = _make_ws()

    async def _says_nothing() -> str:
        await asyncio.Event().wait()
        return ""

    viewer.receive_text = _says_nothing
    entry = SessionRegistryEntry(owner="u1", live_ws="ws://host/live/1")
    with (
        patch.object(blv.registry, "get_session_entry", new=AsyncMock(return_value=entry)),
        patch.object(blv.websockets, "connect", return_value=_SilentHost()),
    ):
        watching = asyncio.create_task(blv.live_view_ws(viewer, code, t=None))
        for _ in range(20):
            await asyncio.sleep(0)
        assert not watching.done()

        await revoke_handoff_live_code("h1")

        await asyncio.wait_for(watching, timeout=2)
    viewer.close.assert_awaited_once()
