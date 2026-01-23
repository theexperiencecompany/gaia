"""SQLAlchemy models for OAuth tokens and MCP credentials."""

from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.postgresql import Base


class MCPAuthType(str, Enum):
    """Authentication types for MCP integrations."""

    NONE = "none"
    OAUTH = "oauth"
    BEARER = "bearer"


class MCPCredentialStatus(str, Enum):
    """Status values for MCP credentials."""

    PENDING = "pending"
    CONNECTED = "connected"
    ERROR = "error"


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


class MCPCredential(Base):
    """User's MCP integration connection state and encrypted credentials."""

    __tablename__ = "mcp_credentials"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    integration_id: Mapped[str] = mapped_column(String(100), nullable=False)
    auth_type: Mapped[MCPAuthType] = mapped_column(
        SQLEnum(MCPAuthType, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )
    status: Mapped[MCPCredentialStatus] = mapped_column(
        SQLEnum(MCPCredentialStatus, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=MCPCredentialStatus.PENDING,
    )
    access_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    refresh_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    client_registration: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    connected_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "user_id", "integration_id", name="uq_mcp_creds_user_integration"
        ),
    )
