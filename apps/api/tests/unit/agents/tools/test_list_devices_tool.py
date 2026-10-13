"""Unit tests for the list_devices executor tool."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.agents.tools.integration_tool import list_devices
from tests.helpers import captured_wide_event

_MODULE = "app.agents.tools.integration_tool"
_CONFIG = {"configurable": {"user_id": "u1"}}


def _device(device_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=device_id,
        name="MacBook",
        platform="darwin",
        last_seen_at=datetime(2026, 9, 6, tzinfo=UTC),
    )


def _server(synced: bool) -> SimpleNamespace:
    return SimpleNamespace(
        server_key="github",
        display_name="GitHub",
        integration_id="int-gh",
        kind="stdio",
        status=SimpleNamespace(value="connected"),
        tools_synced_at=datetime(2026, 9, 6, tzinfo=UTC) if synced else None,
    )


async def _run(config=_CONFIG):
    return await list_devices.ainvoke({}, config=config)


async def test_lists_devices_with_online_and_server_mapping():
    dev_svc = AsyncMock(return_value=[_device("dev-1")])
    online = AsyncMock(return_value={"dev-1"})
    servers = AsyncMock(return_value={"dev-1": [_server(synced=True)]})
    with (
        patch(f"{_MODULE}.list_devices_service", dev_svc),
        patch(f"{_MODULE}.online_device_ids", online),
        patch(f"{_MODULE}.list_device_servers", servers),
    ):
        async with captured_wide_event() as event:
            result = await _run()

    assert event["tool"] == {"name": "list_devices", "action": "list"}
    # Devices are fetched for this user; online + server lookups key off the ids.
    dev_svc.assert_awaited_once_with("u1")
    online.assert_awaited_once_with(["dev-1"])
    servers.assert_awaited_once_with(["dev-1"])
    # The whole device row, including every server field, is rendered verbatim.
    assert result["devices"] == [
        {
            "id": "dev-1",
            "name": "MacBook",
            "platform": "darwin",
            "online": True,
            "last_seen_at": "2026-09-06T00:00:00+00:00",
            "servers": [
                {
                    "server_key": "github",
                    "display_name": "GitHub",
                    "integration_id": "int-gh",
                    "kind": "stdio",
                    "status": "connected",
                    "tools_synced_at": "2026-09-06T00:00:00+00:00",
                }
            ],
        }
    ]


async def test_offline_device_and_unsynced_server_render():
    with (
        patch(f"{_MODULE}.list_devices_service", AsyncMock(return_value=[_device("dev-1")])),
        patch(f"{_MODULE}.online_device_ids", AsyncMock(return_value=set())),
        patch(
            f"{_MODULE}.list_device_servers",
            AsyncMock(return_value={"dev-1": [_server(synced=False)]}),
        ),
    ):
        result = await _run()

    device = result["devices"][0]
    # A device absent from the online set is offline, and a never-synced server
    # surfaces null tools_synced_at so the agent can warn the user.
    assert device["online"] is False
    assert device["last_seen_at"] == "2026-09-06T00:00:00+00:00"
    assert device["servers"][0]["tools_synced_at"] is None


async def test_device_with_no_last_seen_renders_null():
    dev = _device("dev-1")
    dev.last_seen_at = None
    with (
        patch(f"{_MODULE}.list_devices_service", AsyncMock(return_value=[dev])),
        patch(f"{_MODULE}.online_device_ids", AsyncMock(return_value=set())),
        patch(f"{_MODULE}.list_device_servers", AsyncMock(return_value={})),
    ):
        result = await _run()

    # No last_seen and no server entry for the device — both defaults hold: a
    # null timestamp and an empty (not None) server list.
    assert result["devices"][0]["last_seen_at"] is None
    assert result["devices"][0]["servers"] == []


async def test_missing_user_id_fails_loud():
    result = await _run(config={"configurable": {}})
    assert result == "Error: User ID not found in configuration."


async def test_underlying_failure_is_reported_and_logged():
    with patch(f"{_MODULE}.list_devices_service", AsyncMock(side_effect=RuntimeError("db down"))):
        async with captured_wide_event() as event:
            result = await _run()

    assert result == "Error listing devices: db down"
    (error,) = event["errors"]
    assert "Error listing devices" in error["msg"]
    assert error["error_type"] == "RuntimeError"
