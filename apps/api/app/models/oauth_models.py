"""
OAuth Token Models

This module defines SQLAlchemy models for OAuth tokens.
"""

from collections.abc import Callable
from datetime import datetime
from typing import Dict, List, Literal, Optional

from app.db.postgresql import Base
from pydantic import BaseModel
from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func


class OAuthToken(Base):
    """SQLAlchemy model for OAuth tokens."""

    __tablename__ = "oauth_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    access_token: Mapped[str] = mapped_column(Text, nullable=False)
    refresh_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_data: Mapped[str] = mapped_column(
        Text, nullable=False, comment="JSON serialized token data"
    )
    scopes: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="Space-separated OAuth scopes"
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now(), nullable=False
    )

    # __table_args__ = (
    #     Index("ix_oauth_tokens_user_id", "user_id"),
    #     UniqueConstraint("access_token", name="uq_oauth_tokens_access_token"),
    #     {"sqlite_autoincrement": True},
    # )


class OAuthScope(BaseModel):
    """OAuth scope configuration."""

    scope: str
    description: str


TRIGGER_TYPES = Literal["GMAIL_NEW_GMAIL_MESSAGE"]


class TriggerConfig(BaseModel):
    """Configuration for a specific trigger."""

    slug: TRIGGER_TYPES  # Extendable for more triggers
    name: str
    description: str
    config: Optional[dict] = None
    get_config: Optional[Callable] = None


class ComposioConfig(BaseModel):
    """Configuration for Composio integration."""

    auth_config_id: str
    toolkit: str


class SubAgentConfig(BaseModel):
    """Configuration for sub-agent metadata."""

    has_subagent: bool = False
    agent_name: str
    tool_space: str
    handoff_tool_name: str
    domain: str
    capabilities: str
    use_cases: str
    system_prompt: str
    use_direct_tools: bool = False
    disable_retrieve_tools: bool = False
    specific_tools: Optional[List[str]] = None


class ProviderMetadataConfig(BaseModel):
    """
    Configuration for fetching and extracting provider-specific user metadata.

    This enables automatic fetching of user info (like username) when an OAuth
    integration is connected, which can be injected into agent prompts for
    improved performance.
    """

    user_info_tool: str  # Tool name to call for user info (e.g., "GITHUB_GET_THE_AUTHENTICATED_USER")
    username_field: str  # JSON path to username in response (e.g., "data.login" or "data.data.username")
    extract_fields: Optional[Dict[str, str]] = (
        None  # Additional fields to extract: {field_name: json_path}
    )


class MCPConfig(BaseModel):
    """Configuration for MCP (Model Context Protocol) integration."""

    server_url: str
    transport: str = "sse"  # sse, http, streamable_http
    requires_auth: bool = False


class OAuthIntegration(BaseModel):
    """OAuth integration configuration."""

    id: str
    name: str
    description: str
    category: str
    provider: str  # 'google', 'github', 'figma', 'notion', etc.
    scopes: List[OAuthScope]
    available: bool = True
    oauth_endpoints: Optional[Dict[str, str]] = None
    # Display and organization properties
    is_special: bool = False  # For unified integrations like Google Workspace
    display_priority: int = 0  # Higher priority shows first
    included_integrations: List[str] = []  # Child integrations for unified ones
    is_featured: bool = False  # Featured integrations displayed at the top
    # Short name for slash command dropdowns and quick access
    short_name: Optional[str] = None  # e.g., "gmail", "calendar", "drive", "docs"
    managed_by: Literal["self", "composio", "mcp"]
    # Composio-specific configuration
    composio_config: Optional[ComposioConfig] = None
    # MCP-specific configuration
    mcp_config: Optional[MCPConfig] = None
    associated_triggers: List[
        TriggerConfig
    ] = []  # Triggers associated with this integration
    # Sub-agent configuration
    subagent_config: Optional[SubAgentConfig] = None
    # Provider metadata configuration for fetching user info (username, etc.)
    metadata_config: Optional[ProviderMetadataConfig] = None


class IntegrationConfigResponse(BaseModel):
    """Response model for integration configuration."""

    id: str
    name: str
    description: str
    category: str
    provider: str
    available: bool
    loginEndpoint: Optional[str]
    isSpecial: bool
    displayPriority: int
    includedIntegrations: List[str]
    isFeatured: bool
    managedBy: Literal["self", "composio", "mcp"]
