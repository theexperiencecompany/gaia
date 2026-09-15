"""The section bodies: what each piece of context actually renders to.

Each takes the whole SectionContext and returns rendered text or "" —
never raises. That is deliberate and is the one place in this codebase where
swallowing is correct: a context section is enrichment, and failing a user's
whole turn because a recall query timed out trades a degraded answer for no
answer. Every swallow logs the cause, so the failure is visible in the wide
event rather than silent.

A section whose text is nothing but one of these reads is registered against it
directly in sections.SECTIONS; only a section that genuinely branches keeps
a body of its own next to the table.
"""

import re

from app.agents.context.section_context import SectionContext
from app.agents.context.text import (
    BACKGROUND_EXECUTION_BANNER,
    BUILTIN_CAPABILITY_OVERLAPS,
    BUILTIN_OVERLAP_LINE,
    CORE_MEMORY_HEADER,
    GAIA_KNOWLEDGE_HEADER,
    MEMORY_RECALL_HEADER,
)
from app.agents.prompts.new_user_prompts import build_new_user_guidance
from app.agents.workspace.paths import session_dir
from app.constants.cache import TRACKED_TODOS_SUMMARY_CACHE_KEY, TRACKED_TODOS_SUMMARY_CACHE_TTL
from app.constants.tool_labels import humanize_tool_name
from app.db.repositories.conversations import conversation_repository
from app.db.repositories.todos import todo_repository
from app.decorators.caching import Cacheable
from app.memory.context import AGENDA_HEADING, RECENT_ACTIVITY_HEADING
from app.memory.engine import memory_engine
from app.memory.mappers import entry_to_note
from app.models.todo_models import TodoDocument
from app.models.user_models import OnboardingNeed, OnboardingPreferences
from app.services.device.device_service import (
    list_device_servers,
    list_devices as list_devices_service,
)
from app.services.gaia_knowledge_service import gaia_knowledge_service
from app.services.integrations.user_integrations import get_connected_integrations_named
from app.services.onboarding.first_question import seeded_chips
from app.services.storage._vfs_common import folder_name
from app.services.tools.tools_service import get_integration_tool_list
from app.services.tracked_todo_service import tracked_todo_service
from app.utils.artifact_utils import artifact_url_base
from shared.py.wide_events import log


def _split_off_section(context: str, heading: str) -> tuple[str, str]:
    """Split a heading's section off the memory core.

    Returns (everything before the heading, the section body). A heading is
    matched at the very start too, not only after a blank line: a user with
    no stable documents OPENS with a churning section.
    """
    if context.startswith(heading):
        return "", context[len(heading) :]
    marker = f"\n\n{heading}"
    if marker in context:
        before, body = context.split(marker, 1)
        return before, body
    return context, ""


async def _core_context(user_id: str | None) -> str:
    """Return the memory core as the engine renders it, or "".

    Redis-cached inside the engine and invalidated on ingestion, so the two
    sections built from it each read it without a second round trip to Mongo.
    """
    if not user_id:
        return ""
    try:
        return await memory_engine.get_core_context(user_id)
    except Exception as e:
        log.warning(
            "Error retrieving core memory context",
            error=str(e),
            error_type=type(e).__name__,
            user_id=user_id,
        )
        return ""


def _split_core_context(core_context: str) -> tuple[str, str, str]:
    """(stable documents, agenda, recent activity).

    Split from the BACK. get_core_context emits the agenda BEFORE the
    journal, so splitting on the agenda first hands back everything to its right
    — the journal included — as "the agenda", and the journal's own split then
    finds nothing left to match.
    """
    core_context, activity = _split_off_section(core_context, RECENT_ACTIVITY_HEADING)
    core_context, agenda = _split_off_section(core_context, AGENDA_HEADING)
    return core_context, agenda, activity


async def build_core_memory_block(ctx: SectionContext) -> str:
    """Build the document half of the memory core (identity, preferences, routines).

    Deliberately in the volatile TAIL, not the cached prefix: consolidation
    rewrites them DURING conversations, and inside the prefix each rewrite
    pushed the whole conversation out of cache (measured: moving them behind
    the conversation took comms 46.0% -> 59.3%, executor 64.8% -> 75.8%).
    """
    documents, _agenda, _activity = _split_core_context(await _core_context(ctx.user_id))
    return f"{CORE_MEMORY_HEADER}\n{documents}" if documents else ""


