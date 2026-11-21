"""GAIA's own tasks: taking one on, changing what it waits on, and closing it.

Every write keeps the open-state rule (an open one-off has a next step) and arms the
task's next time. What changed is written to the task's log, with who changed it.
"""

from datetime import UTC, datetime

from app.constants.tasks import Assignee, TaskLogEvent
from app.db.repositories.tasks import task_repository
from app.models.task_models import TaskDocument, TaskUpdate
from app.services.analytics_service import capture
from app.services.tasks.arming import arm_task
from app.services.tasks.open_state import open_state_problems
from app.services.tasks.run_records import log_line, record_event
from app.services.todos.errors import OpenStateError
from app.utils.auth_utils import require_owner
from shared.py.analytics import UserId
from shared.py.analytics.catalog.tasks import TaskCreated, TaskToggled
from shared.py.wide_events import log


def _plan_words(task: TaskDocument) -> str:
    waiting = task.waiting
    parts = [f"waiting on {waiting.on.value}"] if waiting else []
    if waiting is not None and waiting.question is not None:
        parts.append(f'asked "{waiting.question.text}"')
    if task.next_check_at is not None:
        parts.append(f"next check {task.next_check_at.isoformat()}")
    return ", ".join(parts) or "no next step"


async def create_gaia_task(draft: TaskDocument, *, by: str) -> TaskDocument:
    """Take on a task GAIA does; refused with OpenStateError when it would have no next step."""
    if draft.assignee is not Assignee.GAIA:
        raise ValueError("create_gaia_task takes GAIA's tasks only")
    await require_owner(draft.user_id)
    if problems := open_state_problems(draft, datetime.now(UTC)):
        raise OpenStateError(problems)
    draft.log = f"{log_line(TaskLogEvent.CREATED, f'{_plan_words(draft)}, by {by}')}\n"
    created = await task_repository.create(draft)
    await arm_task(created)
    log.set_ns("task", id=created.id, assignee=created.assignee.value)
    capture(
        UserId(created.user_id),
        TaskCreated(
            task_id=created.id,
            assignee=created.assignee.value,
            when_kind=created.when.kind.value,
            priority=created.priority.value,
            has_body=bool(created.body),
            checklist_count=len(created.subtasks),
            is_subtask=created.parent_id is not None,
        ),
    )
    return created


async def update_gaia_task(task: TaskDocument, update: TaskUpdate, *, by: str) -> TaskDocument:
    """Apply GAIA's change to its task; refused with OpenStateError when it would leave no next step."""
    after = task.updated_by(update)
    if problems := open_state_problems(after, datetime.now(UTC)):
        raise OpenStateError(problems)
    updated = await task_repository.update(task.id, user_id=task.user_id, update=update)
    if updated is None:
        raise LookupError(f"task {task.id} was deleted before GAIA's change landed")
    await arm_task(updated)
    if {"waiting", "next_check_at"} & update.model_fields_set:
        await record_event(
            updated, TaskLogEvent.WAITING_CHANGED, f"{_plan_words(updated)}, by {by}"
        )
    return updated


async def complete_gaia_task(task: TaskDocument, summary: str) -> TaskDocument | None:
    """Close GAIA's task with what came of it; None when it was gone or already closed."""
    closed = await task_repository.update_if_open(
        task.id,
        task.user_id,
        update=TaskUpdate(
            completed=True,
            completed_at=datetime.now(UTC),
            next_check_at=None,
            waiting=None,
        ),
    )
    if closed is None:
        return None
    await record_event(closed, TaskLogEvent.COMPLETED, summary)
    capture(UserId(closed.user_id), TaskToggled(task_id=closed.id, completed=True))
    log.set_ns("task", completed=closed.id)
    return closed
