"""Request schemas for the device bridge (pairing, token exchange, servers)."""

from pydantic import BaseModel, Field


class StartPairingRequest(BaseModel):
    """Daemon kicks off pairing, announcing itself (RFC 8628 device flow)."""

    name: str = Field(min_length=1, max_length=120, description="Human label for this device")
    platform: str | None = Field(default=None, max_length=60)
    daemon_version: str | None = Field(default=None, max_length=40)


class PollPairingRequest(BaseModel):
    """Daemon polls for the user's browser approval."""

    device_code: str = Field(min_length=1)


class ApprovePairingRequest(BaseModel):
    """The signed-in browser approves a pairing by its short user_code."""

    user_code: str = Field(min_length=1, max_length=32)


class DeviceTokenRequest(BaseModel):
    """Daemon exchanges its refresh credential for a short-lived connect JWT."""

    refresh_token: str = Field(min_length=1)


class RegisterServerRequest(BaseModel):
    """Daemon registers (or re-registers) one exposed MCP server for this device.

    Authenticated by the device connect JWT, not a user session — the daemon owns
    the list of servers it exposes. ``server_key`` is stable per device.
    """

    server_key: str = Field(min_length=1, max_length=120, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    display_name: str = Field(min_length=1, max_length=120)
