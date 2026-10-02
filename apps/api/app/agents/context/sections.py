"""Every piece of context an agent can be given, declared once.

A section says three things: which slot it belongs in, which tiers get it,
and how to fetch its text. Tier differences are rows in :data:SECTIONS
rather than branches in five separate builders.

The slot each section declares is correctness-critical: text depending on
the current query/turn is volatile (MEMORY_RECALL, tail of system block);
text that only changes on preference/integration edits is stable
(DYNAMIC_STABLE, inside the cacheable prefix). Getting that backwards
silently destroys the prompt cache.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from app.agents.context.fetchers import (
    build_active_todo_banner,
    build_agenda_and_activity_block,
    build_background_banner,
    build_connected_devices_manifest,
    build_connected_integrations_manifest,
    build_core_memory_block,
    build_gaia_knowledge_block,
    build_memory_recall_block,
    build_new_user_guidance_block,
    build_open_pendings_block,
    build_provider_metadata_block,
    build_tracked_todos_block,
    build_workspace_session_banner,
)
from app.agents.context.section_context import SectionContext
from app.agents.context.slots import PromptSlot
from app.agents.context.text import (
    CONNECTED_DEVICES_HEADER,
    CONNECTED_INTEGRATIONS_HEADER,
    EXECUTOR_ACTIVATION_CONNECTED_INTEGRATIONS_HEADER,
    EXECUTOR_CONNECTED_DEVICES_HEADER,
)
from app.agents.context.tiers import ALL_TIERS, WORKER_TIERS, AgentTier
from app.agents.skills.discovery import get_available_skills_text
from app.agents.workspace.skill_loader import target_to_subagent
from app.agents.workspace.system_docs import integration_skills_block
from app.config.oauth_config import get_integration_by_id
from app.constants.log_tags import LogTag
from app.constants.skills import EXECUTOR_SUBAGENT_ID
from app.models.chat_models import BOT_CONVERSATION_SOURCES, ConversationSource
from app.services.integration_instructions_service import get_instructions
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


async def _platform_banner(ctx: SectionContext) -> str:
    """Build the banner naming which messaging app comms is replying in.

    The model cannot read configurable directly, so this is the only way it
    learns the platform. Applies to bot channels only, not web/mobile/desktop.
    """
    source = ConversationSource.coerce(ctx.source)
    # Desktop tools are named only here, not in the static prompt: retrieval
    # already gates them by source, so naming them for every channel cost
    # tokens off-desktop for no benefit.
    if source is ConversationSource.DESKTOP:
        return (
            "You are on the user's desktop app, so desktop tools are available "
            "(discover them with retrieve_tools): take_screenshot, "
            "read_clipboard/write_clipboard, open_app, open_url, list_windows. "
            "Use take_screenshot whenever the user references what they are "
            "currently looking at."
        )
    if source is None or source not in BOT_CONVERSATION_SOURCES:
        return ""
    name = source.display_name
    return (
        f"You are chatting with the user in their {name} chat right now. "
        f"Write like a normal {name} message: plain text, short, no markdown "
        "tables or rich cards."
    )


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
    if ctx.tier is not AgentTier.EXECUTOR:
        header = CONNECTED_INTEGRATIONS_HEADER
    else:
        header = EXECUTOR_ACTIVATION_CONNECTED_INTEGRATIONS_HEADER
    return await build_connected_integrations_manifest(ctx.user_id, header=header)


async def _connected_devices(ctx: SectionContext) -> str:
    if not ctx.user_id:
        return ""
    header = (
        EXECUTOR_CONNECTED_DEVICES_HEADER
        if ctx.tier is AgentTier.EXECUTOR
        else CONNECTED_DEVICES_HEADER
    )
    return await build_connected_devices_manifest(ctx.user_id, header=header)


async def _provider_metadata(ctx: SectionContext) -> str:
    return await build_provider_metadata_block(ctx.integration_id, ctx.user_id)


async def _custom_instructions(ctx: SectionContext) -> str:
    """Injected in full rather than as a read-on-demand pointer.

    The point is that the subagent honours "focus on #eng" without an extra
    file read.
    """
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
    return f"CUSTOM INSTRUCTIONS FOR {label} (set by the user, honor these):\n{content.strip()}"


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
    Section(
        "platform_banner",
        PromptSlot.DYNAMIC_STABLE,
        frozenset({AgentTier.COMMS}),
        5,
        _platform_banner,
    ),
    Section("user_identity", PromptSlot.DYNAMIC_STABLE, ALL_TIERS, 10, _user_identity),
    Section("user_prefs", PromptSlot.DYNAMIC_STABLE, ALL_TIERS, 20, _user_prefs),
    # Comms only: the executor never opens a conversation. Stable rather than
    # volatile since it's a pure function of signup answers plus a slow
    # counter, byte-identical until the user outgrows it.
    Section(
        "new_user_guidance",
        PromptSlot.DYNAMIC_STABLE,
        frozenset({AgentTier.COMMS}),
        25,
        build_new_user_guidance_block,
    ),
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
        "connected_devices",
        PromptSlot.DYNAMIC_STABLE,
        frozenset({AgentTier.COMMS, AgentTier.EXECUTOR}),
        45,
        _connected_devices,
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
    # Capability info, not retrieval: pure function of user + agent, Redis-
    # cached 12h (was re-read every worker call in the volatile slot). Same
    # once-per-change prefix-invalidation trade integrations_manifest makes.
    Section("skills", PromptSlot.DYNAMIC_STABLE, WORKER_TIERS, 70, _skills),
    # Open approval pendings: ledger state that changes on user/agent decisions,
    # not per turn — same stability trade as integrations_manifest above.
    Section(
        "open_pendings", PromptSlot.DYNAMIC_STABLE, WORKER_TIERS, 75, build_open_pendings_block
    ),
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
    """Return the sections tier gets in slot, in intra-slot order."""
    return sorted(
        (s for s in SECTIONS if s.slot is slot and s.applies(tier)), key=lambda s: s.order
    )
