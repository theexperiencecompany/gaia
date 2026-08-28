"""
Tracked todo service — Mongo-backed lifecycle for GAIA's working memory todos.

A tracked todo is a regular todo with:
- vfs_path (display label) set to /workspace/gaia-tasks/{todo_id}
- 'gaia-tracked' label
- canvas_content field (agent-written brain) indexed in ChromaDB
- log_content field (system-written audit trail)

Canvas and log content live on the todo document itself — see
``app/services/todo_canvas_storage.py`` for the storage primitives. No
JuiceFS / FUSE mount is required, so tracked todos work in every dev mode.
"""

from datetime import UTC, datetime

from app.constants.todos import GAIA_TRACKED_LABEL
from app.db.repositories.todos import todo_repository
from app.models.todo_models import Priority, TodoDocument, TodoModel, TodoResponse, TodoUpdate
from app.services.gaia_tasks_fs import schedule_gaia_tasks_sync
from app.services.todo_canvas_storage import (
    append_log,
    build_vfs_label,
    read_canvas,
    write_canvas,
)
from app.services.todos.todo_service import TodoService
from app.services.triggers.subscription_service import teardown_subscriptions
from app.utils.canvas_vector_utils import (
    mark_canvas_completed,
    store_canvas_embedding,
    update_canvas_embedding,
)
from app.utils.redis_utils import RedisPoolManager
from app.workers.queue import enqueue_worker_job
from shared.py.wide_events import log

CANVAS_TEMPLATE = """# {title}

## Key Details
<!-- email addresses, thread IDs, calendar IDs, issue IDs — everything needed to take action -->

## Current State
<!-- what's true RIGHT NOW — updated after every action -->

## Activity Log
<!-- which agent did what, which tools it used, what the outcome was — add entries HERE, not in Learnings -->

## Timeline
<!-- chronological list of actions taken and results -->

## Context
<!-- accumulated context from signals, related information, decisions made -->

## Learnings
<!-- written on completion: what worked, what didn't, key decisions, timing insights, optimizations for next time -->
"""


def _pin_active_todo(docs: list[TodoDocument], active_todo_id: str | None) -> None:
    """Move the matching todo to the front of `docs` in-place (no-op if not found)."""
    if not active_todo_id:
        return
    for i, d in enumerate(docs):
        if d.id == active_todo_id and i > 0:
            docs.insert(0, docs.pop(i))
            return


def _format_due_string(due_date: datetime | None, now: datetime) -> str:
    """Render the due-date suffix: ` due(Nd)`, ` OVERDUE(Nd)`, or empty."""
    if not due_date:
        return ""
    days_until = (due_date - now).days
    if days_until < 0:
        return f" OVERDUE({-days_until}d)"
    return f" due({days_until}d)"


# Capture everything under the "## Key Details" heading up to the next "## "
# heading (or end of text). A tempered greedy token — "any char that does not
# begin a new section" — avoids a reluctant quantifier entirely.


def _format_tracked_todo_line(doc: TodoDocument, now: datetime, active_todo_id: str | None) -> str:
    """Format one tracked-todo doc as a context-injection summary line."""
    age_days = (now - (doc.created_at or now)).days
    last_update = (now - (doc.updated_at or now)).days
    labels = [lbl for lbl in doc.labels if lbl != GAIA_TRACKED_LABEL]
    labels_str = f" [{', '.join(labels)}]" if labels else ""
    prefix = "⭐ ACTIVE " if doc.id == active_todo_id else ""
    return (
        f'  {prefix}"{doc.title}"{labels_str}{_format_due_string(doc.due_date, now)}'
        f" — {age_days}d old, updated {last_update}d ago"
        f" | ID: {doc.id}"
    )


