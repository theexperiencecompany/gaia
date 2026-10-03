"""Dumb-pipe persistence for agent lifecycle events pushed from the sandbox.

The receiver never classifies or interprets kind/raw — it authenticates the
caller, checks the session belongs to them, and stores the payload verbatim.
A future supervisor reads the tail; until then this module is storage only.
"""

from typing import Any

from app.db.repositories.agent_lab_sessions import agent_lab_session_repository
from app.models.agent_lab_models import AgentSessionDocument
from app.utils.errors import AppError


async def record_lab_event(
    session_id: str, *, user_id: str, kind: str, raw: dict[str, Any]
) -> AgentSessionDocument:
    """Store one raw lifecycle event tail; fails loud on unknown or foreign sessions."""
    updated = await agent_lab_session_repository.record_event(
        session_id, user_id=user_id, kind=kind, raw=raw
    )
    if updated is None:
        raise AppError(
            message="agent lab session not found",
            why="the id is unknown or belongs to another user",
            fix="start a session with lab_start, then retry with its id",
            status_code=404,
            code="agent_lab_session_not_found",
        )
    return updated
