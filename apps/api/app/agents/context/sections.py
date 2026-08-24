"""Every piece of context an agent can be given, declared once.

A section says three things: which slot it belongs in, which tiers get it, and
how to fetch its text. Tier differences are therefore rows in :data:`SECTIONS`
rather than branches in five separate builders — adding a section to a tier is
one edit to one ``applies_to`` set.

A row points straight at its body in ``fetchers``; the private functions here are
only the sections that genuinely branch before rendering, and exist because they
branch, not to adapt one signature to another.

The slot each section declares is the correctness-critical part. Anything whose
text depends on the current query or turn is volatile and belongs in
``MEMORY_RECALL``, at the tail of the system block. Anything that changes only
when the user edits a preference or connects an integration is stable and
belongs in ``DYNAMIC_STABLE``, inside the cacheable prefix. Getting that
backwards is what silently destroys the prompt cache.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from app.agents.context.fetchers import (
    build_active_todo_banner,
    build_agenda_and_activity_block,
    build_background_banner,
    build_connected_integrations_manifest,
    build_core_memory_block,
    build_gaia_knowledge_block,
    build_memory_recall_block,
    build_tracked_todos_block,
    build_workspace_session_banner,
)
from app.agents.context.section_context import SectionContext
from app.agents.context.slots import PromptSlot
from app.agents.context.text import (
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
from app.services.integration_instructions_service import get_instructions
from app.services.provider_metadata_service import get_provider_metadata
from app.utils.user_preferences_utils import format_user_preferences_for_agent
from shared.py.wide_events import log

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


# --- volatile sections: retrieved against this turn, churn turn to turn -------


#: The section × tier table. Ordering within a slot is by ``order``; the two
#: run banners deliberately sort last so their directives land with recency,
#: immediately before the conversation begins.
SECTIONS: tuple[Section, ...] = (
    Section("user_identity", PromptSlot.DYNAMIC_STABLE, ALL_TIERS, 10, _user_identity),
    Section("user_prefs", PromptSlot.DYNAMIC_STABLE, ALL_TIERS, 20, _user_prefs),
    Section(
        "workspace_session",
        PromptSlot.DYNAMIC_STABLE,
        WORKER_TIERS,
        30,
        build_workspace_session_banner,
    ),
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
    # Capability info, not retrieval: the listing is a pure function of the
    # user and the agent — no query, no clock — and is Redis-cached for 12h,
    # so it is byte-stable for a conversation's whole life. In the volatile
    # slot it was re-read on every worker call (~475-1,400 tokens each time).
    # The trade, taken knowingly: install_skill_from_github can change the
    # listing mid-conversation, which invalidates the prefix ONCE — the same
    # trade integrations_manifest already makes for account connects.
    Section("skills", PromptSlot.DYNAMIC_STABLE, WORKER_TIERS, 70, _skills),
    # The memory core's documents, not the whole core: the agenda and the
    # activity journal are split off into their own volatile section, because
    # they are rewritten every turn and would otherwise churn the cached prefix.
    Section("core_memory", PromptSlot.MEMORY_RECALL, ALL_TIERS, 5, build_core_memory_block),
    Section(
        "agenda_activity", PromptSlot.MEMORY_RECALL, ALL_TIERS, 10, build_agenda_and_activity_block
    ),
    Section("memory_recall", PromptSlot.MEMORY_RECALL, ALL_TIERS, 20, build_memory_recall_block),
    Section("gaia_knowledge", PromptSlot.MEMORY_RECALL, ALL_TIERS, 30, build_gaia_knowledge_block),
    Section("tracked_todos", PromptSlot.MEMORY_RECALL, ALL_TIERS, 50, build_tracked_todos_block),
    Section("bg_banner", PromptSlot.MEMORY_RECALL, ALL_TIERS, 60, build_background_banner),
    Section(
        "active_todo_banner", PromptSlot.MEMORY_RECALL, ALL_TIERS, 70, build_active_todo_banner
    ),
)


def sections_for(tier: AgentTier, slot: PromptSlot) -> list[Section]:
    """The sections ``tier`` gets in ``slot``, in intra-slot order."""
    return sorted(
        (s for s in SECTIONS if s.slot is slot and s.applies(tier)), key=lambda s: s.order
    )