class TrackedTodoService:
    """Manages VFS lifecycle for tracked (GAIA working memory) todos.

    All methods are static — the service holds no instance state. The
    ``tracked_todo_service`` singleton is kept for call-site compatibility.
    """

    @staticmethod
    async def create_tracked_todo(
        user_id: str,
        title: str,
        description: str | None = None,
        project_id: str | None = None,
        due_date: datetime | None = None,
        priority: Priority = Priority.NONE,
        labels: list[str] | None = None,
        initial_canvas: str | None = None,
    ) -> TodoResponse:
        """Create a todo with VFS canvas and ChromaDB indexing.

        1. Creates a regular todo with 'gaia-tracked' label
        2. Initializes the canvas + log on the todo doc
        3. Sets vfs_path on the todo document
        4. Indexes canvas in ChromaDB
        """
        all_labels = list(labels or [])
        if GAIA_TRACKED_LABEL not in all_labels:
            all_labels.append(GAIA_TRACKED_LABEL)

        todo = TodoModel(
            title=title,
            description=description,
            project_id=project_id,
            due_date=due_date,
            priority=priority,
            labels=all_labels,
        )
        result = await TodoService.create_todo(todo, user_id)
        todo_id = result.id

        vfs_path = build_vfs_label(todo_id)
        canvas_content = initial_canvas or CANVAS_TEMPLATE.format(title=title)
        now = datetime.now(UTC)
        log_content = (
            f"# System Log: {title}\n\n"
            f"## {now.isoformat()} [CREATED]\n"
            f"- Source: agent\n"
            f"- Labels: {', '.join(all_labels)}\n"
        )

        await todo_repository.update(
            todo_id,
            user_id=user_id,
            update=TodoUpdate(
                vfs_path=vfs_path, canvas_content=canvas_content, log_content=log_content
            ),
        )

        await store_canvas_embedding(
            todo_id=todo_id,
            canvas_content=canvas_content,
            user_id=user_id,
            title=title,
            labels=all_labels,
        )

        result.vfs_path = vfs_path
        log.info(
            "tracked_todo.created",
            todo_id=todo_id,
            user_id=user_id,
            title=title,
            vfs_path=vfs_path,
        )
        schedule_gaia_tasks_sync(user_id)
        return result

    @staticmethod
    async def complete_tracked_todo(todo_id: str, user_id: str, summary: str) -> bool:
        """Complete a tracked todo: append completion to log, mark done, archive label."""
        doc = await todo_repository.get(todo_id, user_id=user_id)
        if not doc:
            return False

        # Guard against double-completion
        if doc.completed:
            return True

        now = datetime.now(UTC)

        await append_log(
            todo_id,
            user_id,
            f"\n## {now.isoformat()} [COMPLETED]\n- Summary: {summary}\n",
        )

        # Always derive the archived label — never persist a stored one back.
        # Legacy docs still carry the host-side /users/<uid>/todos/<id> format;
        # deriving here heals them on completion instead of re-saving the leak.
        archive_path = build_vfs_label(todo_id, archived=True)

        # The repository refreshes the entity cache and bumps the generation, so
        # the frontend reflects completion immediately — no manual invalidation.
        await todo_repository.update(
            todo_id,
            user_id=user_id,
            update=TodoUpdate(completed=True, completed_at=now, vfs_path=archive_path),
        )

        await mark_canvas_completed(todo_id)

        # A completed todo must stop watching. Teardown lives here rather than at
        # the callers (tool, sweep, worker) so no completion path can forget it.
        await teardown_subscriptions(todo_id, user_id, reason="completed")

        log.info("tracked_todo.completed", todo_id=todo_id, user_id=user_id, summary=summary)
        schedule_gaia_tasks_sync(user_id)
        return True

    @staticmethod
    async def get_active_tracked_summary(user_id: str, active_todo_id: str | None = None) -> str:
        """Formatted summary of active tracked todos for context injection.

        When active_todo_id is provided, that todo is pinned at the top with
        an ⭐ ACTIVE marker so the agent can quickly identify the run's
        bound canvas.
        """
        docs = await todo_repository.list_active_tracked(user_id, limit=15)
        if not docs:
            return ""

        _pin_active_todo(docs, active_todo_id)

        now = datetime.now(UTC)
        lines = ["ACTIVE TRACKED TODOS:"]
        lines.extend(_format_tracked_todo_line(doc, now, active_todo_id) for doc in docs)
        return "\n".join(lines)

    @staticmethod
    async def append_canvas_timeline(todo_id: str, user_id: str, entry: str) -> bool:
        """Append a line to the canvas Timeline section.

        Called by code (not agent) to guarantee a paper trail for scheduled runs
        regardless of what the LLM writes. If the canvas has a "## Timeline"
        section, the line is inserted at the top of its body; otherwise a new
        section is appended at the end of the canvas.
        """
        try:
            current = await read_canvas(todo_id, user_id) or ""
        except Exception as e:
            log.warning(
                "tracked_todo.canvas_read_for_timeline_failed", todo_id=todo_id, error=str(e)
            )
            return False
        if not current:
            return False

        line = entry if entry.startswith("- ") else f"- {entry}"
        heading = "## Timeline"
        heading_pos = current.find(f"\n{heading}")

        if heading_pos == -1:
            new_canvas = current.rstrip() + f"\n\n{heading}\n{line}\n"
        else:
            insert_pos = heading_pos + len(f"\n{heading}")
            new_canvas = current[:insert_pos] + f"\n{line}" + current[insert_pos:]

        try:
            await write_canvas(todo_id, user_id, new_canvas)
        except Exception as e:
            log.warning("tracked_todo.canvas_timeline_write_failed", todo_id=todo_id, error=str(e))
            return False
        return True

    @staticmethod
    async def system_log(todo_id: str, user_id: str, event_type: str, details: str) -> None:
        """Append a system log entry to a tracked todo's log.

        Called by code (not agent) for audit trail. Agent writes to canvas.
        """
        now = datetime.now(UTC)
        await append_log(
            todo_id,
            user_id,
            f"\n## {now.isoformat()} [{event_type}]\n- {details}\n",
        )

    @staticmethod
    async def reindex_canvas(todo_id: str, user_id: str) -> bool:
        """Re-index a todo's canvas in ChromaDB after the agent writes to it."""
        doc = await todo_repository.get(todo_id, user_id=user_id)
        if not doc:
            return False

        canvas_content = doc.canvas_content
        if not canvas_content:
            return False

        return await update_canvas_embedding(
            todo_id=todo_id,
            canvas_content=canvas_content,
            user_id=user_id,
            title=doc.title,
            labels=doc.labels,
        )

    @staticmethod
    async def schedule_execution(todo_id: str, scheduled_at: datetime) -> bool:
        """Enqueue an ARQ deferred job to execute this tracked todo at scheduled_at.

        Returns True if job was enqueued successfully, False otherwise.
        """
        try:
            pool = await RedisPoolManager.get_pool()
            await enqueue_worker_job(
                pool,
                "execute_tracked_todo",
                todo_id,
                _defer_until=scheduled_at,
            )
            return True
        except Exception as e:
            log.warning("tracked_todo.schedule_failed", todo_id=todo_id, error=str(e))
            return False

    @staticmethod
    async def reschedule_execution(todo_id: str, new_scheduled_at: datetime) -> bool:
        """Cancel any existing ARQ job for this todo and enqueue a new one.

        Note: ARQ does not support cancelling deferred jobs by argument.
        We enqueue a new job; the task itself uses a Redis lock to prevent
        double-execution. This is safe — at most one execution fires per lock window.
        """
        return await TrackedTodoService.schedule_execution(todo_id, new_scheduled_at)

    @staticmethod
    async def archive_tracked_todo(todo_id: str, user_id: str, reason: str) -> bool:
        """Archive a tracked todo by marking it completed with a system-generated summary.

        Used by maintenance sweep when a todo expires cleanly (no action needed).
        Logs the archival reason to log.md before completing.
        """
        try:
            await TrackedTodoService.system_log(
                todo_id,
                user_id,
                "auto_archived",
                f"Archived by maintenance sweep: {reason}",
            )
            return await TrackedTodoService.complete_tracked_todo(
                todo_id, user_id, summary=f"Auto-archived: {reason}"
            )
        except Exception as e:
            log.warning("tracked_todo.archive_failed", todo_id=todo_id, error=str(e))
            return False


tracked_todo_service = TrackedTodoService()
