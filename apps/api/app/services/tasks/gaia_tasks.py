"""GAIA's own tasks: taking one on, and changing what it waits on or where it is filed.

Every write keeps the open-state rule (an open one-off has a next step) and arms the
task's next time. What changed is written to the task's log, with who changed it. The
parent check and the write are two writes, so each is checked again once it lands: a
newborn subtask whose parent closed meanwhile is closed too, a moved one is moved back.
"""

from datetime import UTC, datetime

from app.constants.tasks import Assignee, TaskLogEvent
from app.db.repositories.tasks import task_repository
from app.models.task_models import TaskDocument, TaskUpdate
from app.services.analytics_service import capture
from app.services.tasks.arming import arm_task
from app.services.tasks.completion import complete_task
from app.services.tasks.errors import SubtaskParentError
from app.services.tasks.family import require_subtask_parent
from app.services.tasks.open_state import open_state_problems
from app.services.tasks.run_records import log_line, record_event
from app.services.tasks.search_index import index_task
from app.services.todos.errors import OpenStateError
from app.utils.auth_utils import require_owner
from shared.py.analytics import UserId
from shared.py.analytics.catalog.tasks import TaskCreated
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
    if draft.parent_id is not None:
        await require_subtask_parent(draft.user_id, draft.parent_id, assignee=Assignee.GAIA)
    if problems := open_state_problems(draft, datetime.now(UTC)):
        raise OpenStateError(problems)
    draft.log = f"{log_line(TaskLogEvent.CREATED, f'{_plan_words(draft)}, by {by}')}\n"
    created = await task_repository.create(draft)
    await arm_task(created)
    await index_task(created)
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
    if created.parent_id is not None and not await _still_files(created, created.parent_id):
        await complete_task(created, "Its parent was completed while it was being created.")
    return created


async def update_gaia_task(task: TaskDocument, update: TaskUpdate, *, by: str) -> TaskDocument:
    """Apply GAIA's change to its task; refused with OpenStateError when it would leave no next step."""
    moving_to = update.parent_id if "parent_id" in update.model_fields_set else None
    if moving_to is not None:
        await require_subtask_parent(task.user_id, moving_to, assignee=task.assignee, child=task)
    after = task.updated_by(update)
    if problems := open_state_problems(after, datetime.now(UTC)):
        raise OpenStateError(problems)
    updated = await task_repository.update(task.id, user_id=task.user_id, update=update)
    if updated is None:
        raise LookupError(f"task {task.id} was deleted before GAIA's change landed")
    await arm_task(updated)
    if moving_to is not None and not await _still_files(updated, moving_to):
        await task_repository.update(
            task.id, user_id=task.user_id, update=TaskUpdate(parent_id=None)
        )
        await index_task(updated.model_copy(update={"parent_id": None}))
        raise SubtaskParentError(
            f"The parent was completed meanwhile, so moving task {task.id} under it was rolled "
            "back. Reopen the parent first, or pick an open one."
        )
    await index_task(updated)
    if {"waiting", "next_check_at"} & update.model_fields_set:
        await record_event(
            updated, TaskLogEvent.WAITING_CHANGED, f"{_plan_words(updated)}, by {by}"
        )
    return updated


async def _still_files(task: TaskDocument, parent_id: str) -> bool:
    try:
        await require_subtask_parent(task.user_id, parent_id, assignee=task.assignee)
    except SubtaskParentError:
        return False
    return True
