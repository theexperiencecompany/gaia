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

from app.agents.context.section_context import SectionContext
from app.agents.context.text import (
    BACKGROUND_EXECUTION_BANNER,
    CORE_MEMORY_HEADER,
    GAIA_KNOWLEDGE_HEADER,
    MEMORY_RECALL_HEADER,
)
from app.agents.workspace.paths import session_dir
from app.constants.cache import TRACKED_TODOS_SUMMARY_CACHE_KEY, TRACKED_TODOS_SUMMARY_CACHE_TTL
from app.db.repositories.todos import todo_repository
from app.decorators.caching import Cacheable
from app.memory.context import AGENDA_HEADING, RECENT_ACTIVITY_HEADING
from app.memory.engine import memory_engine
from app.memory.mappers import entry_to_note
from app.models.todo_models import TodoDocument
from app.services.gaia_knowledge_service import gaia_knowledge_service
from app.services.integrations.user_integrations import get_connected_integrations_named
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


async def _core_context(user_id: str | None) -> str:
    """The memory core as the engine renders it, or ``""``.

    Redis-cached inside the engine and invalidated on ingestion, so the two
    sections built from it (the stable documents and the volatile agenda +
    journal) each read it without a second round trip to Mongo.
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
    """The BYTE-STABLE half of the memory core: the user / assistant-conventions
    documents (identity, preferences, routines).

    These are rewritten only by the consolidation pass, never per turn, so they
    belong inside the cached prefix. The agenda and the activity journal are
    split out into their own volatile section below — they churn every turn, and
    inside the prefix they were the dominant per-turn uncached chunk.
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
    return (
        "🎯 ACTIVE TODO (this run is bound to this todo)\n"
        f"   id: {todo.id}\n"
        f"   title: {todo.title or 'Untitled'}\n"
        "\n"
        "   Default write target for this turn: this todo's canvas.\n"
        f'   - Use `update_tracked_todo_canvas(todo_id="{todo.id}", ...)` for any progress, '
        "outcome, or learning from this run.\n"
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


async def build_connected_integrations_manifest(user_id: str, header: str) -> str:
    """One line per connected integration, so the agent knows what it can reach.

    Capability awareness only — detailed tool schemas still come from
    ``retrieve_tools`` at inference time. The parenthesised id doubles as the
    ``subagent_id`` the executor passes to ``handoff``. A line collapses to
    ``- id`` when the name IS the id, so a custom integration never renders the
    same value twice.
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
    lines = [header]
    for item in items:
        iid, name = item["id"], item["name"]
        lines.append(f"- {name} ({iid})" if name and name != iid else f"- {iid}")
    return "\n".join(lines)
