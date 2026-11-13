"""Every piece of context an agent can be given, declared once.

A section says three things: which slot it belongs in, which tiers get it,
and how to fetch its text. Tier differences are rows in :data:SECTIONS
rather than branches in five separate builders.

The slot each section declares is correctness-critical: text depending on
the current query/turn is volatile (MEMORY_RECALL, written into the thread
with its turn); text that only changes on preference/integration edits is
stable (DYNAMIC_STABLE, leading every request). Getting that backwards
silently destroys the prompt cache.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum

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
    build_tracked_todos_block,
    build_workspace_session_banner,
)
from app.agents.context.live_work import build_browser_task_block
from app.agents.context.section_context import SectionContext
from app.agents.context.slots import PromptSlot
from app.agents.context.text import (
    COMMS_MULTI_ACCOUNT_NOTE,
    CONNECTED_DEVICES_HEADER,
    CONNECTED_INTEGRATIONS_HEADER,
    EXECUTOR_ACTIVATION_CONNECTED_INTEGRATIONS_HEADER,
    EXECUTOR_CONNECTED_DEVICES_HEADER,
    MULTI_ACCOUNT_INSTRUCTION,
)
from app.agents.context.tiers import ALL_TIERS, WORKER_TIERS, AgentTier
from app.agents.context.work_state import build_work_state_block
from app.agents.prompts.user_instructions_prompts import render_user_instructions
from app.agents.skills.discovery import get_available_skills_text
from app.agents.workspace.skill_loader import target_to_subagent
from app.agents.workspace.system_docs import integration_skills_block
from app.constants.log_tags import LogTag
from app.constants.skills import EXECUTOR_SUBAGENT_ID
from app.models.chat_models import BOT_CONVERSATION_SOURCES, ConversationSource
from app.models.user_instructions_models import GLOBAL_INSTRUCTIONS_SCOPE
from app.services.user_instructions_service import get_instructions
from app.utils.user_preferences_utils import format_user_preferences_for_agent
from shared.py.wide_events import log

SectionFetch = Callable[[SectionContext], Awaitable[str]]


class SectionId(StrEnum):
    """Every section, named once: the table declares by it and readers look a section up by it."""

    PLATFORM_BANNER = "platform_banner"
    EXECUTOR_PLATFORM = "executor_platform"
    USER_IDENTITY = "user_identity"
    USER_PREFS = "user_prefs"
    GLOBAL_INSTRUCTIONS = "global_instructions"
    NEW_USER_GUIDANCE = "new_user_guidance"
    WORKSPACE_SESSION = "workspace_session"
    INTEGRATIONS_MANIFEST = "integrations_manifest"
    CONNECTED_DEVICES = "connected_devices"
    SKILLS = "skills"
    OPEN_PENDINGS = "open_pendings"
    CORE_MEMORY = "core_memory"
    AGENDA_ACTIVITY = "agenda_activity"
    MEMORY_RECALL = "memory_recall"
    GAIA_KNOWLEDGE = "gaia_knowledge"
    TRACKED_TODOS = "tracked_todos"
    WORK_STATE = "work_state"
    BROWSER_TASK = "browser_task"
    BG_BANNER = "bg_banner"
    ACTIVE_TODO_BANNER = "active_todo_banner"


@dataclass(frozen=True)
class Section:
    """One declared piece of context."""

    id: SectionId
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
    if source is None or source not in BOT_CONVERSATION_SOURCES:
        return ""
    name = source.display_name
    return (
        f"You are chatting with the user in their {name} chat right now. "
        f"Write like a normal {name} message: plain text, short, no markdown "
        "tables or rich cards."
    )


#: The sources a user chats from, as the executor's platform line names them.
_USER_PLATFORMS: frozenset[ConversationSource] = (
    frozenset({ConversationSource.WEB, ConversationSource.MOBILE, ConversationSource.DESKTOP})
    | BOT_CONVERSATION_SOURCES
)


async def _executor_platform(ctx: SectionContext) -> str:
    """State the platform the user is on, which decides the executor's output formats.

    Desktop tools are named only on desktop: retrieval already gates them by
    source, so naming them for every channel cost tokens off-desktop.
    """
    source = ConversationSource.coerce(ctx.source)
    if source is None or source not in _USER_PLATFORMS:
        return ""
    line = f"The user is on {source.display_name}."
    if source is ConversationSource.DESKTOP:
        line += (
            " Desktop tools are available (discover them with retrieve_tools): "
            "take_screenshot, read_clipboard/write_clipboard, open_app, open_url, "
            "list_windows. Use take_screenshot whenever the user references what "
            "they are currently looking at."
        )
    return line


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
        header, account_guidance = CONNECTED_INTEGRATIONS_HEADER, COMMS_MULTI_ACCOUNT_NOTE
    else:
        header = EXECUTOR_ACTIVATION_CONNECTED_INTEGRATIONS_HEADER
        account_guidance = MULTI_ACCOUNT_INSTRUCTION
    return await build_connected_integrations_manifest(
        ctx.user_id, header=header, account_guidance=account_guidance
    )


async def _connected_devices(ctx: SectionContext) -> str:
    if not ctx.user_id:
        return ""
    header = (
        EXECUTOR_CONNECTED_DEVICES_HEADER
        if ctx.tier is AgentTier.EXECUTOR
        else CONNECTED_DEVICES_HEADER
    )
    return await build_connected_devices_manifest(ctx.user_id, header=header)


async def _global_instructions(ctx: SectionContext) -> str:
    if not ctx.user_id:
        return ""
    try:
        content = await get_instructions(ctx.user_id, GLOBAL_INSTRUCTIONS_SCOPE)
    except Exception as e:
        log.warning(
            f"{LogTag.AGENT} Failed to fetch user instructions",
            scope=GLOBAL_INSTRUCTIONS_SCOPE,
            user_id=ctx.user_id,
            error_type=type(e).__name__,
            error=str(e),
        )
        return ""
    return render_user_instructions(GLOBAL_INSTRUCTIONS_SCOPE, content) if content else ""


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
        SectionId.PLATFORM_BANNER,
        PromptSlot.DYNAMIC_STABLE,
        frozenset({AgentTier.COMMS}),
        5,
        _platform_banner,
    ),
    Section(
        SectionId.EXECUTOR_PLATFORM,
        PromptSlot.DYNAMIC_STABLE,
        frozenset({AgentTier.EXECUTOR}),
        5,
        _executor_platform,
    ),
    Section(SectionId.USER_IDENTITY, PromptSlot.DYNAMIC_STABLE, ALL_TIERS, 10, _user_identity),
    Section(SectionId.USER_PREFS, PromptSlot.DYNAMIC_STABLE, ALL_TIERS, 20, _user_prefs),
    Section(
        SectionId.GLOBAL_INSTRUCTIONS,
        PromptSlot.DYNAMIC_STABLE,
        ALL_TIERS,
        22,
        _global_instructions,
    ),
    # Comms only: the executor never opens a conversation. Stable rather than
    # volatile since it's a pure function of signup answers plus a slow
    # counter, byte-identical until the user outgrows it.
    Section(
        SectionId.NEW_USER_GUIDANCE,
        PromptSlot.DYNAMIC_STABLE,
        frozenset({AgentTier.COMMS}),
        25,
        build_new_user_guidance_block,
    ),
    Section(
        SectionId.WORKSPACE_SESSION,
        PromptSlot.DYNAMIC_STABLE,
        WORKER_TIERS,
        30,
        build_workspace_session_banner,
    ),
    Section(
        SectionId.INTEGRATIONS_MANIFEST,
        PromptSlot.DYNAMIC_STABLE,
        frozenset({AgentTier.COMMS, AgentTier.EXECUTOR}),
        40,
        _integrations_manifest,
    ),
    Section(
        SectionId.CONNECTED_DEVICES,
        PromptSlot.DYNAMIC_STABLE,
        frozenset({AgentTier.COMMS, AgentTier.EXECUTOR}),
        45,
        _connected_devices,
    ),
    # Capability info, not retrieval: pure function of user + agent, Redis-
    # cached 12h (was re-read every worker call in the volatile slot). Same
    # once-per-change prefix-invalidation trade integrations_manifest makes.
    Section(SectionId.SKILLS, PromptSlot.DYNAMIC_STABLE, WORKER_TIERS, 70, _skills),
    # Open approval pendings: ledger state that changes on user/agent decisions,
    # not per turn — same stability trade as integrations_manifest above.
    Section(
        SectionId.OPEN_PENDINGS,
        PromptSlot.DYNAMIC_STABLE,
        WORKER_TIERS,
        75,
        build_open_pendings_block,
    ),
    # The memory core's documents, not the whole core: the agenda and the
    # activity journal are split off into their own volatile section, because
    # they are rewritten every turn and would otherwise churn the cached prefix.
    Section(SectionId.CORE_MEMORY, PromptSlot.MEMORY_RECALL, ALL_TIERS, 5, build_core_memory_block),
    Section(
        SectionId.AGENDA_ACTIVITY,
        PromptSlot.MEMORY_RECALL,
        ALL_TIERS,
        10,
        build_agenda_and_activity_block,
    ),
    Section(
        SectionId.MEMORY_RECALL, PromptSlot.MEMORY_RECALL, ALL_TIERS, 20, build_memory_recall_block
    ),
    Section(
        SectionId.GAIA_KNOWLEDGE,
        PromptSlot.MEMORY_RECALL,
        ALL_TIERS,
        30,
        build_gaia_knowledge_block,
    ),
    Section(
        SectionId.TRACKED_TODOS, PromptSlot.MEMORY_RECALL, ALL_TIERS, 50, build_tracked_todos_block
    ),
    # What is going on for the user beside the chat, read once as the turn starts.
    Section(
        SectionId.WORK_STATE,
        PromptSlot.MEMORY_RECALL,
        frozenset({AgentTier.COMMS}),
        54,
        build_work_state_block,
    ),
    Section(
        SectionId.BROWSER_TASK,
        PromptSlot.MEMORY_RECALL,
        frozenset({AgentTier.COMMS}),
        56,
        build_browser_task_block,
    ),
    Section(SectionId.BG_BANNER, PromptSlot.MEMORY_RECALL, ALL_TIERS, 60, build_background_banner),
    Section(
        SectionId.ACTIVE_TODO_BANNER,
        PromptSlot.MEMORY_RECALL,
        ALL_TIERS,
        70,
        build_active_todo_banner,
    ),
)


def sections_for(tier: AgentTier, slot: PromptSlot) -> list[Section]:
    """Return the sections tier gets in slot, in intra-slot order."""
    return sorted(
        (s for s in SECTIONS if s.slot is slot and s.applies(tier)), key=lambda s: s.order
    )
