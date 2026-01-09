"""
Integration request models.

These models define the expected input for integration API endpoints.
Re-exported from the original location for backwards compatibility.
"""

from typing import Literal, Optional

from pydantic import BaseModel, Field


class AddUserIntegrationRequest(BaseModel):
    """Request to add an integration to user's workspace."""

    integration_id: str = Field(..., description="ID of integration to add")


class CreateCustomIntegrationRequest(BaseModel):
    """Request to create a custom MCP integration."""

    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    category: str = Field(default="custom")
    server_url: str = Field(..., description="MCP server URL")
    requires_auth: bool = Field(False)
    auth_type: Optional[Literal["none", "oauth", "bearer"]] = Field(None)
    is_public: bool = Field(False, description="Make visible in marketplace")


class UpdateCustomIntegrationRequest(BaseModel):
    """Request to update a custom integration (partial update)."""

    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = Field(None, min_length=1, max_length=500)
    server_url: Optional[str] = None
    requires_auth: Optional[bool] = None
    auth_type: Optional[Literal["none", "oauth", "bearer"]] = None
    is_public: Optional[bool] = None


class ConnectIntegrationRequest(BaseModel):
    """Request to connect an integration."""

    redirect_path: str = Field(
        default="/integrations",
        description="Frontend path to redirect after OAuth completes",
    )
