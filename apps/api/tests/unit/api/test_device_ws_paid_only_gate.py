"""The device tunnel is a WebSocket, so the HTTP paywall middleware never sees it.

The daemon's connect JWT outlives a subscription and the daemon reconnects on
its own, so without a connect-time check a lapsed user's machine keeps relaying
MCP traffic forever. Closing with 1008 (policy violation) matches how the same
handler already rejects a revoked device.
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.api.v1.endpoints.device_ws import device_ws

pytestmark = pytest.mark.unit

MODULE = "app.api.v1.endpoints.device_ws"
TOKEN_INFO = {"device_id": "dev-1", "user_id": "user-1"}


def _socket() -> AsyncMock:
    websocket = AsyncMock()
    websocket.headers = {"authorization": "Bearer device-jwt"}
    return websocket


async def test_free_user_socket_is_closed_with_policy_violation() -> None:
    websocket = _socket()
    with (
        patch(f"{MODULE}.verify_device_token", return_value=TOKEN_INFO),
        patch(f"{MODULE}.get_active_device", new_callable=AsyncMock, return_value={"id": "dev-1"}),
        patch(f"{MODULE}.is_subscription_active", new_callable=AsyncMock, return_value=False),
    ):
        await device_ws(websocket)

    websocket.close.assert_awaited_once_with(code=1008)
    websocket.accept.assert_not_awaited()


async def test_gate_runs_before_the_socket_is_accepted() -> None:
    """Accepting first would let a frame through before the check completed."""
    websocket = _socket()
    with (
        patch(f"{MODULE}.verify_device_token", return_value=TOKEN_INFO),
        patch(f"{MODULE}.get_active_device", new_callable=AsyncMock, return_value={"id": "dev-1"}),
        patch(f"{MODULE}.is_subscription_active", new_callable=AsyncMock, return_value=False),
        patch(f"{MODULE}.device_connection_manager") as manager,
        patch(f"{MODULE}.mark_online", new_callable=AsyncMock) as mark_online,
    ):
        await device_ws(websocket)

    manager.add.assert_not_called()
    mark_online.assert_not_awaited()


async def test_gate_asks_about_the_tokens_own_user() -> None:
    websocket = _socket()
    is_active = AsyncMock(return_value=False)
    with (
        patch(f"{MODULE}.verify_device_token", return_value=TOKEN_INFO),
        patch(f"{MODULE}.get_active_device", new_callable=AsyncMock, return_value={"id": "dev-1"}),
        patch(f"{MODULE}.is_subscription_active", is_active),
    ):
        await device_ws(websocket)

    is_active.assert_awaited_once_with("user-1")
