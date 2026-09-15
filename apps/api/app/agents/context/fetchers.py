"""The section bodies: what each piece of context actually renders to.

Each takes the whole ``SectionContext`` and returns rendered text or ``""`` —
never raises. That is deliberate and is the one place in this codebase where
swallowing is correct: a context section is enrichment, and failing a user's
whole turn because a recall query timed out trades a degraded answer for no
answer. Every swallow logs the cause, so the failure is visible in the wide
event rather than silent.

A section whose text is nothing but one of these reads is registered against it
directly in ``sections.SECTIONS``; only a section that genuinely branches keeps
a body of its own next to the table.
"""

import asyncio
import functools
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
from app.agents.workspace.paths import session_dir
from app.db.repositories.todos import todo_repository
from app.memory.context import AGENDA_HEADING, RECENT_ACTIVITY_HEADING
from app.memory.engine import memory_engine
from app.memory.mappers import entry_to_note
from app.models.todo_models import TodoDocument
from app.services.device.device_service import get_device_manifest
from app.services.gaia_knowledge_service import gaia_knowledge_service
from app.services.integrations.user_integrations import get_connected_integrations_named
from app.services.storage._vfs_common import folder_name
from app.services.tracked_todo_service import tracked_todo_service
from app.utils.artifact_utils import artifact_url_base
from shared.py.wide_events import log


def _split_off_section(context: str, heading: str) -> tuple[str, str]:
    """Split a heading's section off the memory core.

    Returns ``(everything before the heading, the section body)``. A heading is
    matched at the very start too, not only after a blank line: the core of a
    user with no stable documents OPENS with a churning section, and requiring
    the blank line would file it as stable and put per-turn bytes back in the
    cached prefix — for exactly the users the split exists to protect.
    """
    if context.startswith(heading):
        return "", context[len(heading) :]
    marker = f"\n\n{heading}"
    if marker in context:
        before, body = context.split(marker, 1)
        return before, body
    return context, ""


async def _fetch_core_context(user_id: str) -> str:
    """Read the memory core once, or ``""``.

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


#: One in-flight core fetch per (event loop, user). The two core-memory sections
#: run in the same ``asyncio.gather`` and would otherwise each pay the whole
#: fetch; sharing the task pays it once. Keyed by loop so a task bound to a
#: closed loop (tests, reloads) is never awaited from another.
_inflight_core: dict[tuple[asyncio.AbstractEventLoop, str], asyncio.Task[str]] = {}


def _forget_inflight(key: tuple[asyncio.AbstractEventLoop, str], task: asyncio.Task[str]) -> None:
    """Drop the finished fetch, if it is still the registered one.

    Eviction is load-bearing, not cleanup: without it the registry would retain
    every user's core context for the process's life. Nothing consumes the task's
    result — ``_fetch_core_context`` catches and returns ``""``, so it never holds
    an exception to retrieve.
    """
    if _inflight_core.get(key) is task:
        del _inflight_core[key]


async def _core_context(user_id: str | None) -> str:
    """The memory core as the engine renders it, or ``""``.

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
    return await task


def _split_core_context(core_context: str) -> tuple[str, str, str]:
    """``(stable documents, agenda, recent activity)``.

    Split from the BACK. ``get_core_context`` emits the agenda BEFORE the
    journal, so splitting on the agenda first hands back everything to its right
    — the journal included — as "the agenda", and the journal's own split then
    finds nothing left to match.
    """
    core_context, activity = _split_off_section(core_context, RECENT_ACTIVITY_HEADING)
    core_context, agenda = _split_off_section(core_context, AGENDA_HEADING)
    return core_context, agenda, activity


async def build_core_memory_block(ctx: SectionContext) -> str:
    """The document half of the memory core: the user / assistant-conventions
    documents (identity, preferences, routines).

    Deliberately in the volatile TAIL, not the cached prefix, even though the
    documents change less often than the agenda/journal half: consolidation
    rewrites them DURING conversations, and inside the prefix each rewrite
    pushed the whole conversation out of the cache behind it (measured on the
    real graph: moving them behind the conversation took comms 46.0% -> 59.3%
    and the executor 64.8% -> 75.8%). The tail re-send is the known price;
    see the placement note on ``SECTIONS`` in ``sections.py``.
    """
    documents, _agenda, _activity = _split_core_context(await _core_context(ctx.user_id))
    return f"{CORE_MEMORY_HEADER}\n{documents}" if documents else ""


async def build_agenda_and_activity_block(ctx: SectionContext) -> str:
    """The CHURNING half of the memory core: the current agenda and the recent
    activity journal.

    They sit in the volatile slot together, each under its own heading, so the
    agenda a user gets asked about is never read as part of the journal.
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

    Rendered through ``entry_to_note`` so the agent can reason about *when*
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


async def build_tracked_todos_block(ctx: SectionContext) -> str:
    """Active tracked-todo summary, with this run's bound todo pinned.

    The summary is rendered from the user-scoped list the repository caches under
    the user's generation — cleared by every todo write, so it is never staler
    than the last write. The pin is applied here because it is per-run binding,
    not per-user state, and a user-keyed cache of the pinned form would leak one
    run's binding onto every other turn.
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


async def build_background_banner(ctx: SectionContext) -> str:
    return BACKGROUND_EXECUTION_BANNER if ctx.execution_mode == "background" else ""


async def build_workspace_session_banner(ctx: SectionContext) -> str:
    """State the agent's own session directory and the public artifact URL base.

    The agent never otherwise learns its session id, so a prompt asking it to
    report an absolute ``/workspace/sessions/<id>/...`` path forces a guess — and
    a weak model fabricates one, writing the deliverable outside the session the
    artifact watcher scans, where it is silently lost.

    It also knows a file's workspace path but not the URL the browser fetches it
    from, so without the second line it cannot link or embed an artifact at all.
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

    A connected set can hold two ids for the same account — a legacy
    ``google_calendar`` beside today's ``googlecalendar`` — and only the
    registered one resolves to a name. Rendering both handed the agent two
    handoff targets for one account, one of which resolves to no subagent at
    all. Ids that share no provider are untouched, so nothing is ever dropped.
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

    Capability awareness only — detailed tool schemas still come from
    ``retrieve_tools`` at inference time. The parenthesised id doubles as the
    ``subagent_id`` the executor passes to ``handoff``. A line collapses to
    ``- id`` when the name IS the id, so a custom integration never renders the
    same value twice.

    A built-in whose job a connected provider is mistaken for gets its own row
    above the accounts, because a capability the agent cannot see in this list
    is one it attributes to whatever it can see.
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
        lines.append(f"- {name} ({iid})" if name and name != iid else f"- {iid}")
    return "\n".join(lines)


async def build_connected_devices_manifest(user_id: str, header: str) -> str:
    """One line per paired device and the servers it exposes, so the agent knows
    the user has their own machine reachable and routes local-file work there
    instead of the cloud sandbox. Capability awareness only - live online status
    and tool schemas come from list_devices / retrieve_tools at call time.

    Reads the per-user device manifest, which the service caches for a day and
    clears on every structural device/server write.
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
