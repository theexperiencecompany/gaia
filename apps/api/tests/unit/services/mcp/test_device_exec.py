"""run_device_command: how a command on a paired device ends from the cloud's side."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.constants import device_bridge
from app.services.mcp.device_exec import DeviceExecError, run_device_command

_MODULE = "app.services.mcp.device_exec"


@pytest.mark.regression
async def test_a_command_fails_at_once_when_its_device_socket_closes() -> None:
    """Regression for #1144: a dropped socket left run_on_device waiting out its 105s timeout."""
    inbox: asyncio.Queue[dict[str, object]] = asyncio.Queue()
    inbox.put_nowait({"t": device_bridge.FRAME_TUNNEL_CLOSED})
    with (
        patch(f"{_MODULE}.redis_cache", MagicMock()),
        patch(f"{_MODULE}.is_online", AsyncMock(return_value=True)),
        patch(f"{_MODULE}.send_down", AsyncMock()),
        patch(f"{_MODULE}.register_up_session", MagicMock(return_value=inbox)),
        pytest.raises(DeviceExecError) as failed,
    ):
        await asyncio.wait_for(run_device_command("dev-1", "sleep 30"), timeout=2.0)

    assert str(failed.value) == device_bridge.DEVICE_DISCONNECTED_MESSAGE
