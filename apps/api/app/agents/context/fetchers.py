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

import asyncio
from datetime import UTC, datetime
import functools
import re
from typing import TypedDict, cast

from app.agents.context.section_context import SectionContext
from app.agents.context.text import (
    BACKGROUND_EXECUTION_BANNER,
    BUILTIN_CAPABILITY_OVERLAPS,
    BUILTIN_OVERLAP_LINE,
    CORE_MEMORY_HEADER,
    GAIA_KNOWLEDGE_HEADER,
    MEMORY_IS_PAST_NOTE,
    MEMORY_RECALL_HEADER,
)
from app.agents.prompts.new_user_prompts import build_new_user_guidance
from app.agents.workspace.paths import session_dir
from app.config.oauth_config import get_integration_by_id
from app.constants.log_tags import LogTag
from app.constants.memory import MEMORY_RECALL_BLOCK_LIMIT
from app.constants.tool_labels import humanize_tool_name
from app.db.repositories.approval_ledger import approval_ledger_repository
from app.db.repositories.conversations import conversation_repository
from app.db.repositories.todos import todo_repository
from app.memory.context import AGENDA_HEADING, RECENT_ACTIVITY_HEADING
from app.memory.engine import memory_engine
from app.memory.mappers import entry_to_note
from app.models.memory_models import MemorySearchResult
from app.models.todo_models import TodoDocument
from app.models.user_models import OnboardingNeed, OnboardingPreferences
from app.services.device.device_service import (
    get_device_manifest,
)
from app.services.gaia_knowledge_service import gaia_knowledge_service
from app.services.integrations.user_integrations import get_connected_integrations_named
from app.services.onboarding.first_question import seeded_chips
from app.services.provider_metadata_service import get_provider_metadata
from app.services.storage._vfs_common import folder_name
from app.services.tools.tools_service import get_integration_tool_list
from app.services.tracked_todo_service import tracked_todo_service
from app.utils.artifact_utils import artifact_url_base
from app.utils.user_preferences_utils import OnboardingPreferencesRecord
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


async def _fetch_core_context(user_id: str) -> str:
    """Read the memory core once, or an empty string.

    Redis-cached inside the engine and invalidated on ingestion; the swallow logs
    its cause so a degraded core is visible in the wide event.
    """
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


#: One in-flight core fetch per (event loop, user): the two core-memory sections
#: share the task instead of each paying the fetch. Keyed by loop so a task bound
#: to a closed loop (tests, reloads) is never awaited from another.
_inflight_core: dict[tuple[asyncio.AbstractEventLoop, str], asyncio.Task[str]] = {}


def _forget_inflight(key: tuple[asyncio.AbstractEventLoop, str], task: asyncio.Task[str]) -> None:
    """Drop the finished fetch, if it is still the registered one.

    Eviction is load-bearing: without it the registry would retain every user's
    core context for the process's life. The task never holds an exception to
    retrieve, because _fetch_core_context catches and returns an empty string.
    """
    if _inflight_core.get(key) is task:
        del _inflight_core[key]


async def _core_context(user_id: str | None) -> str:
    """Return the memory core as the engine renders it, or an empty string.

    A singleflight over the two sections built from it: an assembly pays the core
    read once, and the fetch is evicted on completion so a later assembly reads
    afresh — sharing, not TTL caching.
    """
    if not user_id:
        return ""
    key = (asyncio.get_running_loop(), user_id)
    task = _inflight_core.get(key)
    if task is None:
        task = asyncio.ensure_future(_fetch_core_context(user_id))
        _inflight_core[key] = task
        task.add_done_callback(functools.partial(_forget_inflight, key))
    # Shielded: cancelling one waiter (a client that disconnected mid-turn)
    # must not cancel the shared task under the sibling still waiting on it.
    return await asyncio.shield(task)


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
        # The journal is where a finished task shows up, so it says what it is.
        parts.append(f"{RECENT_ACTIVITY_HEADING}\n{MEMORY_IS_PAST_NOTE}{activity}")
    return "\n\n".join(parts)


