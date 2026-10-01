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

from app.constants.todos import (
    ACTIVE_TRACKED_SUMMARY_LIMIT,
    EXECUTE_TRACKED_TODO_TASK,
    GAIA_TRACKED_LABEL,
    TodoActivityEvent,
)
from app.db.repositories.todos import todo_repository
from app.models.todo_models import (
    ExternalRef,
    Priority,
    TodoDocument,
    TodoModel,
    TodoResponse,
    TodoUpdate,
)
from app.services.canvas_markdown import canvas_problems, normalize_canvas
from app.services.gaia_tasks_fs import schedule_gaia_tasks_sync
from app.services.storage._vfs_common import folder_name
from app.services.todo_activity import (
    activity_line,
    agent_actor,
    field_change_lines,
    record_activity,
)
from app.services.todo_canvas_storage import (
    append_log,
    build_vfs_label,
    repair_canvas_and_activity,
)
from app.services.todos.errors import CanvasShapeError, SubTodoParentError
from app.services.todos.external_ref_watch import watch_external_ref
from app.services.todos.todo_service import TodoService
from app.services.triggers.subscription_service import teardown_subscriptions
from app.utils.canvas_vector_utils import mark_canvas_completed, store_canvas_embedding
from app.utils.occurrence import occurrence_stamp
from app.utils.redis_utils import RedisPoolManager
from app.workers.queue import enqueue_worker_job
from shared.py.wide_events import log

CANVAS_TEMPLATE = """# {title}

## Standing rules
<!-- the user's instructions for how this todo behaves, one line each with the date given; every run obeys them over its defaults; never removed unless the user retracts one -->

## Key Details
<!-- email addresses, thread IDs, calendar IDs, issue IDs: everything needed to take action -->

## Current State
<!-- what is true RIGHT NOW; rewrite after every action -->

## Context
<!-- accumulated context from signals, related information, decisions made, open questions -->

## Learnings
<!-- written on completion: what worked, what did not, timing insights, reusable patterns -->
"""


async def _discard_unwatched_todo(todo_id: str, user_id: str, watch_error: Exception) -> None:
    """Delete a todo whose watch failed; a failed delete is logged and noted on watch_error."""
    try:
        await TodoService.delete_todo(todo_id, user_id)
    except Exception as delete_error:
        log.error(
            "tracked_todo.unwatched_discard_failed",
            todo_id=todo_id,
            user_id=user_id,
            error=str(delete_error),
            error_type=type(delete_error).__name__,
        )
        watch_error.add_note(f"Deleting the unwatched todo {todo_id} failed too: {delete_error!r}")


async def require_sub_todo_parent(
    user_id: str, parent_todo_id: str, *, child_id: str | None = None
) -> None:
    """Refuse a parent that is not an open, top-level tracked todo of the user.

    child_id names an existing todo being moved under it, which must not be the
    parent itself nor have sub-todos of its own: sub-todos go one level deep.
    """
    parent = (
        await todo_repository.get(parent_todo_id, user_id=user_id)
        if todo_repository.is_valid_id(parent_todo_id)
        else None
    )
    if parent is None:
        raise SubTodoParentError(f"The user has no open tracked todo with the id {parent_todo_id}.")
    if GAIA_TRACKED_LABEL not in parent.labels:
        raise SubTodoParentError(
            f'"{parent.title}" is not a tracked todo, so it cannot have sub-todos.'
        )
    if parent.completed:
        raise SubTodoParentError(f'"{parent.title}" is completed; a sub-todo needs an open parent.')
    if parent.parent_todo_id is not None:
        raise SubTodoParentError(
            f'"{parent.title}" is itself a sub-todo; sub-todos go one level deep.'
        )
    if child_id is None:
        return
    if child_id == parent_todo_id:
        raise SubTodoParentError("A todo cannot be its own parent.")
    if await todo_repository.find_sub_todos(user_id, [child_id]):
        raise SubTodoParentError(f"{child_id} has sub-todos of its own, so it cannot become one.")


