"""
Tracked todo service — Mongo-backed lifecycle for GAIA's working memory todos.

A tracked todo is a regular todo with:
- vfs_path (display label) set to /workspace/gaia-tasks/{todo_id}
- 'gaia-tracked' label
- canvas_content field (agent-written recall doc: canvas.md)
- activity_content field (chronological log: activity.md; agent + run markers)
- log_content field (system-written audit trail: log.md)

Canvas and activity are indexed together in ChromaDB by the storage layer.

Canvas and log content live on the todo document itself — see
app/services/todo_canvas_storage.py for the storage primitives. No
JuiceFS / FUSE mount is required, so tracked todos work in every dev mode.
"""

from datetime import UTC, datetime

from app.constants.todos import GAIA_TRACKED_LABEL, TodoActivityEvent
from app.db.repositories.todos import todo_repository
from app.models.scheduler_models import DeactivationReason
from app.models.todo_models import Priority, TodoDocument, TodoModel, TodoResponse, TodoUpdate
from app.services.canvas_markdown import normalize_canvas
from app.services.gaia_tasks_fs import schedule_gaia_tasks_sync
from app.services.storage._vfs_common import folder_name
from app.services.todo_activity import activity_line, record_activity
from app.services.todo_canvas_storage import (
    append_log,
    build_vfs_label,
    write_canvas_and_activity,
)
from app.services.todos.todo_service import TodoService
from app.services.triggers.subscription_service import teardown_subscriptions
from app.utils.canvas_vector_utils import mark_canvas_completed, store_canvas_embedding
from app.utils.redis_utils import RedisPoolManager
from app.workers.queue import enqueue_worker_job
from shared.py.wide_events import log

CANVAS_TEMPLATE = """# {title}

## Key Details
<!-- email addresses, thread IDs, calendar IDs, issue IDs: everything needed to take action -->

## Current State
<!-- what is true RIGHT NOW; rewrite after every action -->

## Context
<!-- accumulated context from signals, related information, decisions made, open questions -->

## Learnings
<!-- written on completion: what worked, what did not, timing insights, reusable patterns -->
"""


def _pin_active_todo(docs: list[TodoDocument], active_todo_id: str | None) -> None:
    """Move the matching todo to the front of docs in-place (no-op if not found)."""
    if not active_todo_id:
        return
    for i, d in enumerate(docs):
        if d.id == active_todo_id and i > 0:
            docs.insert(0, docs.pop(i))
            return


def _format_due_string(due_date: datetime | None, now: datetime) -> str:
    """Render the due-date suffix:  due(Nd),  OVERDUE(Nd), or empty."""
    if not due_date:
        return ""
    days_until = (due_date - now).days
    if days_until < 0:
        return f" OVERDUE({-days_until}d)"
    return f" due({days_until}d)"


def _format_tracked_todo_line(doc: TodoDocument, now: datetime, active_todo_id: str | None) -> str:
    """Format one tracked-todo doc as a context-injection summary line."""
    age_days = (now - (doc.created_at or now)).days
    last_update = (now - (doc.updated_at or now)).days
    labels = [lbl for lbl in doc.labels if lbl != GAIA_TRACKED_LABEL]
    labels_str = f" [{', '.join(labels)}]" if labels else ""
    prefix = "⭐ ACTIVE " if doc.id == active_todo_id else ""
    return (
        f'  {prefix}"{doc.title}"{labels_str}{_format_due_string(doc.due_date, now)}'
        f" ({age_days}d old, updated {last_update}d ago)"
        f" | ID: {doc.id} | files: /workspace/gaia-tasks/{folder_name(doc.id, doc.title)}/"
    )


