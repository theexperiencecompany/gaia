"""Unit tests for the /ws/connect WebSocket endpoint and its connection manager.

ASGITransport cannot run WebSocket handshakes, so the endpoint is exercised
directly with a mock WebSocket: the real handler logic (auth gate, subprotocol
accept, connection registration, disconnect/server-error cleanup) runs against
a stubbed transport. The manager's connection bookkeeping and both broadcast
paths are covered separately.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.websockets import WebSocketDisconnect

from app.api.v1.endpoints.websocket import websocket_endpoint
from app.core.websocket_manager import websocket_manager

USER_ID = "507f1f77bcf86cd799439011"


def _ws(protocol: str = "") -> MagicMock:
    """A stubbed WebSocket transport: headers dict, accept/close awaitables,
    and a receive_text that disconnects on its first read."""
    ws = MagicMock()
    ws.headers = {"sec-websocket-protocol": protocol}
    ws.accept = AsyncMock()
    ws.close = AsyncMock()
    ws.receive_text = AsyncMock(side_effect=WebSocketDisconnect())
    return ws


@pytest.fixture(autouse=True)
def _clean_connections():
    """The manager is a singleton shared across tests — start from an empty pool."""
    websocket_manager.connections.clear()
    yield
    websocket_manager.connections.clear()


# ---------------------------------------------------------------------------
# websocket_endpoint — auth gate
# ---------------------------------------------------------------------------


class TestWebsocketAuthGate:
    """/ws/connect — the invalid-user branch must never accept or register."""

    @patch("app.core.websocket_manager.websocket_manager.add_connection", new=MagicMock())
    async def test_missing_user_id_closes_without_accepting(self):
        ws = _ws()
        with patch(
            "app.api.v1.endpoints.websocket.get_current_user_ws",
            new=AsyncMock(return_value={}),
        ):
            await websocket_endpoint(ws)

        ws.accept.assert_not_awaited()
        websocket_manager.add_connection.assert_not_called()

    @patch("app.core.websocket_manager.websocket_manager.add_connection", new=MagicMock())
    async def test_non_string_user_id_closes_without_accepting(self):
        ws = _ws()
        with patch(
            "app.api.v1.endpoints.websocket.get_current_user_ws",
            new=AsyncMock(return_value={"user_id": 12345}),
        ):
            await websocket_endpoint(ws)

        ws.accept.assert_not_awaited()
        websocket_manager.add_connection.assert_not_called()


# ---------------------------------------------------------------------------
# websocket_endpoint — accept + registration
# ---------------------------------------------------------------------------


class TestWebsocketAccept:
    """/ws/connect — connection lifecycle for an authenticated user."""

    async def _run_handler(
        self, ws: MagicMock, user: dict, add: MagicMock, remove: MagicMock
    ) -> None:
        with (
            patch("app.core.websocket_manager.websocket_manager.add_connection", new=add),
            patch("app.core.websocket_manager.websocket_manager.remove_connection", new=remove),
            patch(
                "app.api.v1.endpoints.websocket.get_current_user_ws",
                new=AsyncMock(return_value=user),
            ),
        ):
            await websocket_endpoint(ws)

    async def test_cookie_auth_accepts_plain_and_registers(self):
        ws = _ws()
        add, remove = MagicMock(), MagicMock()
        await self._run_handler(ws, {"user_id": USER_ID}, add, remove)

        ws.accept.assert_awaited_once_with()
        add.assert_called_once_with(user_id=USER_ID, websocket=ws)

    async def test_subprotocol_auth_echoes_bearer_handshake(self):
        ws = _ws(protocol="Bearer, some.jwt.token")
        add, remove = MagicMock(), MagicMock()
        await self._run_handler(ws, {"user_id": USER_ID}, add, remove)

        ws.accept.assert_awaited_once_with(subprotocol="Bearer")
        add.assert_called_once()

    async def test_client_disconnect_removes_connection(self):
        ws = _ws()
        add, remove = MagicMock(), MagicMock()
        await self._run_handler(ws, {"user_id": USER_ID}, add, remove)

        remove.assert_called_once_with(user_id=USER_ID, websocket=ws)

    async def test_receive_loop_keeps_reading_until_disconnect(self):
        ws = _ws()
        ws.receive_text = AsyncMock(side_effect=["ping", "pong", WebSocketDisconnect()])
        add, remove = MagicMock(), MagicMock()
        await self._run_handler(ws, {"user_id": USER_ID}, add, remove)

        assert ws.receive_text.await_count == 3
        remove.assert_called_once()

    async def test_server_error_closes_with_1011_cleans_up_and_re_raises(self):
        ws = _ws()
        ws.receive_text = AsyncMock(side_effect=RuntimeError("boom"))
        add, remove = MagicMock(), MagicMock()
        with pytest.raises(RuntimeError, match="boom"):
            await self._run_handler(ws, {"user_id": USER_ID}, add, remove)

        remove.assert_called_once_with(user_id=USER_ID, websocket=ws)
        ws.close.assert_awaited_once_with(code=1011)


# ---------------------------------------------------------------------------
# WebSocketManager — connection bookkeeping
# ---------------------------------------------------------------------------


class TestConnectionBookkeeping:
    """WebSocketManager.add_connection / remove_connection"""

    def test_add_connection_groups_by_user(self):
        ws_a = MagicMock()
        ws_b = MagicMock()
        websocket_manager.add_connection("u1", ws_a)
        websocket_manager.add_connection("u1", ws_b)
        websocket_manager.add_connection("u2", ws_a)

        assert websocket_manager.connections["u1"] == {ws_a, ws_b}
        assert websocket_manager.connections["u2"] == {ws_a}

    def test_remove_connection_drops_only_that_socket(self):
        ws_a = MagicMock()
        ws_b = MagicMock()
        websocket_manager.add_connection("u1", ws_a)
        websocket_manager.add_connection("u1", ws_b)

        websocket_manager.remove_connection("u1", ws_a)

        assert websocket_manager.connections["u1"] == {ws_b}

    def test_remove_connection_deletes_empty_user_sets(self):
        ws = MagicMock()
        websocket_manager.add_connection("u1", ws)
        websocket_manager.remove_connection("u1", ws)
        assert "u1" not in websocket_manager.connections

    def test_remove_connection_for_unknown_user_is_a_no_op(self):
        websocket_manager.remove_connection("nobody", MagicMock())
        assert websocket_manager.connections == {}


# ---------------------------------------------------------------------------
# WebSocketManager — broadcast
# ---------------------------------------------------------------------------


class TestBroadcastToUser:
    """WebSocketManager.broadcast_to_user — direct and RabbitMQ paths"""

    @patch("app.core.websocket_manager.is_main_app", return_value=True)
    async def test_main_app_sends_to_every_connection(self, _mock_main):
        ws_a = MagicMock()
        ws_a.send_json = AsyncMock()
        ws_b = MagicMock()
        ws_b.send_json = AsyncMock()
        websocket_manager.add_connection("u1", ws_a)
        websocket_manager.add_connection("u1", ws_b)

        await websocket_manager.broadcast_to_user("u1", {"type": "update"})

        ws_a.send_json.assert_awaited_once_with({"type": "update"})
        ws_b.send_json.assert_awaited_once_with({"type": "update"})

    @patch("app.core.websocket_manager.is_main_app", return_value=True)
    async def test_main_app_drops_a_socket_that_fails_to_send(self, _mock_main):
        ok_ws = MagicMock()
        ok_ws.send_json = AsyncMock()
        dead_ws = MagicMock()
        dead_ws.send_json = AsyncMock(side_effect=RuntimeError("socket closed"))
        websocket_manager.add_connection("u1", ok_ws)
        websocket_manager.add_connection("u1", dead_ws)

        await websocket_manager.broadcast_to_user("u1", {"type": "update"})

        ok_ws.send_json.assert_awaited_once()
        assert websocket_manager.connections["u1"] == {ok_ws}

    @patch("app.core.websocket_manager.is_main_app", return_value=True)
    async def test_main_app_skips_users_without_connections(self, _mock_main):
        await websocket_manager.broadcast_to_user("nobody", {"type": "update"})
        assert websocket_manager.connections == {}

    @patch("app.core.websocket_manager.is_main_app", return_value=False)
    async def test_worker_publishes_to_rabbitmq_instead(self, _mock_main):
        publisher = MagicMock()
        publisher.publish = AsyncMock()
        with patch(
            "app.core.websocket_manager.get_rabbitmq_publisher",
            new=AsyncMock(return_value=publisher),
        ):
            await websocket_manager.broadcast_to_user("u1", {"type": "update"})

        args, kwargs = publisher.publish.await_args
        assert args[0] == "websocket-events"
        payload = json.loads(args[1].decode("utf-8"))
        assert payload == {
            "type": "websocket_broadcast",
            "user_id": "u1",
            "message": {"type": "update"},
        }
        assert kwargs == {}