async def _recall(user_id: str, query: str) -> MemorySearchResult | None:
    try:
        return await memory_engine.recall(user_id, query, limit=MEMORY_RECALL_BLOCK_LIMIT)
    except Exception as e:
        log.warning(
            "Error retrieving memories",
            error=str(e),
            error_type=type(e).__name__,
            user_id=user_id,
        )
        return None


async def _recall_for_turn(ctx: SectionContext) -> MemorySearchResult | None:
    """Reuse the recall comms made on the user's request; recall on query only when it missed.

    Comms recalled on request_query moments ago, so that call is a cache hit. The
    brief found the same memories on real turns plus noise its template words matched;
    it earns its own recall only when the request matched nothing confidently ("yes do it").
    """
    if not ctx.user_id:
        return None
    if ctx.request_query and ctx.request_query != ctx.query:
        shared = await _recall(ctx.user_id, ctx.request_query)
        reused = shared is not None and shared.has_confident_match
        log.set_ns("dynamic_context", memory_recall_reused=reused)
        if reused:
            return shared
    if not ctx.query:
        return None
    return await _recall(ctx.user_id, ctx.query)


async def build_memory_recall_block(ctx: SectionContext) -> str:
    """Memories relevant to this turn, dated.

    Rendered through entry_to_note so the agent can reason about *when*
    something happened — "how long ago", "which came first" — directly from the
    injected text instead of having to ask.
    """
    results = await _recall_for_turn(ctx)
    if results is None or not results.memories:
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


