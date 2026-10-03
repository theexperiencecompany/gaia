"""Repository for the agent_lab_sessions collection (one row per agent run)."""

from datetime import UTC, datetime
from typing import Any

from app.db.repositories.base import UserScopedRepository
from app.models.agent_lab_models import (
    ACTIVE_AGENT_SESSION_STATES,
    AgentSessionDocument,
    AgentSessionUpdate,
)


class AgentLabSessionsRepository(UserScopedRepository[AgentSessionDocument, AgentSessionUpdate]):
    """The agent_lab_sessions collection repository (user-scoped, uncached)."""

    collection_name = "agent_lab_sessions"
    document_model = AgentSessionDocument
    update_model = AgentSessionUpdate
    uses_object_id = True
    # Session state mutates on every driver call, so reads stay uncached (e2b_sandboxes precedent).
    cache_policy = None

    async def get_for_user(self, session_id: str, *, user_id: str) -> AgentSessionDocument | None:
        """Fetch one lab session by id, scoped to its owner."""
        return await self.get(session_id, user_id=user_id)

    async def record_event(
        self, session_id: str, *, user_id: str, kind: str, raw: dict[str, Any]
    ) -> AgentSessionDocument | None:
        """Persist the latest lifecycle event tail verbatim, scoped to its owner."""
        return await self.update(
            session_id,
            user_id=user_id,
            update=AgentSessionUpdate(
                last_event_kind=kind, last_event_at=datetime.now(UTC), last_event_raw=raw
            ),
        )

    async def list_active_for_user(self, user_id: str) -> list[AgentSessionDocument]:
        """List the user's starting/running sessions, most-recently-updated first."""
        return await self._find(
            {
                "user_id": user_id,
                "state": {"$in": [state.value for state in ACTIVE_AGENT_SESSION_STATES]},
            },
            sort=[("updated_at", -1)],
        )


agent_lab_session_repository = AgentLabSessionsRepository()
