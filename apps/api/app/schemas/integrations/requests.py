"""
Integration request models.

These models define the expected input for integration API endpoints.
Re-exported from the original location for backwards compatibility.
"""

import asyncio
import ipaddress
import socket
from typing import Literal, Optional
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator, model_validator

_BLOCKED_IP_ATTRS = (
    "is_private",
    "is_loopback",
    "is_link_local",
    "is_multicast",
    "is_reserved",
    "is_unspecified",
)


def _validate_mcp_server_url(url: str) -> str:
    """Sync structural checks for an MCP server URL.

    Validates the scheme/host/IP-literal aspects of the URL — anything that
    can be decided without DNS. The matching DNS-resolution check (which
    rejects hostnames whose A/AAAA records point at private/loopback IPs)
    lives in ``validate_mcp_server_url_dns`` and is invoked from the async
    route handler so we don't block the event loop on a slow nameserver.
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        raise ValueError("Invalid URL")

    if parsed.scheme not in ("http", "https"):
        raise ValueError("server_url must use http or https")
    if not parsed.hostname:
        raise ValueError("server_url is missing a host")

    host = parsed.hostname
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None

    if ip is not None and any(getattr(ip, attr) for attr in _BLOCKED_IP_ATTRS):
        raise ValueError("server_url resolves to a blocked IP address")

    return url


async def validate_mcp_server_url_dns(url: str) -> None:
    """Async DNS check: every A/AAAA record for the host must be public.

    Called from route handlers after the sync field validator has accepted
    the URL's structure. Uses the asyncio loop's resolver so a slow
    nameserver can't stall the worker event loop.
    """
    parsed = urlparse(url)
    host = parsed.hostname
    if not host:
        return

    # IP literals are already covered by the sync field validator.
    try:
        ipaddress.ip_address(host)
        return
    except ValueError:
        pass

    loop = asyncio.get_running_loop()
    try:
        addr_infos = await loop.getaddrinfo(host, None)
    except socket.gaierror:
        raise ValueError(f"server_url host '{host}' could not be resolved")

    for info in addr_infos:
        ip_str = info[4][0]
        try:
            resolved = ipaddress.ip_address(ip_str)
        except ValueError:
            raise ValueError("server_url resolved to an unparseable IP address")
        if any(getattr(resolved, attr) for attr in _BLOCKED_IP_ATTRS):
            raise ValueError("server_url resolves to a blocked IP address")


class AddUserIntegrationRequest(BaseModel):
    """Request to add an integration to user's workspace."""

    integration_id: str = Field(..., description="ID of integration to add")


class CreateCustomIntegrationRequest(BaseModel):
    """Request to create a custom MCP integration."""

    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(None, min_length=1, max_length=500)
    category: str = Field(default="custom")
    server_url: str = Field(..., description="MCP server URL")
    requires_auth: bool = Field(False)
    auth_type: Optional[Literal["none", "oauth", "bearer"]] = Field(None)
    is_public: bool = Field(False)
    bearer_token: Optional[str] = Field(None)

    @field_validator("server_url")
    @classmethod
    def server_url_must_be_public(cls, v: str) -> str:
        return _validate_mcp_server_url(v)

    @model_validator(mode="after")
    def validate_auth_type(self) -> "CreateCustomIntegrationRequest":
        if self.requires_auth and not self.auth_type:
            raise ValueError("auth_type must be specified when requires_auth is True")
        return self


class UpdateCustomIntegrationRequest(BaseModel):
    """Request to update a custom integration (partial update)."""

    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = Field(None, min_length=1, max_length=500)
    server_url: Optional[str] = None
    requires_auth: Optional[bool] = None
    auth_type: Optional[Literal["none", "oauth", "bearer"]] = None
    is_public: Optional[bool] = None

    @field_validator("server_url")
    @classmethod
    def server_url_must_be_public(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            return _validate_mcp_server_url(v)
        return v


class ConnectIntegrationRequest(BaseModel):
    """Request to connect an integration."""

    redirect_path: str = Field(
        default="/integrations",
        description="Frontend path to redirect after OAuth completes",
    )
    bearer_token: Optional[str] = Field(None)