async def build_agenda_and_activity_block(ctx: SectionContext) -> str:
    """Build the CHURNING half of the memory core: the current agenda and recent activity journal.

    They sit in the volatile slot together, each under its own heading, so
    the agenda is never read as part of the journal.
    """
    _documents, agenda, activity = _split_core_context(await _core_context(ctx.user_id))
    parts: list[str] = []
    if agenda:
        parts.append(f"{AGENDA_HEADING}{agenda}")
    if activity:
        parts.append(f"{RECENT_ACTIVITY_HEADING}{activity}")
    return "\n\n".join(parts)


async def build_memory_recall_block(ctx: SectionContext) -> str:
    """Memories relevant to this turn, dated.

    Rendered through entry_to_note so the agent can reason about *when*
    something happened — "how long ago", "which came first" — directly from the
    injected text instead of having to ask.
    """
    if not (ctx.user_id and ctx.query):
        return ""
    try:
        results = await memory_engine.recall(ctx.user_id, ctx.query, limit=5)
    except Exception as e:
        log.warning(
            "Error retrieving memories",
            error=str(e),
            error_type=type(e).__name__,
            user_id=ctx.user_id,
        )
        return ""
    if not results.memories:
        return ""
    log.info("Added memories to context", memories_count=len(results.memories))
    notes = "\n".join(f"- {entry_to_note(mem)}" for mem in results.memories)
    return f"{MEMORY_RECALL_HEADER}\n{notes}"


async def build_gaia_knowledge_block(ctx: SectionContext) -> str:
    if not ctx.query:
        return ""
    try:
        results = await gaia_knowledge_service.search_knowledge(query=ctx.query, limit=5)
    except Exception as e:
        log.warning("Error retrieving GAIA knowledge", error=str(e), error_type=type(e).__name__)
        return ""
    if not results:
        return ""
    log.info("Added knowledge items to context", results_count=len(results))
    lines = "\n".join(f"- {result.content}" for result in results)
    return f"{GAIA_KNOWLEDGE_HEADER}\n{lines}"


@Cacheable(key_pattern=TRACKED_TODOS_SUMMARY_CACHE_KEY, ttl=TRACKED_TODOS_SUMMARY_CACHE_TTL)
async def _cached_tracked_todos_summary(user_id: str) -> str:
    return await tracked_todo_service.get_active_tracked_summary(user_id)


async def build_tracked_todos_block(ctx: SectionContext) -> str:
    """Active tracked-todo summary, briefly cached.

    A pinned view is per-run-binding and deliberately skips the cache: it is
    keyed by user alone, so caching the pinned form would show one run's bound
    todo on every other turn until the TTL expired.
    """
    if not ctx.user_id:
        return ""
    try:
        return (
            await tracked_todo_service.get_active_tracked_summary(
                ctx.user_id, active_todo_id=ctx.active_todo_id
            )
            if ctx.active_todo_id
            else await _cached_tracked_todos_summary(ctx.user_id)
        )
    except Exception as e:
        log.warning(
            "Error retrieving tracked todos",
            error=str(e),
            error_type=type(e).__name__,
            user_id=ctx.user_id,
        )
        return ""


#: How many of the user's own conversations still count as "we just met". The
#: live one is included in the count, so 3 covers a first session plus two
#: returns; past that there is real history to lead from and the playbooks stop.
NEW_USER_CONVERSATION_LIMIT = 3


def _selected_needs(preferences: dict[str, object]) -> list[OnboardingNeed]:
    """Return the onboarding needs off a raw preferences bag, in the order picked.

    A value this build does not know (an older client, a renamed need) is
    skipped rather than dropping the whole block.
    """
    raw_needs = preferences.get("needs")
    if not isinstance(raw_needs, list):
        return []
    selected: list[OnboardingNeed] = []
    for raw in raw_needs:
        try:
            selected.append(OnboardingNeed(raw))
        except ValueError:
            log.warning("Unknown onboarding need in preferences", need=str(raw))
    return selected


