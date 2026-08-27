"""Everything any context section is allowed to read.

Its own module rather than living beside the section table, so the fetchers can
take it as their argument without importing the table that calls them.
"""

from dataclasses import dataclass
from typing import Any, Literal

from app.agents.context.tiers import AgentTier
from app.models.agent_models import AgentConfigurable

ExecutionMode = Literal["interactive", "background"]


@dataclass(frozen=True)
class SectionContext:
    """Everything any section is allowed to read.

    A closed, typed shape rather than the run's ``configurable``: a section that
    could reach into the whole bag would be free to grow a dependency on
    anything, and "what does context assembly actually depend on?" would once
    again only be answerable by reading every fetch.
    """

    tier: AgentTier
    user_id: str | None = None
    user_name: str | None = None
    user_timezone: str | None = None
    #: Onboarding answers; open by construction, so no fixed shape.
    user_preferences: dict[str, Any] | None = None
    writing_style: dict[str, Any] | None = None
    #: What this turn is about — the retrieval query for every volatile section.
    query: str | None = None
    subagent_id: str | None = None
    integration_id: str | None = None
    vfs_session_id: str | None = None
    active_todo_id: str | None = None
    execution_mode: ExecutionMode = "interactive"
    #: Conversation channel. Observability only; no section branches on it.
    source: str | None = None

    @classmethod
    def from_configurable(
        cls,
        tier: AgentTier,
        configurable: AgentConfigurable,
        *,
        query: str | None = None,
        user_id: str | None = None,
        subagent_id: str | None = None,
        integration_id: str | None = None,
    ) -> "SectionContext":
        """Read a run's configurable into the closed section shape.

        ``user_preferences`` / ``writing_style`` come off ``configurable`` the
        same way ``user_name`` / ``user_timezone`` do — set once at the run
        tree's root by ``build_agent_config`` and inherited unchanged by every
        child, never overridden per call.
        """
        mode = configurable.get("execution_mode") or "interactive"
        return cls(
            tier=tier,
            user_id=user_id or configurable.get("user_id"),
            user_name=configurable.get("user_name"),
            user_timezone=configurable.get("user_timezone"),
            user_preferences=configurable.get("user_preferences"),
            writing_style=configurable.get("writing_style"),
            query=query,
            subagent_id=subagent_id,
            integration_id=integration_id,
            vfs_session_id=configurable.get("vfs_session_id"),
            active_todo_id=configurable.get("active_todo_id"),
            execution_mode="background" if mode == "background" else "interactive",
            source=configurable.get("conversation_source"),
        )
