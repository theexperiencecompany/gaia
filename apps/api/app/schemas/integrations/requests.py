"""
Integration request models.

These models define the expected input for integration API endpoints.
Re-exported from the original location for backwards compatibility.
"""

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class AddUserIntegrationRequest(BaseModel):
    """Request to add an integration to user's workspace."""

    integration_id: str = Field(..., description="ID of integration to add")


class CreateCustomIntegrationRequest(BaseModel):
    """Request to create a custom MCP integration."""

    name: str = Field(..., min_length=1, max_length=100)
    description: str | None = Field(None, min_length=1, max_length=500)
    category: str = Field(default="custom")
    server_url: str = Field(..., description="MCP server URL")
    requires_auth: bool = Field(False)
    auth_type: Literal["none", "oauth", "bearer"] | None = Field(None)
    is_public: bool = Field(False)
    bearer_token: str | None = Field(None)

    @model_validator(mode="after")
    def validate_auth_type(self):
        """Require an explicit ``auth_type`` whenever ``requires_auth`` is set."""
        if self.requires_auth and not self.auth_type:
            raise ValueError("auth_type must be specified when requires_auth is True")
        return self


class UpdateCustomIntegrationRequest(BaseModel):
    """Request to update a custom integration (partial update)."""

    name: str | None = Field(None, min_length=1, max_length=100)
    description: str | None = Field(None, min_length=1, max_length=500)
    server_url: str | None = None
    requires_auth: bool | None = None
    auth_type: Literal["none", "oauth", "bearer"] | None = None
    is_public: bool | None = None


class ConnectIntegrationRequest(BaseModel):
    """Request to connect an integration."""

    redirect_path: str = Field(
        default="/integrations",
        description="Frontend path to redirect after OAuth completes",
    )
    bearer_token: str | None = Field(None)


class UpdateIntegrationInstructionsRequest(BaseModel):
    """Request to set a user's custom instructions for one integration."""

    content: str = Field(
        default="",
        max_length=8000,
        description="Markdown instructions the agent should honor for this integration",
    )
