"""GAIA's open tasks as every agent's context lists them, the run's own task pinned first."""

from datetime import UTC, datetime

from app.constants.tasks import Assignee
from app.constants.todos import ACTIVE_TRACKED_SUMMARY_LIMIT
from app.db.repositories.tasks import task_repository
from app.models.task_models import DateWhen, RepeatWhen, TaskDocument
from app.services.tasks.open_state import describe_open_state

OPEN_TASKS_HEADER = "GAIA'S OPEN TASKS:"


async def _pinned_first(
    tasks: list[TaskDocument], user_id: str, active_task_id: str | None
) -> None:
    """Put the run's own task first, fetching it when the listing left it out (a subtask is never in it)."""
    if not active_task_id:
        return
    for i, task in enumerate(tasks):
        if task.id == active_task_id:
            tasks.insert(0, tasks.pop(i))
            return
    active = await task_repository.get(active_task_id, user_id=user_id)
    if active is not None and not active.completed and active.assignee is Assignee.GAIA:
        tasks.insert(0, active)


def _when_words(task: TaskDocument, now: datetime) -> str:
    when = task.when
    if isinstance(when, RepeatWhen):
        return f" repeats {when.rule}"
    if isinstance(when, DateWhen):
        days = (when.at - now).days
        return f" OVERDUE({-days}d)" if days < 0 else f" due({days}d)"
    return ""


def _line(task: TaskDocument, now: datetime, active_task_id: str | None, open_children: int) -> str:
    age = (now - (task.created_at or now)).days
    updated = (now - (task.updated_at or now)).days
    flags = f" [{', '.join(f.value for f in task.status_flags)}]" if task.status_flags else ""
    prefix = "⭐ ACTIVE " if task.id == active_task_id else ""
    family = (
        f" | subtask of {task.parent_id}"
        if task.parent_id
        else f" | {open_children} open subtasks"
        if open_children
        else ""
    )
    return (
        f'  {prefix}"{task.title}"{flags}{_when_words(task, now)} ({age}d old, updated '
        f"{updated}d ago){family} | {describe_open_state(task, now)} | ID: {task.id}"
    )


async def open_tasks_summary(user_id: str, *, active_task_id: str | None) -> str:
    """List GAIA's open top-level tasks with their next step and open subtask counts."""
    tasks = await task_repository.list_open_gaia(
        user_id, limit=ACTIVE_TRACKED_SUMMARY_LIMIT, top_level=True
    )
    await _pinned_first(tasks, user_id, active_task_id)
    if not tasks:
        return ""
    counts = await task_repository.count_open_subtasks(user_id, [task.id for task in tasks])
    now = datetime.now(UTC)
    return "\n".join(
        [
            OPEN_TASKS_HEADER,
            *(_line(task, now, active_task_id, counts.get(task.id, 0)) for task in tasks),
        ]
    )
