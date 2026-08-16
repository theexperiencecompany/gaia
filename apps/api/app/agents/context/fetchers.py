"""The reads behind the context sections.

Each returns rendered text or ``""`` — never raises. That is deliberate and is
the one place in this codebase where swallowing is correct: a context section is
enrichment, and failing a user's whole turn because a recall query timed out
trades a degraded answer for no answer. Every swallow logs the cause, so the
failure is visible in the wide event rather than silent.
"""

from app.agents.context.text import (
    CORE_MEMORY_HEADER,
    GAIA_KNOWLEDGE_HEADER,
    MEMORY_RECALL_HEADER,
)
from app.agents.workspace.paths import session_dir
from app.db.repositories.todos import todo_repository
from app.decorators.caching import Cacheable
from app.memory.engine import memory_engine
from app.memory.mappers import entry_to_note
from app.models.todo_models import TodoDocument
from app.services.gaia_knowledge_service import gaia_knowledge_service
from app.services.integrations.user_integrations import get_connected_integrations_named
from app.services.tracked_todo_service import tracked_todo_service
from app.utils.artifact_utils import artifact_url_base
from shared.py.wide_events import log

#: How long a tracked-todo summary stays cached. Short: the list changes as the
#: agent works, and a stale pin is worse than the lookup it saves.
_TRACKED_TODOS_CACHE_TTL = 60


async def build_core_memory_block(user_id: str) -> str:
    """Always-injected memory core: user/memory/agenda docs plus recent journal."""
    try:
        core_context = await memory_engine.get_core_context(user_id)
    except Exception as e:
        log.warning(
            "Error retrieving core memory context",
            error=str(e),
            error_type=type(e).__name__,
            user_id=user_id,
        )
        return ""
    return f"{CORE_MEMORY_HEADER}\n{core_context}" if core_context else ""


async def build_memory_recall_block(user_id: str, query: str) -> str:
    """Memories relevant to this turn, dated.

    Rendered through ``entry_to_note`` so the agent can reason about *when*
    something happened — "how long ago", "which came first" — directly from the
    injected text instead of having to ask.
    """
    try:
        results = await memory_engine.recall(user_id, query, limit=5)
    except Exception as e:
        log.warning(
            "Error retrieving memories",
            error=str(e),
            error_type=type(e).__name__,
            user_id=user_id,
        )
        return ""
    if not results.memories:
        return ""
    log.info("Added memories to context", memories_count=len(results.memories))
    notes = "\n".join(f"- {entry_to_note(mem)}" for mem in results.memories)
    return f"{MEMORY_RECALL_HEADER}\n{notes}"


async def build_gaia_knowledge_block(query: str) -> str:
    try:
        results = await gaia_knowledge_service.search_knowledge(query=query, limit=5)
    except Exception as e:
        log.warning("Error retrieving GAIA knowledge", error=str(e), error_type=type(e).__name__)
        return ""
    if not results:
        return ""
    log.info("Added knowledge items to context", results_count=len(results))
    lines = "\n".join(f"- {result.content}" for result in results)
    return f"{GAIA_KNOWLEDGE_HEADER}\n{lines}"


@Cacheable(key_pattern="tracked_todos:summary:{user_id}", ttl=_TRACKED_TODOS_CACHE_TTL)
async def _cached_tracked_todos_summary(user_id: str) -> str:
    return await tracked_todo_service.get_active_tracked_summary(user_id)


async def build_tracked_todos_block(user_id: str, active_todo_id: str | None = None) -> str:
    """Active tracked-todo summary, briefly cached.

    A pinned view is per-run-binding and deliberately skips the cache: it is
    keyed by user alone, so caching the pinned form would show one run's bound
    todo on every other turn until the TTL expired.
    """
    if active_todo_id:
        return await tracked_todo_service.get_active_tracked_summary(
            user_id, active_todo_id=active_todo_id
        )
    return await _cached_tracked_todos_summary(user_id)


def build_workspace_session_banner(session_id: str) -> str:
    """State the agent's own session directory and the public artifact URL base.

    The agent never otherwise learns its session id, so a prompt asking it to
    report an absolute ``/workspace/sessions/<id>/...`` path forces a guess — and
    a weak model fabricates one, writing the deliverable outside the session the
    artifact watcher scans, where it is silently lost.

    It also knows a file's workspace path but not the URL the browser fetches it
    from, so without the second line it cannot link or embed an artifact at all.
    """
    return (
        f"Session directory: {session_dir(session_id)}\n"
        f"Public artifact URL: a file at `artifacts/<name>` is served at "
        f"{artifact_url_base(session_id)}/<name>"
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


async def build_active_todo_banner(user_id: str, active_todo_id: str) -> str:
    try:
        doc = await todo_repository.get(active_todo_id, user_id=user_id)
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