class TrackedTodoService:
    """Manages VFS lifecycle for tracked (GAIA working memory) todos.

    All methods are static — the service holds no instance state. The
    tracked_todo_service singleton is kept for call-site compatibility.
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
        source_conversation_id: str | None = None,
        notify_on_run: bool = True,
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
            notify_on_run=notify_on_run,
        )
        result = await TodoService.create_todo(todo, user_id)
        todo_id = result.id

        vfs_path = build_vfs_label(todo_id)
        canvas_content = initial_canvas or CANVAS_TEMPLATE.format(title=title)
        # Models still compose an "## Activity Log" (or skip a section) inside
        # initial_canvas; keep canvas.md in the template's shape from the first write.
        canvas_content, moved_activity = normalize_canvas(canvas_content)
        now = datetime.now(UTC)
        # Moved legacy entries come first (oldest-first, like the migration); the
        # creation marker stays last so an edit-append has a line to anchor on,
        # and models reach for edit before write.
        created = activity_line(
            TodoActivityEvent.CREATED,
            f"from conversation {source_conversation_id[:8]}" if source_conversation_id else "",
            at=now,
        )
        activity_content = "\n\n".join(p for p in (moved_activity, created) if p)
        log_content = f"# System Log: {title}\n"

        await todo_repository.update(
            todo_id,
            user_id=user_id,
            update=TodoUpdate(
                vfs_path=vfs_path,
                canvas_content=canvas_content,
                activity_content=activity_content,
                log_content=log_content,
                source_conversation_id=source_conversation_id,
            ),
        )

        await store_canvas_embedding(
            todo_id=todo_id,
            canvas_content="\n\n".join(p for p in (canvas_content, activity_content) if p),
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

        await record_activity(todo_id, user_id, TodoActivityEvent.COMPLETED, summary)

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
        """Format active tracked todos for context injection.

        When active_todo_id is provided, that todo is pinned at the top with an
        ⭐ ACTIVE marker so the agent can identify the run's bound canvas.
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
    async def normalize_stored_canvas(doc: TodoDocument) -> bool:
        """Repair a canvas into the template's shape (see normalize_canvas). True when it wrote.

        Activity inside the canvas (legacy sections, append-mode dated entries,
        "Activity Log (append)" and the like) moves to activity_content, first,
        because it predates anything written to activity.md since.
        """
        if not doc.canvas_content:
            return False
        canvas, moved = normalize_canvas(doc.canvas_content)
        if canvas == doc.canvas_content:
            return False
        parts = [p for p in (moved, doc.activity_content) if p]
        if await write_canvas_and_activity(
            doc.id,
            doc.user_id,
            canvas=canvas,
            activity="\n\n".join(parts),
            expected_updated_at=doc.updated_at,
        ):
            return True
        # Lost a revision race (or the snapshot went stale): re-read once and
        # retry against fresh content. A concurrent agent write wins over the
        # migration, so a second mismatch just skips until the next sweep.
        fresh = await todo_repository.get(doc.id, user_id=doc.user_id)
        if fresh is None or not fresh.canvas_content:
            return False
        canvas, moved = normalize_canvas(fresh.canvas_content)
        if canvas == fresh.canvas_content:
            return False
        parts = [p for p in (moved, fresh.activity_content) if p]
        return await write_canvas_and_activity(
            fresh.id,
            fresh.user_id,
            canvas=canvas,
            activity="\n\n".join(parts),
            expected_updated_at=fresh.updated_at,
        )

    @staticmethod
    async def schedule_execution(todo_id: str, scheduled_at: datetime) -> bool:
        """Enqueue an ARQ deferred job to execute this tracked todo at scheduled_at.

        The todo's stored scheduled_at must already name this time: a fire that
        finds it moved is dropped as stale, which is also how a reschedule
        retires the job it replaces (ARQ cannot cancel a deferred job).
        Returns True if the job was enqueued.
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
    async def resume_paused_for(user_id: str, reason: DeactivationReason) -> int:
        """Resume the user's tracked todos the system paused for reason; return the count resumed.

        A run due while paused fires now: a tracked todo treats a missed run as
        work still owed, the way the safety net does for a lost job.
        """
        resumed = 0
        for todo in await todo_repository.find_paused_for_reason(user_id, reason):
            await todo_repository.update(
                todo.id, user_id=user_id, update=TodoUpdate(pause_reason=None)
            )
            if todo.scheduled_at is not None:
                await TrackedTodoService.schedule_execution(
                    todo.id, max(todo.scheduled_at, datetime.now(UTC))
                )
            resumed += 1
        log.set(tracked_todos_resumed=resumed, tracked_todos_resume_reason=reason.value)
        return resumed

    @staticmethod
    async def archive_tracked_todo(todo_id: str, user_id: str, reason: str) -> bool:
        """Archive a tracked todo by marking it completed with a system-generated summary.

        Used by maintenance sweep when a todo expires cleanly (no action needed);
        the completion entry in activity.md carries the reason.
        """
        try:
            return await TrackedTodoService.complete_tracked_todo(
                todo_id, user_id, summary=f"Auto-archived: {reason}"
            )
        except Exception as e:
            log.warning("tracked_todo.archive_failed", todo_id=todo_id, error=str(e))
            return False


tracked_todo_service = TrackedTodoService()