async def build_tracked_todos_block(ctx: SectionContext) -> str:
    """Active tracked-todo summary, with this run's bound todo pinned.

    Rendered from the list the repository caches under the user's generation, so
    it is never staler than the last write. The pin is applied here because it is
    per-run binding; a user-keyed cache of the pinned form would leak across turns.
    """
    if not ctx.user_id:
        return ""
    try:
        return await tracked_todo_service.get_active_tracked_summary(
            ctx.user_id, active_todo_id=ctx.active_todo_id
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


def _selected_needs(preferences: OnboardingPreferencesRecord) -> list[OnboardingNeed]:
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
    preferences: OnboardingPreferencesRecord = cast(
        OnboardingPreferencesRecord, ctx.user_preferences
    )
    needs = _selected_needs(preferences)
    other_need = preferences.get("other_need")
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
    profession = preferences.get("profession")
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


class _ConnectedIntegration(TypedDict):
    """One row of get_connected_integrations_named: an integration id and its display name."""

    id: str
    name: str


def _dedupe_by_provider(items: list[_ConnectedIntegration]) -> list[_ConnectedIntegration]:
    """One row per provider, keeping whichever row resolved to a display name.

    A connected set can hold two ids for the same account (a legacy
    google_calendar beside today's googlecalendar) — rendering both once gave
    the agent two handoff targets, one resolving to no subagent.
    """
    by_provider: dict[str, _ConnectedIntegration] = {}
    for item in items:
        key = re.sub(r"[^a-z0-9]", "", item["id"].lower())
        held: _ConnectedIntegration | None = by_provider.get(key)
        if held is None or (held["name"] == held["id"] and item["name"] != item["id"]):
            by_provider[key] = item
    return list(by_provider.values())


def _builtin_overlap_lines(items: list[_ConnectedIntegration]) -> list[str]:
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

    Capability awareness only; schemas still come from retrieve_tools. The
    parenthesised id is the integration_id for activate_integration; a row
    collapses to just the id when the name IS the id. A builtin shadowed by
    a connected provider gets its own row above the accounts.
    """
    try:
        items = cast(list[_ConnectedIntegration], await get_connected_integrations_named(user_id))
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
    connected: list[_ConnectedIntegration] = _dedupe_by_provider(items)
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

    Lets the agent route local-file work to the user's own machine instead of the
    cloud sandbox; live status and tool schemas come from list_devices at call time.
    Reads the per-user device manifest, cached for a day and cleared on every
    structural device/server write.
    """
    try:
        entries = await get_device_manifest(user_id)
    except Exception as e:
        log.warning(
            "Error building connected-devices manifest",
            error=str(e),
            error_type=type(e).__name__,
            user_id=user_id,
        )
        return ""
    if not entries:
        return ""
    lines = [header]
    for entry in entries:
        names = ", ".join(entry.servers)
        exposing = f" exposing: {names}" if names else ""
        # Include the id verbatim: it is the device_id run_on_device / the device
        # tools take. Without it the model invents one from the name and the call
        # fails the ownership check.
        lines.append(f"- {entry.name} ({entry.platform}, id: {entry.id}){exposing}")
    return "\n".join(lines)


async def build_provider_metadata_block(integration_id: str | None, user_id: str | None) -> str:
    """Who the user is on this provider — GitHub login, Gmail address, etc.

    Shared by the worker context sections and activate_integration: an
    executor acting on an integration directly needs the same identity a
    worker got, or it does not know which account it is operating.
    """
    if not (integration_id and user_id):
        return ""
    integration = get_integration_by_id(integration_id)
    if not integration or not integration.provider:
        return ""
    try:
        metadata = await get_provider_metadata(user_id, integration.provider)
    except Exception as e:
        log.warning(
            f"{LogTag.AGENT} Failed to fetch provider metadata",
            provider=integration.provider,
            user_id=user_id,
            error_type=type(e).__name__,
            error=str(e),
        )
        return ""
    if not metadata:
        return ""
    lines = "\n".join(f"- {key}: {value}" for key, value in metadata.items())
    return f"USER CONTEXT FOR {integration.name.upper()}:\n{lines}"


async def build_open_pendings_block(ctx: SectionContext) -> str:
    """Open approval pendings for this conversation, oldest first.

    Ledger state, not per-run state: without this a future turn never sees
    what past turns left undecided, and "revoke anything stale" never fires.
    Degrades to nothing (with a warning) rather than failing the turn over an
    enrichment block. Cap keeps a hoarding conversation out of the cache prefix.
    """
    if not ctx.conversation_id:
        return ""
    try:
        pendings = await approval_ledger_repository.list_open(ctx.conversation_id)
    except Exception as e:
        log.warning(
            "open_pendings_fetch_failed",
            error_type=type(e).__name__,
        )
        return ""
    if not pendings:
        return ""
    # Belt-and-suspenders behind the conversation scoping: a foreign row must
    # never render into this user's agent context. Legacy rows without an
    # owner stay visible rather than silently dropping legit pendings.
    if ctx.user_id:
        pendings = [doc for doc in pendings if not doc.user_id or doc.user_id == ctx.user_id]
        if not pendings:
            return ""
    shown = pendings[:10]
    lines = [
        f"- {doc.approval_id} | {doc.tool_name} | {_pending_age(doc.created_at)} | {doc.summary}"
        for doc in shown
    ]
    if len(pendings) > len(shown):
        lines.append(f"(+{len(pendings) - len(shown)} more open)")
    lines.append(
        'If a step is no longer needed, withdraw it with execute(tool_name="revoke", data={"id": "<id>"}).'
    )
    return "OPEN PENDINGS (awaiting the user's decision):\n" + "\n".join(lines)


def _pending_age(created_at: object) -> str:
    """Coarse age bucket for a pending row; unknown when the timestamp is absent.

    Bucketed to the day so the open-pendings block stays byte-stable inside
    the cache-stable context slot (per-minute ages would bust the prompt-cache
    prefix every minute while a pending sits open).
    """
    if not isinstance(created_at, datetime):
        return "?"
    delta = datetime.now(UTC) - created_at
    if delta.days > 0:
        return f"{delta.days}d"
    return "today"
