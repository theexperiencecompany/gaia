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
class SectionScope:
    """The per-call half of a SectionContext: what this run is about, which its configurable does not carry.

    Field meanings are SectionContext's; user_id, when set, wins over the
    configurable's.
    """

    query: str | None = None
    request_query: str | None = None
    user_id: str | None = None
    subagent_id: str | None = None
    integration_id: str | None = None


@dataclass(frozen=True)
class SectionContext:
    """Everything any section is allowed to read.

    A closed, typed shape rather than the run's configurable: a section that
    could reach into the whole bag would be free to grow a dependency on
    anything, and "what does context assembly actually depend on?" would once
    again only be answerable by reading every fetch.
    """

    tier: AgentTier
    user_id: str | None = None
    user_name: str | None = None
    #: Conversation the run belongs to. Sections needing per-conversation
    #: ledger state (open approval pendings) read it here instead of reaching
    #: into the run's configurable bag.
    conversation_id: str | None = None
    user_timezone: str | None = None
    #: Onboarding answers; open by construction, so no fixed shape.
    user_preferences: dict[str, Any] | None = None
    writing_style: dict[str, Any] | None = None
    #: What this turn is about — the retrieval query for every volatile section.
    query: str | None = None
    #: The user's own words for this turn, when comms already recalled memories
    #: on them. Memory recall reuses that result before querying with query.
    request_query: str | None = None
    subagent_id: str | None = None
    integration_id: str | None = None
    vfs_session_id: str | None = None
    active_todo_id: str | None = None
    execution_mode: ExecutionMode = "interactive"
    #: Conversation channel. Read by the comms platform banner, which names the
    #: messaging app so replies read native to it.
    source: str | None = None

    @classmethod
    def from_configurable(
        cls,
        tier: AgentTier,
        configurable: AgentConfigurable,
        scope: SectionScope | None = None,
    ) -> "SectionContext":
        """Read a run's configurable, plus the per-call scope, into the closed section shape.

        user_preferences / writing_style come off configurable the
        same way user_name / user_timezone do — set once at the run
        tree's root by build_agent_config and inherited unchanged by every
        child, never overridden per call.
        """
        scope = scope if scope is not None else SectionScope()
        mode = configurable.get("execution_mode") or "interactive"
        return cls(
            tier=tier,
            user_id=scope.user_id or configurable.get("user_id"),
            conversation_id=configurable.get("conversation_id"),
            user_name=configurable.get("user_name"),
            user_timezone=configurable.get("user_timezone"),
            user_preferences=configurable.get("user_preferences"),
            writing_style=configurable.get("writing_style"),
            query=scope.query,
            request_query=scope.request_query,
            subagent_id=scope.subagent_id,
            integration_id=scope.integration_id,
            vfs_session_id=configurable.get("vfs_session_id"),
            active_todo_id=configurable.get("active_todo_id"),
            execution_mode="background" if mode == "background" else "interactive",
            source=configurable.get("conversation_source"),
        )
