"""The always-live connected-device context: names the user's machines + servers
so the agent routes local-file work to the device instead of the cloud sandbox."""

from unittest.mock import AsyncMock, patch

import pytest
from tests.helpers import captured_wide_event

from app.agents.context import fetchers as mod
from app.schemas.device.manifest import DeviceManifestEntry


def _entry(device_id: str, name: str, platform: str, servers: list[str]) -> DeviceManifestEntry:
    return DeviceManifestEntry(id=device_id, name=name, platform=platform, servers=servers)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_lists_each_device_with_its_servers():
    manifest = AsyncMock(
        return_value=[_entry("d1", "MacBook", "macOS", ["Local Files", "Everything"])]
    )
    with patch.object(mod, "get_device_manifest", manifest):
        out = await mod.build_connected_devices_manifest("u1", "HEADER:")

    # The manifest is looked up for THIS user; asserting the arg kills mutants
    # that drop/alter it (the mock ignores args).
    manifest.assert_awaited_once_with("u1")
    # Exact output: header first, then the device line with the id verbatim
    # (what run_on_device / the device tools take) and its exposed servers.
    assert out == "HEADER:\n- MacBook (macOS, id: d1) exposing: Local Files, Everything"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_device_with_no_servers_still_listed():
    with patch.object(
        mod, "get_device_manifest", AsyncMock(return_value=[_entry("d1", "Box", "linux", [])])
    ):
        out = await mod.build_connected_devices_manifest("u1", "HEADER:")
    assert out == "HEADER:\n- Box (linux, id: d1)"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_empty_when_no_devices():
    with patch.object(mod, "get_device_manifest", AsyncMock(return_value=[])):
        out = await mod.build_connected_devices_manifest("u1", "HEADER:")
    assert out == ""


@pytest.mark.unit
@pytest.mark.asyncio
async def test_swallows_errors_to_empty_block():
    # A context section is enrichment; a lookup failure degrades to "" (byte-stable),
    # never fails the user's turn.
    with patch.object(mod, "get_device_manifest", AsyncMock(side_effect=RuntimeError("boom"))):
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
