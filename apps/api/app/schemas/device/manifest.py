"""Schema for the per-user device manifest cached by ``device_service``."""

from pydantic import BaseModel


class DeviceManifestEntry(BaseModel):
    """One active device as the connected-devices context manifest renders it.

    Only the structural fields: name/platform/id plus the servers' display names.
    Online status and per-server sync state change constantly and are read live by
    the UI and the ``list_devices`` tool, so they are deliberately not cached here.
    """

    id: str
    name: str
    platform: str | None
    servers: list[str]