async def build_new_user_guidance_block(ctx: SectionContext) -> str:
    """Per-need first-conversation playbooks, while the user is still new.

    The needs check runs BEFORE the conversation count, so users who predate
    the persona questions never pay for the lookup at all.
    """
    if not (ctx.user_id and ctx.user_preferences):
        return ""
    needs = _selected_needs(ctx.user_preferences)
    other_need = ctx.user_preferences.get("other_need")
    if not isinstance(other_need, str):
        other_need = None
    if not needs and not other_need:
        return ""
    try:
        conversations = await conversation_repository.count_non_onboarding(ctx.user_id)
    except Exception as e:
        log.warning(
            "Error counting conversations for new-user guidance",
            error=str(e),
            error_type=type(e).__name__,
            user_id=ctx.user_id,
        )
        return ""
    if conversations > NEW_USER_CONVERSATION_LIMIT:
        return ""
    profession = ctx.user_preferences.get("profession")
    # The chips GAIA itself offered at the end of the seeded conversation. Their
    # first message is usually one of them, and without this the model treats a
    # one-word choice as a fragment it has to ask about.
    chips = await seeded_chips(
        ctx.user_id,
        OnboardingPreferences(
            profession=str(profession) if profession else None,
            needs=needs,
            other_need=other_need,
        ),
    )
    return build_new_user_guidance(
        str(profession) if profession else "",
        needs,
        other_need,
        chips,
    )


async def build_background_banner(ctx: SectionContext) -> str:
    return BACKGROUND_EXECUTION_BANNER if ctx.execution_mode == "background" else ""


async def build_workspace_session_banner(ctx: SectionContext) -> str:
    """State the agent's own session directory and the public artifact URL base.

    The agent never otherwise learns its session id, so a weak model
    fabricates one, writing outside the session the artifact watcher scans.
    The URL line lets it link/embed an artifact at all.
    """
    # Only ``vfs_session_id`` is trusted. Falling back to ``thread_id`` would
    # state ``/workspace/sessions/executor_<conv>/``, sending deliverables
    # outside the directory the artifact watcher scans, where they are lost.
    if not ctx.vfs_session_id:
        return ""
    return (
        f"Session directory: {session_dir(ctx.vfs_session_id)}\n"
        f"Public artifact URL: a file at `artifacts/<name>` is served at "
        f"{artifact_url_base(ctx.vfs_session_id)}/<name>"
    )


def format_active_todo_banner(todo: TodoDocument) -> str:
    folder = f"/workspace/gaia-tasks/{folder_name(todo.id, todo.title)}"
    return (
        "🎯 ACTIVE TODO (this run is bound to this todo)\n"
        f"   id: {todo.id}\n"
        f"   title: {todo.title or 'Untitled'}\n"
        f"   files: {folder}/canvas.md, {folder}/activity.md\n"
        "\n"
        "   Default write target for this turn: this todo's files.\n"
        "   - Read canvas.md first. Record progress and outcomes as a dated entry at the end "
        "of activity.md; keep Current State in canvas.md true; learnings go in canvas.md.\n"
        "   - Use `add_memory(...)` ONLY for durable cross-cutting facts unrelated to this "
        "todo (rare).\n"
        "   - To work on a different todo, you must reference it explicitly by id."
    )


async def build_active_todo_banner(ctx: SectionContext) -> str:
    if not (ctx.user_id and ctx.active_todo_id):
        return ""
    try:
        doc = await todo_repository.get(ctx.active_todo_id, user_id=ctx.user_id)
    except Exception as e:
        log.warning("active_todo_banner_fetch_failed", error=str(e))
        return ""
    return format_active_todo_banner(doc) if doc else ""


def _dedupe_by_provider(items: list[dict[str, str]]) -> list[dict[str, str]]:
    """One row per provider, keeping whichever row resolved to a display name.

    A connected set can hold two ids for the same account (a legacy
    google_calendar beside today's googlecalendar) — rendering both once gave
    the agent two handoff targets, one resolving to no subagent.
    """
    by_provider: dict[str, dict[str, str]] = {}
    for item in items:
        key = re.sub(r"[^a-z0-9]", "", item["id"].lower())
        held = by_provider.get(key)
        if held is None or (held["name"] == held["id"] and item["name"] != item["id"]):
            by_provider[key] = item
    return list(by_provider.values())


