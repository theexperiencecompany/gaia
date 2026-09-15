"""The device tunnel is a WebSocket, so the HTTP paywall middleware never sees it.

The daemon's connect JWT outlives a subscription and the daemon reconnects on
its own, so without a connect-time check a lapsed user's machine keeps relaying
MCP traffic forever. Closing with 1008 (policy violation) matches how the same
handler already rejects a revoked device.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.v1.endpoints.device_ws import device_ws
from app.models.payment_models import PlanType

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
        patch(f"{MODULE}.is_paid", new_callable=AsyncMock, return_value=False),
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
        patch(f"{MODULE}.is_paid", new_callable=AsyncMock, return_value=False),
        patch(f"{MODULE}.device_connection_manager") as manager,
        patch(f"{MODULE}.mark_online", new_callable=AsyncMock) as mark_online,
    ):
        await device_ws(websocket)

    manager.add.assert_not_called()
    mark_online.assert_not_awaited()


async def test_the_close_is_attributed_to_the_paywall_in_the_wide_event() -> None:
    """The reason string is the only way a support ticket ("my daemon keeps
    dropping") is told apart from a revoke or a bad token in Loki, so it is a
    queried value, not narration — asserted exactly."""
    websocket = _socket()
    with (
        patch(f"{MODULE}.verify_device_token", return_value=TOKEN_INFO),
        patch(f"{MODULE}.get_active_device", new_callable=AsyncMock, return_value={"id": "dev-1"}),
        patch(f"{MODULE}.is_paid", new_callable=AsyncMock, return_value=False),
        patch(f"{MODULE}.log") as mock_log,
    ):
        await device_ws(websocket)

    mock_log.set.assert_any_call(disconnect_reason="subscription_required")


async def test_gate_asks_about_the_tokens_own_user() -> None:
    websocket = _socket()
    is_active = AsyncMock(return_value=False)
    with (
        patch(f"{MODULE}.verify_device_token", return_value=TOKEN_INFO),
        patch(f"{MODULE}.get_active_device", new_callable=AsyncMock, return_value={"id": "dev-1"}),
        patch(f"{MODULE}.is_paid", is_active),
    ):
        await device_ws(websocket)

    is_active.assert_awaited_once_with("user-1")


async def test_a_user_who_just_paid_connects_off_the_row_not_the_stale_cache() -> None:
    """The daemon dials the moment the user pays; the cache can still say
    FREE for five minutes. Reading it alone closed a paying user's tunnel
    with the paywall code on every reconnect until the TTL ran out."""
    websocket = _socket()
    with (
        patch(f"{MODULE}.verify_device_token", return_value=TOKEN_INFO),
        patch(f"{MODULE}.get_active_device", new_callable=AsyncMock, return_value={"id": "dev-1"}),
        patch(
            "app.decorators.entitlements.payment_service.get_cached_plan_type",
            new_callable=AsyncMock,
            return_value=PlanType.FREE,
        ),
        patch(
            "app.decorators.entitlements.payment_service.get_user_subscription_status",
            new_callable=AsyncMock,
            return_value=MagicMock(plan_type=PlanType.PRO),
        ),
        patch("app.decorators.entitlements.invalidate_plan_cache", new_callable=AsyncMock),
        patch(f"{MODULE}.device_connection_manager"),
        patch(f"{MODULE}.mark_online", new_callable=AsyncMock),
        patch(f"{MODULE}.mark_offline", new_callable=AsyncMock),
        patch(f"{MODULE}._down_relay", new_callable=AsyncMock),
        patch(f"{MODULE}._heartbeat", new_callable=AsyncMock),
        patch(f"{MODULE}._receive_loop", new_callable=AsyncMock),
    ):
        await device_ws(websocket)

    websocket.accept.assert_awaited_once()
    assert all(call.kwargs.get("code") != 1008 for call in websocket.close.await_args_list)
