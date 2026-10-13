"""Typed shapes for the list_devices agent tool (LLM-facing, so ISO strings)."""

from typing import TypedDict


class DeviceServerInfo(TypedDict):
    server_key: str
    display_name: str
    integration_id: str
    kind: str
    status: str
    tools_synced_at: str | None


class DeviceInfo(TypedDict):
    id: str
    name: str
    platform: str | None
    online: bool
    last_seen_at: str | None
    servers: list[DeviceServerInfo]


class ListDevicesResult(TypedDict):
    devices: list[DeviceInfo]
