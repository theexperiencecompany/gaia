"""Unit tests for warm_device_servers.

The warm-connect that makes a device's MCP tools discoverable after registration.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.workers.tasks.device_tasks import warm_device_servers
from tests.helpers import captured_wide_event

_MODULE = "app.workers.tasks.device_tasks"


def _server(integration_id: str, server_key: str) -> SimpleNamespace:
    return SimpleNamespace(integration_id=integration_id, server_key=server_key)


@pytest.mark.asyncio
async def test_warms_each_server_and_records_success():
    device = SimpleNamespace(user_id="u1")
    client = AsyncMock()
    client.ensure_connected = AsyncMock(return_value=["t1", "t2"])
    with (
        patch(f"{_MODULE}.get_active_device", AsyncMock(return_value=device)) as active,
        patch(
            f"{_MODULE}.list_device_servers",
            AsyncMock(return_value={"dev": [_server("int-a", "a"), _server("int-b", "b")]}),
        ) as listed,
        patch(f"{_MODULE}.get_mcp_client", AsyncMock(return_value=client)) as get_client,
        patch(f"{_MODULE}.record_device_server_sync", new=AsyncMock()) as record,
    ):
        async with captured_wide_event() as event:
            result = await warm_device_servers({}, "dev")

    assert result == "warmed=2 failed=0"
    # The right device is looked up, its servers listed, and the client fetched
    # for that device's owner — not some other id.
    active.assert_awaited_once_with("dev")
    listed.assert_awaited_once_with(["dev"])
    get_client.assert_awaited_once_with("u1")
    # Each server is connected by its own integration_id, in order.
    assert [c.args[0] for c in client.ensure_connected.await_args_list] == ["int-a", "int-b"]
    recorded = {c.args[0]: c.kwargs["error"] for c in record.await_args_list}
    assert recorded == {"int-a": None, "int-b": None}
    assert event["device"] == {"operation": "warm_servers", "device_id": "dev"}
    assert event["warmed"] == 2
    assert event["failed"] == 0


@pytest.mark.asyncio
async def test_one_server_failing_records_the_error_and_warns_but_continues():
    device = SimpleNamespace(user_id="u1")
    client = AsyncMock()
    client.ensure_connected = AsyncMock(side_effect=[RuntimeError("boom"), ["t1"]])
    with (
        patch(f"{_MODULE}.get_active_device", AsyncMock(return_value=device)),
        patch(
            f"{_MODULE}.list_device_servers",
            AsyncMock(return_value={"dev": [_server("int-bad", "bad"), _server("int-ok", "ok")]}),
        ),
        patch(f"{_MODULE}.get_mcp_client", AsyncMock(return_value=client)),
        patch(f"{_MODULE}.record_device_server_sync", new=AsyncMock()) as record,
    ):
        async with captured_wide_event() as event:
            result = await warm_device_servers({}, "dev")

    assert result == "warmed=1 failed=1"
    recorded = {c.args[0]: c.kwargs["error"] for c in record.await_args_list}
    assert recorded["int-ok"] is None
    # The recorded error carries the real exception type, not a generic label.
    assert recorded["int-bad"] == "RuntimeError: boom"
    # The failure is surfaced on the wide event with the offending server's
    # identity — a swallowed warm-connect must not be silent.
    (warning,) = event["warnings"]
    assert "warm-connect failed" in warning["msg"]
    assert warning["device_id"] == "dev"
    assert warning["server_key"] == "bad"
    assert warning["error"] == "boom"
    assert warning["error_type"] == "RuntimeError"
    assert event["warmed"] == 1
    assert event["failed"] == 1


@pytest.mark.asyncio
async def test_every_server_failing_counts_each_failure():
    # Two failures must count as failed=2, not failed=1 — the counter accumulates.
    device = SimpleNamespace(user_id="u1")
    client = AsyncMock()
    client.ensure_connected = AsyncMock(side_effect=[RuntimeError("x"), RuntimeError("y")])
    with (
        patch(f"{_MODULE}.get_active_device", AsyncMock(return_value=device)),
        patch(
            f"{_MODULE}.list_device_servers",
            AsyncMock(return_value={"dev": [_server("int-1", "a"), _server("int-2", "b")]}),
        ),
        patch(f"{_MODULE}.get_mcp_client", AsyncMock(return_value=client)),
        patch(f"{_MODULE}.record_device_server_sync", new=AsyncMock()),
    ):
        result = await warm_device_servers({}, "dev")

    assert result == "warmed=0 failed=2"


@pytest.mark.asyncio
async def test_inactive_device_is_a_noop():
    with patch(f"{_MODULE}.get_active_device", AsyncMock(return_value=None)):
        result = await warm_device_servers({}, "dev")
    assert result == "device inactive"


@pytest.mark.asyncio
async def test_device_with_no_registered_servers_warms_nothing():
    # list_device_servers has no entry for this device — the default must be an
    # empty list, not None (which would blow up the iteration).
    device = SimpleNamespace(user_id="u1")
    with (
        patch(f"{_MODULE}.get_active_device", AsyncMock(return_value=device)),
        patch(f"{_MODULE}.list_device_servers", AsyncMock(return_value={})),
        patch(f"{_MODULE}.get_mcp_client", AsyncMock(return_value=AsyncMock())),
        patch(f"{_MODULE}.record_device_server_sync", new=AsyncMock()),
    ):
        result = await warm_device_servers({}, "dev")

    assert result == "warmed=0 failed=0"


@pytest.mark.asyncio
async def test_server_keys_filter_limits_the_warmup():
    device = SimpleNamespace(user_id="u1")
    client = AsyncMock()
    client.ensure_connected = AsyncMock(return_value=[])
    with (
        patch(f"{_MODULE}.get_active_device", AsyncMock(return_value=device)),
        patch(
            f"{_MODULE}.list_device_servers",
            AsyncMock(return_value={"dev": [_server("int-a", "a"), _server("int-b", "b")]}),
        ),
        patch(f"{_MODULE}.get_mcp_client", AsyncMock(return_value=client)),
        patch(f"{_MODULE}.record_device_server_sync", new=AsyncMock()) as record,
    ):
        await warm_device_servers({}, "dev", ["b"])

    recorded = [c.args[0] for c in record.await_args_list]
    assert recorded == ["int-b"]


@pytest.mark.asyncio
async def test_servers_warm_concurrently_not_serially():
    # A's connect blocks until B's connect has STARTED: only overlapping
    # execution lets both succeed. A serial loop would time A out and report
    # warmed=1 failed=1.
    b_started = asyncio.Event()

    async def connect(integration_id: str):
        if integration_id == "int-a":
            await asyncio.wait_for(b_started.wait(), 5)
        else:
            b_started.set()
        return []

    device = SimpleNamespace(user_id="u1")
    client = AsyncMock()
    client.ensure_connected = AsyncMock(side_effect=connect)
    with (
        patch(f"{_MODULE}.get_active_device", AsyncMock(return_value=device)),
        patch(
            f"{_MODULE}.list_device_servers",
            AsyncMock(return_value={"dev": [_server("int-a", "a"), _server("int-b", "b")]}),
        ),
        patch(f"{_MODULE}.get_mcp_client", AsyncMock(return_value=client)),
        patch(f"{_MODULE}.record_device_server_sync", new=AsyncMock()),
    ):
        result = await warm_device_servers({}, "dev")

    assert result == "warmed=2 failed=0"
