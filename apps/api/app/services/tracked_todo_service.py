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
    EXECUTE_TRACKED_TODO_TASK,
    SUB_TODO_PARENT_WAKE_DELAY,
    TodoActivityEvent,
    WaitingOn,
)
from app.db.repositories.todos import todo_repository
from app.models.scheduler_models import DeactivationReason
from app.models.todo_models import (
    TodoDocument,
    TodoUpdate,
)
from app.services.canvas_markdown import (
    normalize_canvas,
)
from app.services.todo_activity import (
    record_activity,
)
from app.services.todo_canvas_storage import (
    append_log,
    build_vfs_label,
    repair_notes,
)
from app.services.triggers.subscription_service import teardown_subscriptions
from app.services.triggers.todo_trigger_window import release_trigger_events_held_while_paused
from app.utils.canvas_vector_utils import (
    set_canvas_completed,
)
from app.utils.occurrence import occurrence_stamp
from app.utils.redis_utils import RedisPoolManager
from app.workers.queue import enqueue_worker_job
from shared.py.wide_events import log


class TrackedTodoService:
    """Manages VFS lifecycle for tracked (GAIA working memory) todos.

    All methods are static — the service holds no instance state. The
    tracked_todo_service singleton is kept for call-site compatibility.
    """

    @staticmethod
    async def complete_tracked_todo(todo_id: str, user_id: str, summary: str) -> bool:
        """Complete a tracked todo and its open sub-todos: log it, mark it done, stop its watches."""
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

        # Derived, never the stored one: legacy docs carry a host-side /users/<uid>/todos/<id>
        # label this heals. The repository's cache refresh shows the completion at once.
        await todo_repository.update(
            todo_id,
            user_id=user_id,
            update=TodoUpdate(completed=True, completed_at=now, vfs_path=build_vfs_label(todo_id)),
        )

        await set_canvas_completed(todo_id, completed=True)

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
            await TrackedTodoService._wake_waiting_parent(doc.parent_todo_id, user_id)

        log.info("tracked_todo.completed", todo_id=todo_id, user_id=user_id, summary=summary)
        return True

    @staticmethod
    async def _wake_waiting_parent(parent_id: str, user_id: str) -> None:
        """Run a parent that waits on its sub-todos soon after one of them completes."""
        parent = await todo_repository.get(parent_id, user_id=user_id)
        if parent is None or parent.completed or parent.waiting_on is not WaitingOn.SUB_TODOS:
            return
        wake_at = datetime.now(UTC) + SUB_TODO_PARENT_WAKE_DELAY
        if parent.scheduled_at is not None and parent.scheduled_at <= wake_at:
            return
        await todo_repository.update(
            parent_id, user_id=user_id, update=TodoUpdate(scheduled_at=wake_at)
        )
        await TrackedTodoService.schedule_execution(parent_id, wake_at)

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
        notes = TodoUpdate(canvas_content=canvas, activity_content="\n\n".join(parts))
        if await repair_notes(doc.id, doc.user_id, notes, expected_updated_at=doc.updated_at):
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
        notes = TodoUpdate(canvas_content=canvas, activity_content="\n\n".join(parts))
        repaired = await repair_notes(
            fresh.id, fresh.user_id, notes, expected_updated_at=fresh.updated_at
        )
        return repaired is not None

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
    async def _rearm_resumed(todo: TodoDocument) -> None:
        """Queue a resumed todo's due run now and replay the trigger events held while it was paused.

        The job is armed for the stored occurrence so the stale-fire guard runs it; when
        a job for that same occurrence is still queued, it is the run and none is added.
        """
        if todo.scheduled_at is not None:
            await TrackedTodoService.schedule_execution(
                todo.id, todo.scheduled_at, defer_until=max(todo.scheduled_at, datetime.now(UTC))
            )
        await release_trigger_events_held_while_paused(todo.id)

    @staticmethod
    async def resume_paused_for(user_id: str, reason: DeactivationReason) -> int:
        """Resume the user's tracked todos the system paused for reason; return the count resumed.

        A run due while paused fires now: a tracked todo treats a missed run as
        work still owed, the way the safety net does for a lost job. One that
        cannot resume does not stop the rest; their failures are raised together.
        """
        resumed = 0
        failures: list[Exception] = []
        for todo in await todo_repository.find_paused_for_reason(user_id, reason):
            try:
                await todo_repository.update(
                    todo.id, user_id=user_id, update=TodoUpdate(pause_reason=None)
                )
                try:
                    await TrackedTodoService._rearm_resumed(todo)
                except Exception:
                    # Re-paused so the resume retry, which finds todos by this reason, re-arms it.
                    await todo_repository.update(
                        todo.id, user_id=user_id, update=TodoUpdate(pause_reason=reason)
                    )
                    raise
            except Exception as e:  # the rest of the user's todos must still resume
                log.warning(
                    "tracked_todo.resume_failed",
                    todo_id=todo.id,
                    user_id=user_id,
                    error=str(e),
                    error_type=type(e).__name__,
                )
                failures.append(e)
                continue
            resumed += 1
        log.set(tracked_todos_resumed=resumed, tracked_todos_resume_reason=reason.value)
        if failures:
            raise ExceptionGroup(
                f"{len(failures)} paused tracked todo(s) could not resume", failures
            )
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