async def _active_todo_first(
    docs: list[TodoDocument], user_id: str, active_todo_id: str | None
) -> None:
    """Put the run's own todo first in docs, fetching it when the listing left it out.

    A sub-todo is never in the top-level listing, and neither is a todo past its limit.
    """
    if not active_todo_id:
        return
    for i, d in enumerate(docs):
        if d.id == active_todo_id:
            docs.insert(0, docs.pop(i))
            return
    active = await todo_repository.get(active_todo_id, user_id=user_id)
    if active is not None and not active.completed:
        docs.insert(0, active)


def _format_due_string(due_date: datetime | None, now: datetime) -> str:
    """Render the due-date suffix:  due(Nd),  OVERDUE(Nd), or empty."""
    if not due_date:
        return ""
    days_until = (due_date - now).days
    if days_until < 0:
        return f" OVERDUE({-days_until}d)"
    return f" due({days_until}d)"


def _format_tracked_todo_line(
    doc: TodoDocument, now: datetime, active_todo_id: str | None, open_sub_todos: int
) -> str:
    """Format one tracked-todo doc as a context-injection summary line."""
    age_days = (now - (doc.created_at or now)).days
    last_update = (now - (doc.updated_at or now)).days
    labels = [lbl for lbl in doc.labels if lbl != GAIA_TRACKED_LABEL]
    labels_str = f" [{', '.join(labels)}]" if labels else ""
    prefix = "⭐ ACTIVE " if doc.id == active_todo_id else ""
    family = ""
    if doc.parent_todo_id:
        family = f" | sub-todo of {doc.parent_todo_id}"
    elif open_sub_todos:
        family = f" | {open_sub_todos} open sub-todos"
    return (
        f'  {prefix}"{doc.title}"{labels_str}{_format_due_string(doc.due_date, now)}'
        f" — {age_days}d old, updated {last_update}d ago{family}"
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
        priority: Priority = Priority.NONE,
        labels: list[str] | None = None,
        initial_canvas: str | None = None,
        source_conversation_id: str | None = None,
        notify_on_run: bool | None = None,
        external_ref: ExternalRef | None = None,
        references: list[str] | None = None,
        parent_todo_id: str | None = None,
        schedule: TodoUpdate | None = None,
    ) -> TodoResponse:
        """Create a todo with its canvas, activity and log, indexed in ChromaDB.

        schedule's fields are saved with the insert; external_ref makes it that object's one open,
        watching todo; a sub-todo's runs reach the user only on request. Raises
        ExternalRefTakenError (ref held), SubTodoParentError (unusable parent) and
        CanvasShapeError (initial_canvas breaks a rule normalizing cannot repair).
        """
        if parent_todo_id is not None:
            await require_sub_todo_parent(user_id, parent_todo_id)
        if notify_on_run is None:
            notify_on_run = parent_todo_id is None
        schedule = schedule or TodoUpdate()
        all_labels = list(labels or [])
        if GAIA_TRACKED_LABEL not in all_labels:
            all_labels.append(GAIA_TRACKED_LABEL)

        todo = TodoModel(
            title=title,
            description=description,
            project_id=project_id,
            priority=priority,
            labels=all_labels,
            notify_on_run=notify_on_run,
            references=references or [],
            scheduled_at=schedule.scheduled_at,
            recurrence=schedule.recurrence,
            due_date=schedule.due_date,
            expires_at=schedule.expires_at,
        )
        canvas_content = initial_canvas or CANVAS_TEMPLATE.format(title=title)
        # Models still compose an "## Activity Log" (or skip a section) inside
        # initial_canvas; keep canvas.md in the template's shape from the first write.
        canvas_content, moved_activity = normalize_canvas(canvas_content)
        if problems := canvas_problems(canvas_content):
            raise CanvasShapeError(problems)
        result = await TodoService.create_todo(
            todo, user_id, external_ref=external_ref, parent_todo_id=parent_todo_id
        )
        todo_id = result.id

        vfs_path = build_vfs_label(todo_id)
        now = datetime.now(UTC)
        # Moved legacy entries come first (oldest-first, like the migration); the
        # creation entries stay last so an edit-append has a line to anchor on,
        # and models reach for edit before write.
        origin = f"from conversation {source_conversation_id[:8]}" if source_conversation_id else ""
        created = "\n".join(
            [
                activity_line(TodoActivityEvent.CREATED, origin, at=now),
                *field_change_lines(schedule, by=agent_actor(source_conversation_id), at=now),
            ]
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

        if external_ref is not None:
            try:
                await watch_external_ref(todo_id, user_id, external_ref, ())
            except Exception as watch_error:
                # Unwatched, it would still hold the ref and answer every retry as a duplicate.
                await _discard_unwatched_todo(todo_id, user_id, watch_error)
                raise

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
        """Complete a tracked todo and its open sub-todos: log it, mark done, archive label."""
        doc = await todo_repository.get(todo_id, user_id=user_id)
        if not doc:
            return False

        # Guard against double-completion
        if doc.completed:
            return True

        # Sub-todos first, so a retry after a partial failure finds the parent still open.
        await TrackedTodoService._complete_open_sub_todos(doc, summary)

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

        # Again, for any sub-todo created after the first sweep and before the parent closed.
        await TrackedTodoService._complete_open_sub_todos(doc, summary)
        # A sub-todo reports to its parent: its outcome is in the parent's next run.
        if doc.parent_todo_id:
            await record_activity(
                doc.parent_todo_id,
                user_id,
                TodoActivityEvent.SUB_TODO_COMPLETED,
                f'"{doc.title}" ({todo_id}): {summary}',
            )

        log.info("tracked_todo.completed", todo_id=todo_id, user_id=user_id, summary=summary)
        schedule_gaia_tasks_sync(user_id)
        return True

    @staticmethod
    async def _complete_open_sub_todos(parent: TodoDocument, summary: str) -> None:
        for child in await todo_repository.find_sub_todos(parent.user_id, [parent.id]):
            if not child.completed:
                await TrackedTodoService.complete_tracked_todo(
                    child.id,
                    parent.user_id,
                    summary=f'Parent "{parent.title}" completed: {summary}',
                )

    @staticmethod
    async def get_active_tracked_summary(user_id: str, active_todo_id: str | None = None) -> str:
        """Format active top-level tracked todos, each with its open sub-todo count.

        When active_todo_id is provided, that todo (a sub-todo included) is pinned at
        the top with an ⭐ ACTIVE marker so the agent can identify the run's bound canvas.
        """
        docs = await todo_repository.list_active_tracked(
            user_id, limit=ACTIVE_TRACKED_SUMMARY_LIMIT, top_level=True
        )
        await _active_todo_first(docs, user_id, active_todo_id)
        if not docs:
            return ""

        counts = await todo_repository.count_open_sub_todos(user_id, [doc.id for doc in docs])
        now = datetime.now(UTC)
        lines = ["ACTIVE TRACKED TODOS:"]
        lines.extend(
            _format_tracked_todo_line(doc, now, active_todo_id, counts.get(doc.id, 0))
            for doc in docs
        )
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
        if await repair_canvas_and_activity(
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
        return await repair_canvas_and_activity(
            fresh.id,
            fresh.user_id,
            canvas=canvas,
            activity="\n\n".join(parts),
            expected_updated_at=fresh.updated_at,
        )

    @staticmethod
    async def schedule_execution(
        todo_id: str,
        scheduled_at: datetime,
        *,
        defer_until: datetime | None = None,
    ) -> bool:
        """Queue the run armed for scheduled_at; False when that occurrence is already queued.

        Store scheduled_at on the todo first: the job id dedupes a repeat enqueue,
        and a fire whose todo has moved off its stamp is dropped as stale, which is
        how a reschedule retires the job ARQ cannot cancel. defer_until only delays it.
        """
        # Mongo stores a naive datetime as UTC, so the stamp must name that instant.
        armed_for = scheduled_at if scheduled_at.tzinfo else scheduled_at.replace(tzinfo=UTC)
        stamp = occurrence_stamp(armed_for)
        pool = await RedisPoolManager.get_pool()
        job = await enqueue_worker_job(
            pool,
            EXECUTE_TRACKED_TODO_TASK,
            todo_id,
            scheduled_for=stamp,
            _job_id=f"{EXECUTE_TRACKED_TODO_TASK}:{todo_id}:{stamp}",
            _defer_until=defer_until or armed_for,
        )
        return job is not None

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
