"""Closing a task, GAIA's or the user's: its open subtasks close with it, and its parent hears.

Subtasks are closed before the parent, so a retry after a partial failure finds the parent
still open, and again after, for one filed while it closed. A closed GAIA task releases the
Composio instances its subscriptions hold. A closed subtask is written
to its GAIA parent's log, and a parent waiting on its subtasks is woken shortly after.
"""

from datetime import UTC, datetime

from app.constants.tasks import Assignee, TaskLogEvent
from app.constants.todos import SUB_TODO_PARENT_WAKE_DELAY, WaitingOn
from app.db.repositories.tasks import task_repository
from app.models.task_models import TaskDocument, TaskUpdate
from app.services.analytics_service import capture
from app.services.tasks.arming import arm_at, arm_task
from app.services.tasks.run_records import record_event
from app.services.tasks.subscriptions import release_subscriptions
from app.services.tasks.todo_rounds import with_round_fields
from shared.py.analytics import UserId
from shared.py.analytics.catalog.tasks import TaskToggled
from shared.py.wide_events import log


async def complete_task(task: TaskDocument, summary: str) -> TaskDocument | None:
    """Close the task and its open subtasks with what came of it; None when it was gone or done."""
    await _complete_open_subtasks(task, summary)
    closing = TaskUpdate(completed=True, completed_at=datetime.now(UTC))
    if task.assignee is Assignee.GAIA:
        closing = closing.model_copy(update={"next_check_at": None, "waiting": None})
    closed = await task_repository.update_if_open(
        task.id, task.user_id, update=with_round_fields(task, closing)
    )
    if closed is None:
        return None
    await arm_task(closed)
    if closed.assignee is Assignee.GAIA:
        await release_subscriptions(closed)
        await record_event(closed, TaskLogEvent.COMPLETED, summary)
    capture(UserId(closed.user_id), TaskToggled(task_id=closed.id, completed=True))
    log.set_ns("task", completed=closed.id)
    await _complete_open_subtasks(closed, summary)
    if closed.parent_id is not None:
        await _report_to_parent(closed, summary)
    return closed


async def _complete_open_subtasks(parent: TaskDocument, summary: str) -> None:
    for child in await task_repository.find_subtasks(parent.user_id, [parent.id]):
        if not child.completed:
            await complete_task(child, f'Parent "{parent.title}" completed: {summary}')


async def _report_to_parent(child: TaskDocument, summary: str) -> None:
    """Write the closed subtask on its GAIA parent's log, and wake the parent if it waits on it."""
    if child.parent_id is None:
        return
    parent = await task_repository.get(child.parent_id, user_id=child.user_id)
    if parent is None or parent.completed or parent.assignee is not Assignee.GAIA:
        return
    await record_event(
        parent, TaskLogEvent.SUBTASK_COMPLETED, f'"{child.title}" ({child.id}): {summary}'
    )
    if parent.waiting is None or parent.waiting.on is not WaitingOn.SUB_TODOS:
        return
    wake_at = datetime.now(UTC) + SUB_TODO_PARENT_WAKE_DELAY
    if parent.next_check_at is not None and parent.next_check_at <= wake_at:
        return
    woken = await task_repository.update_if_next_check_at(
        parent.id,
        parent.user_id,
        expected=parent.next_check_at,
        update=TaskUpdate(next_check_at=wake_at),
    )
    if woken is None:
        log.info("task.parent_rescheduled_before_wake", task_id=parent.id)
        return
    await arm_at(woken.id, wake_at)
