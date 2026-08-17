"""SQLAlchemy models for paired bridge devices and their exposed MCP servers."""

from datetime import datetime
from enum import Enum

from sqlalchemy import (
    DateTime,
    Enum as SQLEnum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.postgresql import Base


class DeviceStatus(str, Enum):
    """Lifecycle of a paired device."""

    ACTIVE = "active"
    REVOKED = "revoked"


class DeviceServerStatus(str, Enum):
    """Connection state of one MCP server a device exposes."""

    CONNECTED = "connected"
    ERROR = "error"


class Device(Base):
    """A user's paired machine running the ``gaia bridge`` daemon.

    ``refresh_token_hash`` holds the SHA-256 of the current long-lived refresh
    credential (never the plaintext). ``previous_refresh_token_hash`` retains the
    just-rotated value so a replay of an already-rotated token is detectable and
    triggers revocation (refresh-token reuse detection).
    """

    __tablename__ = "bridge_devices"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    platform: Mapped[str | None] = mapped_column(String(60), nullable=True)
    daemon_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    status: Mapped[DeviceStatus] = mapped_column(
        SQLEnum(DeviceStatus, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=DeviceStatus.ACTIVE,
    )
    refresh_token_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    previous_refresh_token_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=func.now(), onupdate=func.now(), nullable=False
    )


class DeviceMCPServer(Base):
    """One MCP server a device exposes to the cloud over its tunnel.

    Each row is surfaced to the user as a custom integration (``managed_by="mcp"``,
    ``category="device"``, ``mcp_config.transport="device"``) so the existing
    per-user subagent / namespace machinery exposes its tools to the agent.
    ``integration_id`` is that integration's id.
    """

    __tablename__ = "bridge_device_mcp_servers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("bridge_devices.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    integration_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    # Daemon-local identifier for this server (the ``--name`` slug, or "filesystem"
    # for the built-in server). Unique per device; the frame's ``server`` field.
    server_key: Mapped[str] = mapped_column(String(120), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[DeviceServerStatus] = mapped_column(
        SQLEnum(DeviceServerStatus, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=DeviceServerStatus.CONNECTED,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    tools_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (UniqueConstraint("device_id", "server_key", name="uq_device_server_key"),)
