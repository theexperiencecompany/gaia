"""Every piece of context an agent can be given, declared once.

A section says three things: which slot it belongs in, which tiers get it, and
how to fetch its text. Tier differences are therefore rows in :data:`SECTIONS`
rather than branches in five separate builders — adding a section to a tier is
one edit to one ``applies_to`` set.

The slot each section declares is the correctness-critical part. Anything whose
text depends on the current query or turn is volatile and belongs in
``MEMORY_RECALL``, at the tail of the system block. Anything that changes only
when the user edits a preference or connects an integration is stable and
belongs in ``DYNAMIC_STABLE``, inside the cacheable prefix. Getting that
backwards is what silently destroys the prompt cache.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal

from app.agents.context.fetchers import (
    build_active_todo_banner,
    build_connected_integrations_manifest,
    build_core_memory_block,
    build_gaia_knowledge_block,
    build_memory_recall_block,
    build_tracked_todos_block,
    build_workspace_session_banner,
)
from app.agents.context.slots import PromptSlot
from app.agents.context.text import (
    BACKGROUND_EXECUTION_BANNER,
    CONNECTED_INTEGRATIONS_HEADER,
    EXECUTOR_CONNECTED_INTEGRATIONS_HEADER,
)
from app.agents.context.tiers import ALL_TIERS, WORKER_TIERS, AgentTier
from app.agents.skills.discovery import get_available_skills_text
from app.agents.workspace.skill_loader import target_to_subagent
from app.agents.workspace.system_docs import integration_skills_block
from app.config.oauth_config import get_integration_by_id
from app.constants.log_tags import LogTag
from app.constants.skills import EXECUTOR_SUBAGENT_ID
from app.models.agent_models import AgentConfigurable
from app.services.integration_instructions_service import get_instructions
from app.services.provider_metadata_service import get_provider_metadata
from app.utils.user_preferences_utils import format_user_preferences_for_agent
from shared.py.wide_events import log

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
        user_preferences: dict[str, Any] | None = None,
        writing_style: dict[str, Any] | None = None,
    ) -> "SectionContext":
        """Read a run's configurable into the closed section shape."""
        mode = configurable.get("execution_mode") or "interactive"
        return cls(
            tier=tier,
            user_id=user_id or configurable.get("user_id"),
            user_name=configurable.get("user_name"),
            user_timezone=configurable.get("user_timezone"),
            user_preferences=user_preferences,
            writing_style=writing_style,
            query=query,
            subagent_id=subagent_id,
            integration_id=integration_id,
            vfs_session_id=configurable.get("vfs_session_id"),
            active_todo_id=configurable.get("active_todo_id"),
            execution_mode="background" if mode == "background" else "interactive",
            source=configurable.get("conversation_source"),
        )


SectionFetch = Callable[[SectionContext], Awaitable[str]]


@dataclass(frozen=True)
class Section:
    """One declared piece of context."""

    id: str
    slot: PromptSlot
    applies_to: frozenset[AgentTier]
    #: Position within the slot. Sparse so a section can be inserted between two
    #: existing ones without renumbering the table.
    order: int
    fetch: SectionFetch

    def applies(self, tier: AgentTier) -> bool:
        return tier in self.applies_to


# --- stable sections: change on a preference edit or a connect, not per turn ---


async def _user_identity(ctx: SectionContext) -> str:
    lines = []
    if ctx.user_name:
        lines.append(f"User Name: {ctx.user_name}")
    # Only the static home zone lives here. The clock itself rides a
    # HumanMessage — a minute-ticking byte in this block would reset the cache
    # boundary on every call.
    if ctx.user_timezone:
        lines.append(f"User Timezone: {ctx.user_timezone}")
    return "\n".join(lines)


async def _user_prefs(ctx: SectionContext) -> str:
    if not (ctx.user_preferences or ctx.writing_style):
        return ""
    formatted = format_user_preferences_for_agent(
        ctx.user_preferences or {}, writing_style=ctx.writing_style
    )
    return f"User Preferences:\n{formatted}" if formatted else ""


async def _workspace_session(ctx: SectionContext) -> str:
    # Only ``vfs_session_id`` is trusted. Falling back to ``thread_id`` would
    # state ``/workspace/sessions/executor_<conv>/``, sending deliverables
    # outside the directory the artifact watcher scans, where they are lost.
    if not ctx.vfs_session_id:
        return ""
    return build_workspace_session_banner(ctx.vfs_session_id)


async def _integrations_manifest(ctx: SectionContext) -> str:
    if not ctx.user_id:
        return ""
    header = (
        EXECUTOR_CONNECTED_INTEGRATIONS_HEADER
        if ctx.tier is AgentTier.EXECUTOR
        else CONNECTED_INTEGRATIONS_HEADER
    )
    return await build_connected_integrations_manifest(ctx.user_id, header=header)


async def _provider_metadata(ctx: SectionContext) -> str:
    """Who the user is on this provider — GitHub login, Gmail address, etc."""
    if not (ctx.integration_id and ctx.user_id):
        return ""
    integration = get_integration_by_id(ctx.integration_id)
    if not integration or not integration.provider:
        return ""
    try:
        metadata = await get_provider_metadata(ctx.user_id, integration.provider)
    except Exception as e:
        log.warning(
            f"{LogTag.AGENT} Failed to fetch provider metadata",
            provider=integration.provider,
            user_id=ctx.user_id,
            error_type=type(e).__name__,
            error=str(e),
        )
        return ""
    if not metadata:
        return ""
    lines = "\n".join(f"- {key}: {value}" for key, value in metadata.items())
    return f"USER CONTEXT FOR {integration.name.upper()}:\n{lines}"


