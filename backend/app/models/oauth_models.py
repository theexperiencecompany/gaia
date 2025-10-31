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


class OAuthIntegration(BaseModel):
    """OAuth integration configuration."""

    id: str
    name: str
    description: str
    icons: List[str]  # List of icon URLs for different contexts/sizes
    category: str
    provider: str  # 'google', 'github', 'figma', 'notion', etc.
    scopes: List[OAuthScope]
    available: bool = True
    oauth_endpoints: Optional[Dict[str, str]] = None
    # Display and organization properties
    is_special: bool = False  # For unified integrations like Google Workspace
    display_priority: int = 0  # Higher priority shows first
    included_integrations: List[str] = []  # Child integrations for unified ones
    # Short name for slash command dropdowns and quick access
    short_name: Optional[str] = None  # e.g., "gmail", "calendar", "drive", "docs"
    managed_by: Literal["self", "composio"]
    # Composio-specific configuration
    composio_config: Optional[ComposioConfig] = None
    associated_triggers: List[
        TriggerConfig
    ] = []  # Triggers associated with this integration
    # MCP Server link - if this OAuth integration powers an MCP server
    mcp_server_id: Optional[str] = None  # Links to MCPServerTemplate.id


class IntegrationConfigResponse(BaseModel):
    """Response model for integration configuration."""

    id: str
    name: str
    description: str
    icons: List[str]
    category: str
    provider: str
    available: bool
    loginEndpoint: Optional[str]
    isSpecial: bool
    displayPriority: int
    includedIntegrations: List[str]
