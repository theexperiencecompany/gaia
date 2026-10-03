"""Typed documents for Agent Lab sessions (the agent_lab_sessions collection)."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from app.db.repositories.base import UserScopedDocument


class AgentKind(StrEnum):
    """Which CLI drives the session (one driver subclass per member)."""

    CLAUDE = "claude"
    CODEX = "codex"
    OPENCODE = "opencode"


class AgentSessionState(StrEnum):
    """Lifecycle of one lab session; STARTING/RUNNING are the active set."""

    STARTING = "starting"
    RUNNING = "running"
    STOPPED = "stopped"
    FAILED = "failed"


ACTIVE_AGENT_SESSION_STATES: tuple[AgentSessionState, ...] = (
    AgentSessionState.STARTING,
    AgentSessionState.RUNNING,
)


class AgentSessionDocument(UserScopedDocument):
    """One agent run against a tracked todo, owned by a user."""

    todo_id: str
    agent: AgentKind
    state: AgentSessionState = AgentSessionState.STARTING
    sandbox_session_ref: str | None = None
    transcript_cursor: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class AgentSessionUpdate(BaseModel):
    """Partial $set update for a lab session — every settable field, all optional."""

    model_config = ConfigDict(extra="forbid")

    state: AgentSessionState | None = None
    sandbox_session_ref: str | None = None
    transcript_cursor: str | None = None