async def _custom_instructions(ctx: SectionContext) -> str:
    """Injected in full rather than as a read-on-demand pointer: the whole point
    is that the subagent honours "focus on #eng" without an extra file read."""
    target = ctx.integration_id or ctx.subagent_id
    if not (target and ctx.user_id):
        return ""
    try:
        content = await get_instructions(ctx.user_id, target)
    except Exception as e:
        log.warning(
            f"{LogTag.AGENT} Failed to fetch custom instructions",
            integration_id=target,
            user_id=ctx.user_id,
            error_type=type(e).__name__,
            error=str(e),
        )
        return ""
    if not content:
        return ""
    integration = get_integration_by_id(target)
    label = (integration.name if integration else target).upper()
    return f"CUSTOM INSTRUCTIONS FOR {label} (set by the user — honor these):\n{content.strip()}"


# --- volatile sections: retrieved against this turn, churn turn to turn -------


async def _core_memory(ctx: SectionContext) -> str:
    return await build_core_memory_block(ctx.user_id) if ctx.user_id else ""


async def _memory_recall(ctx: SectionContext) -> str:
    if not (ctx.user_id and ctx.query):
        return ""
    return await build_memory_recall_block(ctx.user_id, ctx.query)


async def _gaia_knowledge(ctx: SectionContext) -> str:
    return await build_gaia_knowledge_block(ctx.query) if ctx.query else ""


async def _tracked_todos(ctx: SectionContext) -> str:
    if not ctx.user_id:
        return ""
    return await build_tracked_todos_block(ctx.user_id, ctx.active_todo_id)


async def _skills(ctx: SectionContext) -> str:
    """Installable skills, plus this subagent's integration-specific ones."""
    if not ctx.user_id:
        return ""
    block = ""
    try:
        block = await get_available_skills_text(
            user_id=ctx.user_id, agent_name=ctx.subagent_id or EXECUTOR_SUBAGENT_ID
        )
    except Exception as e:
        log.warning(
            f"{LogTag.AGENT} Error injecting installable skills",
            user_id=ctx.user_id,
            error_type=type(e).__name__,
            error=str(e),
        )
    if ctx.subagent_id:
        # ``subagent_id`` carries the agent_name ("docgen_agent") but
        # skills_by_subagent is keyed by the subagent id ("docgen"). Mapped the
        # same way the loader builds those keys, or this silently finds nothing.
        if integration_block := integration_skills_block(target_to_subagent(ctx.subagent_id)):
            block = f"{block}\n\n{integration_block}" if block else integration_block
    return block


async def _background_banner(ctx: SectionContext) -> str:
    return BACKGROUND_EXECUTION_BANNER if ctx.execution_mode == "background" else ""


async def _active_todo_banner(ctx: SectionContext) -> str:
    if not (ctx.user_id and ctx.active_todo_id):
        return ""
    return await build_active_todo_banner(ctx.user_id, ctx.active_todo_id)


#: The section × tier table. Ordering within a slot is by ``order``; the two
#: run banners deliberately sort last so their directives land with recency,
#: immediately before the conversation begins.
SECTIONS: tuple[Section, ...] = (
    Section("user_identity", PromptSlot.DYNAMIC_STABLE, ALL_TIERS, 10, _user_identity),
    Section("user_prefs", PromptSlot.DYNAMIC_STABLE, frozenset({AgentTier.COMMS}), 20, _user_prefs),
    Section("workspace_session", PromptSlot.DYNAMIC_STABLE, WORKER_TIERS, 30, _workspace_session),
    Section(
        "integrations_manifest",
        PromptSlot.DYNAMIC_STABLE,
        frozenset({AgentTier.COMMS, AgentTier.EXECUTOR}),
        40,
        _integrations_manifest,
    ),
    Section(
        "provider_metadata",
        PromptSlot.DYNAMIC_STABLE,
        frozenset({AgentTier.PROVIDER_SUBAGENT}),
        50,
        _provider_metadata,
    ),
    Section(
        "custom_instructions",
        PromptSlot.DYNAMIC_STABLE,
        frozenset({AgentTier.PROVIDER_SUBAGENT}),
        60,
        _custom_instructions,
    ),
    Section(
        "core_memory", PromptSlot.MEMORY_RECALL, frozenset({AgentTier.COMMS}), 10, _core_memory
    ),
    Section("memory_recall", PromptSlot.MEMORY_RECALL, ALL_TIERS, 20, _memory_recall),
    Section(
        "gaia_knowledge",
        PromptSlot.MEMORY_RECALL,
        frozenset({AgentTier.COMMS}),
        30,
        _gaia_knowledge,
    ),
    Section("skills", PromptSlot.MEMORY_RECALL, WORKER_TIERS, 40, _skills),
    Section(
        "tracked_todos",
        PromptSlot.MEMORY_RECALL,
        frozenset({AgentTier.COMMS}),
        50,
        _tracked_todos,
    ),
    Section("bg_banner", PromptSlot.MEMORY_RECALL, ALL_TIERS, 60, _background_banner),
    Section("active_todo_banner", PromptSlot.MEMORY_RECALL, ALL_TIERS, 70, _active_todo_banner),
)


def sections_for(tier: AgentTier, slot: PromptSlot) -> list[Section]:
    """The sections ``tier`` gets in ``slot``, in intra-slot order."""
    return sorted(
        (s for s in SECTIONS if s.slot is slot and s.applies(tier)), key=lambda s: s.order
    )
