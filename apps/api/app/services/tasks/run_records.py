"""A GAIA task's history: one task_runs record per run, and its log for everything between runs.

A run is opened when it starts and closed once with its outcome; a fire that never ran
the task (paused, waiting on a busy chat) is a skipped record. Lifecycle events that are
no run (scheduled, retried, marked failed) are lines in the task's log, the activity.md
the agent reads and writes.
"""

from datetime import UTC, datetime
from uuid import uuid4

from app.constants.tasks import TaskLogEvent, TaskRunStatus, TaskRunTrigger
from app.db.repositories.task_runs import task_run_repository
from app.db.repositories.tasks import task_repository
from app.models.conversation_log_models import TaskRun
from app.models.task_models import TaskDocument
from app.models.task_run_models import TaskRunDocument, TaskRunUpdate


def log_line(event: TaskLogEvent, detail: str, at: datetime | None = None) -> str:
    """Format one engine-written log entry: "- <iso> [event] detail"."""
    return f"- {(at or datetime.now(UTC)).isoformat()} [{event.value}] {detail}".rstrip()


async def record_event(task: TaskDocument, event: TaskLogEvent, detail: str) -> None:
    """Append one lifecycle entry to the task's log."""
    await task_repository.append_log(task.id, task.user_id, suffix=f"{log_line(event, detail)}\n")


async def open_run(task: TaskDocument, run: TaskRun, conversation_id: str) -> TaskRunDocument:
    """Write the record of a run that is starting now."""
    return await task_run_repository.create(
        TaskRunDocument(
            run_id=run.run_id,
            task_id=task.id,
            user_id=task.user_id,
            started_at=datetime.now(UTC),
            conversation_id=conversation_id,
            trigger_type=run.trigger_type,
        )
    )


async def close_run(task: TaskDocument, run: TaskRun, status: TaskRunStatus, error: str) -> None:
    """Close a run that did not deliver a result; a run that never opened gets its record now."""
    if await task_run_repository.complete(
        run.run_id, TaskRunUpdate(status=status, error_message=error)
    ):
        return
    if await task_run_repository.get(run.run_id) is not None:
        return  # already closed: its delivery finished first
    now = datetime.now(UTC)
    await task_run_repository.create(
        TaskRunDocument(
            run_id=run.run_id,
            task_id=task.id,
            user_id=task.user_id,
            status=status,
            started_at=now,
            completed_at=now,
            duration_seconds=0,
            error_message=error,
            trigger_type=run.trigger_type,
        )
    )


async def record_skipped_run(task: TaskDocument, trigger: TaskRunTrigger, reason: str) -> None:
    """Write the record of a fire that came due but did not run the task, and why."""
    now = datetime.now(UTC)
    await task_run_repository.create(
        TaskRunDocument(
            run_id=str(uuid4()),
            task_id=task.id,
            user_id=task.user_id,
            status=TaskRunStatus.SKIPPED,
            started_at=now,
            completed_at=now,
            duration_seconds=0,
            summary=reason,
            trigger_type=trigger.value,
        )
    )