def _builtin_overlap_lines(items: list[dict[str, str]]) -> list[str]:
    """Rows spelling out the built-ins a connected provider would otherwise mask."""
    names = {item["id"]: item["name"] for item in items}
    lines: list[str] = []
    for overlap in BUILTIN_CAPABILITY_OVERLAPS:
        rivals = [names[pid] for pid in sorted(overlap.provider_ids) if pid in names]
        if rivals:
            lines.append(
                BUILTIN_OVERLAP_LINE.format(
                    description=overlap.description,
                    providers=" or ".join(rivals),
                    subagent_id=overlap.subagent_id,
                )
            )
    return lines


async def build_connected_integrations_manifest(user_id: str, header: str) -> str:
    """One line per connected integration, so the agent knows what it can reach.

    Capability awareness only — tool schemas still come from retrieve_tools
    at inference time. The parenthesised id doubles as the handoff
    subagent_id. A built-in whose job a connected provider is mistaken for
    gets its own row above the accounts.
    """
    try:
        items = await get_connected_integrations_named(user_id)
    except Exception as e:
        log.warning(
            "Error building connected-integrations manifest",
            error=str(e),
            error_type=type(e).__name__,
            user_id=user_id,
        )
        return ""
    if not items:
        return ""
    connected = _dedupe_by_provider(items)
    lines = [header, *_builtin_overlap_lines(connected)]
    for item in connected:
        iid, name = item["id"], item["name"]
        row = f"- {name} ({iid})" if name and name != iid else f"- {iid}"
        lines.append(f"{row}{await _tool_summary(iid)}")
    return "\n".join(lines)


#: How many tool names a manifest row shows. Enough for the model to see what an
#: integration is for ("create issue, list pull requests, ..."), few enough that
#: ten connected integrations stay a screen, not a catalogue.
MANIFEST_TOOL_SAMPLE_SIZE = 5


async def _tool_summary(integration_id: str) -> str:
    """Return ": N tools, e.g. a, b, c" for a connected integration, or "" when it has none.

    Read from the registry (the same catalogue retrieve_tools searches). A
    listing failure keeps the bare row: the connection is real even when
    its tool list isn't readable right now.
    """
    try:
        tools = await get_integration_tool_list(integration_id)
    except Exception as e:
        log.warning(
            "Could not list tools for a connected integration; manifest row stays bare",
            integration_id=integration_id,
            error=str(e),
            error_type=type(e).__name__,
        )
        return ""
    if not tools:
        return ""
    sample = ", ".join(
        humanize_tool_name(tool.name, integration_id).lower()
        for tool in tools[:MANIFEST_TOOL_SAMPLE_SIZE]
    )
    return f": {len(tools)} tools, e.g. {sample}"


async def build_connected_devices_manifest(user_id: str, header: str) -> str:
    """One line per paired device and the servers it exposes.

    Lets the agent know the user has their own machine reachable and route local-file
    work there instead of the cloud sandbox. Capability awareness only — live online
    status and tool schemas come from list_devices / retrieve_tools at call time.
    """
    try:
        devices = await list_devices_service(user_id)
        if not devices:
            return ""
        servers_by_device = await list_device_servers([d.id for d in devices])
    except Exception as e:
        log.warning(
            "Error building connected-devices manifest",
            error=str(e),
            error_type=type(e).__name__,
            user_id=user_id,
        )
        return ""
    lines = [header]
    for device in devices:
        servers = servers_by_device.get(device.id, [])
        names = ", ".join(s.display_name for s in servers)
        exposing = f" exposing: {names}" if names else ""
        # Include the id verbatim: it is the device_id run_on_device / the device
        # tools take. Without it the model invents one from the name and the call
        # fails the ownership check.
        lines.append(f"- {device.name} ({device.platform}, id: {device.id}){exposing}")
    return "\n".join(lines)
