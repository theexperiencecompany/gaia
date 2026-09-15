"""The always-live connected-device context.

Names the user's machines + servers so the agent routes local-file work to
the device instead of the cloud sandbox.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from tests.helpers import captured_wide_event

from app.agents.context import fetchers as mod


def _device(did: str, name: str, platform: str) -> SimpleNamespace:
    return SimpleNamespace(id=did, name=name, platform=platform)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_lists_each_device_with_its_servers():
    devices = [_device("d1", "MacBook", "macOS")]
    servers = {
        "d1": [
            SimpleNamespace(display_name="Local Files"),
            SimpleNamespace(display_name="Everything"),
        ]
    }
    list_devices = AsyncMock(return_value=devices)
    list_servers = AsyncMock(return_value=servers)
    with (
        patch.object(mod, "list_devices_service", list_devices),
        patch.object(mod, "list_device_servers", list_servers),
    ):
        out = await mod.build_connected_devices_manifest("u1", "HEADER:")

    # The manifest is looked up for THIS user and its servers keyed by device id;
    # asserting the args kills mutants that drop/alter them (the mocks ignore args).
    list_devices.assert_awaited_once_with("u1")
    list_servers.assert_awaited_once_with(["d1"])
    # Exact output: header first, then the device line with the id verbatim
    # (what run_on_device / the device tools take) and its exposed servers.
    assert out == "HEADER:\n- MacBook (macOS, id: d1) exposing: Local Files, Everything"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_device_with_no_servers_still_listed():
    with (
        patch.object(
            mod, "list_devices_service", AsyncMock(return_value=[_device("d1", "Box", "linux")])
        ),
        patch.object(mod, "list_device_servers", AsyncMock(return_value={})),
    ):
        out = await mod.build_connected_devices_manifest("u1", "HEADER:")
    assert out == "HEADER:\n- Box (linux, id: d1)"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_empty_when_no_devices():
    with patch.object(mod, "list_devices_service", AsyncMock(return_value=[])):
        out = await mod.build_connected_devices_manifest("u1", "HEADER:")
    assert out == ""


@pytest.mark.unit
@pytest.mark.asyncio
async def test_swallows_errors_to_empty_block():
    # A context section is enrichment; a lookup failure degrades to "" (byte-stable),
    # never fails the user's turn.
    with patch.object(mod, "list_devices_service", AsyncMock(side_effect=RuntimeError("boom"))):
        async with captured_wide_event() as event:
            out = await mod.build_connected_devices_manifest("u1", "HEADER:")
    assert out == ""
    # The swallow is not silent: the failure is surfaced on the wide event with the
    # real exception and the user it happened for — asserting these kills the
    # log.warning field mutants (message/error/error_type/user_id).
    (warning,) = event["warnings"]
    assert warning["msg"] == "Error building connected-devices manifest"
    assert warning["error"] == "boom"
    assert warning["error_type"] == "RuntimeError"
    assert warning["user_id"] == "u1"
