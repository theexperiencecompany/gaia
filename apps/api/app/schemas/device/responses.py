"""Response schemas for the device bridge."""

from datetime import datetime
from typing import Literal, TypedDict

from pydantic import BaseModel

from app.schemas.common import ResponseModel


class StartPairingResponse(ResponseModel):
    """Returned to the daemon after it starts pairing."""

    device_code: str
    user_code: str
    verification_url: str
    expires_in: int
    interval: int


class PollPairingResponse(ResponseModel):
    """Result of a pairing poll.

    ``status`` is ``pending`` (keep polling), ``approved`` (``device_id`` and
    ``refresh_token`` set) or ``expired`` (stop).
    """

    status: Literal["pending", "approved", "expired"]
    device_id: str | None = None
    refresh_token: str | None = None


class DeviceTokenResponse(ResponseModel):
    """Short-lived connect JWT plus the rotated refresh credential."""

    access_token: str
    token_type: str = "Bearer"
    expires_in: int
    refresh_token: str


class DeviceServerResponse(BaseModel):
    """One MCP server a device exposes, as shown in the device list."""

    server_key: str
    display_name: str
    integration_id: str
    kind: str = "stdio"
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


class DeregisterServerResponse(BaseModel):
    """Result of the daemon deregistering one of its MCP servers."""

    server_key: str
    removed: bool


class DevicePairApproveResponse(BaseModel):
    """Result of approving a pending device pairing."""

    device_id: str
    name: str


class SelfPairResponse(BaseModel):
    """Result of a one-call self-pair: the device plus its refresh credential.

    Mirrors the approve response but also returns ``refresh_token`` inline, since
    the caller that pairs is the same host that stores the credential.
    """

    device_id: str
    refresh_token: str
    name: str


class DeviceRevokeResponse(BaseModel):
    """Result of revoking a device's access."""

    device_id: str
    status: str


class DeviceTokenClaims(TypedDict):
    """Claims carried by a device connect JWT.

    A TypedDict, not a model: the dependency and its consumers read these as
    ``info["device_id"]``, so dict semantics are preserved while mypy checks the
    keys.
    """

    device_id: str
    user_id: str
