"""
Integration request models.

These models define the expected input for integration API endpoints.
Re-exported from the original location for backwards compatibility.
"""

import ipaddress
import socket
from typing import Literal, Optional
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator, model_validator


def _validate_mcp_server_url(url: str) -> str:
    """Raise ValueError if ``url`` is not a safe public https/http MCP server URL.

    Mirrors the SSRF hardening in internet_utils._validate_external_url but raises
    ValueError so it works inside Pydantic field validators.
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

    _blocked = (
        "is_private",
        "is_loopback",
        "is_link_local",
        "is_multicast",
        "is_reserved",
        "is_unspecified",
    )

    if ip is not None:
        if any(getattr(ip, attr) for attr in _blocked):
            raise ValueError("server_url resolves to a blocked IP address")
        return url

    try:
        addr_infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        raise ValueError(f"server_url host '{host}' could not be resolved")

    for info in addr_infos:
        ip_str = info[4][0]
        try:
            resolved = ipaddress.ip_address(ip_str)
        except ValueError:
            raise ValueError("server_url resolved to an unparseable IP address")
        if any(getattr(resolved, attr) for attr in _blocked):
            raise ValueError("server_url resolves to a blocked IP address")

    return url


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
