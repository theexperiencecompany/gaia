"""Response schemas for the device bridge."""

from datetime import datetime

from pydantic import BaseModel


class StartPairingResponse(BaseModel):
    """Returned to the daemon after it starts pairing."""

    device_code: str
    user_code: str
    verification_url: str
    expires_in: int
    interval: int


class PollPairingResponse(BaseModel):
    """Result of a pairing poll.

    ``status`` is ``pending`` (keep polling), ``approved`` (``refresh_token`` set),
    or ``denied`` / ``expired`` (stop).
    """

    status: str
    device_id: str | None = None
    refresh_token: str | None = None


class DeviceTokenResponse(BaseModel):
    """Short-lived connect JWT plus the rotated refresh credential."""

    access_token: str
    token_type: str = "Bearer"  # noqa: S105 - token type label, not a secret
    expires_in: int
    refresh_token: str


class DeviceServerResponse(BaseModel):
    """One MCP server a device exposes, as shown in the device list."""

    server_key: str
    display_name: str
    integration_id: str
    status: str
    tools_synced_at: datetime | None = None


class DeviceResponse(BaseModel):
    """A paired device with its status and exposed servers."""

    id: str
    name: str
    platform: str | None
    daemon_version: str | None
    status: str
    online: bool
    last_seen_at: datetime | None
    created_at: datetime
    servers: list[DeviceServerResponse]


class DeviceListResponse(BaseModel):
    """The user's paired devices."""

    devices: list[DeviceResponse]


class RegisterServerResponse(BaseModel):
    """Result of registering a device's MCP server."""

    integration_id: str
    server_key: str
