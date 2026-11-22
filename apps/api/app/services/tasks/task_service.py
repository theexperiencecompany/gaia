"""The user's tasks: making, reading, editing, ticking off and deleting them, and their checklists.

Every write that can change when a to-do comes round (its date, its repeat, its completion,
its notify switch) recomputes the nudge it owes and arms the task's next time.
"""

import uuid

from app.constants.tasks import Assignee
from app.db.repositories.task_runs import task_run_repository
from app.db.repositories.tasks import task_repository
from app.models.task_models import (
    NoWhen,
    RepeatWhen,
    TaskCounts,
    TaskDocument,
    TaskPage,
    TaskQuery,
    TaskUpdate,
    When,
)
from app.models.task_run_models import TaskRunDocument
from app.models.todo_models import PendingApprovalRef, SubTask, TodoDayWindow
from app.schemas.tasks import TaskCreateRequest, TaskResponse, TaskUpdateRequest
from app.services.analytics_service import capture
from app.services.conversation_service import (
    delete_task_conversations,
    get_or_create_task_conversation,
)
from app.services.hil.pending import pending_approvals_by_task
from app.services.integrations.user_integrations import get_connected_integration_ids
from app.services.tasks.arming import arm_task
from app.services.tasks.completion import complete_task
from app.services.tasks.errors import (
    NoChatError,
    RepeatRuleError,
    SubtaskNotFoundError,
    TaskNotFoundError,
)
from app.services.tasks.family import require_reopenable, require_subtask_parent
from app.services.tasks.subscriptions import release_subscriptions
from app.services.tasks.todo_rounds import first_nudge_at, first_repeat, with_round_fields
from app.services.user_service import get_profile_timezone
from app.utils.auth_utils import require_owner
from app.utils.schedule import InvalidScheduleError, validate_repeat_rule
from shared.py.analytics import UserId
from shared.py.analytics.catalog.tasks import (
    TaskChatOpened,
    TaskCreated,
    TaskDeleted,
    TaskToggled,
    TaskUpdated,
)
from shared.py.wide_events import log


async def _pending_approvals(tasks: list[TaskDocument]) -> dict[str, PendingApprovalRef]:
    """Find the oldest approval each GAIA task's runs wait on, for the jump to its card."""
    gaia_ids = [task.id for task in tasks if task.assignee is Assignee.GAIA]
    return {
        task_id: PendingApprovalRef(
            approval_id=row.approval_id, conversation_id=row.conversation_id
        )
        for task_id, row in (await pending_approvals_by_task(gaia_ids)).items()
    }


async def task_responses(user_id: str, tasks: list[TaskDocument]) -> list[TaskResponse]:
    """Project tasks onto TaskResponse with their open subtask counts, approvals and missing apps."""
    counts = await task_repository.count_open_subtasks(user_id, [task.id for task in tasks])
    pending = await _pending_approvals(tasks)
    needs_apps = any(task.integration_ids for task in tasks)
    connected = await get_connected_integration_ids(user_id) if needs_apps else set()
    return [
        TaskResponse.from_document(
            task,
            open_subtask_count=counts.get(task.id, 0),
            connected=connected,
            pending_approval=pending.get(task.id),
        )
        for task in tasks
    ]


async def task_response(user_id: str, task: TaskDocument) -> TaskResponse:
    (response,) = await task_responses(user_id, [task])
    return response


async def require_task(user_id: str, task_id: str) -> TaskDocument:
    """Return the user's task, or raise TaskNotFoundError."""
    task = await task_repository.get(task_id, user_id=user_id)
    if task is None:
        raise TaskNotFoundError(task_id)
    return task


async def _ready_when(user_id: str, when: When) -> When:
    """Check a repeat's rule and give it its first next time."""
    if not isinstance(when, RepeatWhen):
        return when
    try:
        validate_repeat_rule(when.rule)
    except InvalidScheduleError as e:
        raise RepeatRuleError(e) from e
    # The next time is always worked out here, never taken from the client.
    fresh = when.model_copy(update={"next_run": None})
    return first_repeat(fresh, (await get_profile_timezone(user_id)).value)


def _with_ids(subtasks: list[SubTask]) -> list[SubTask]:
    return [s if s.id else s.model_copy(update={"id": str(uuid.uuid4())}) for s in subtasks]


async def create_task(user_id: str, request: TaskCreateRequest) -> TaskDocument:
    """Make a to-do the user does themselves, filed under parent_id when given."""
    await require_owner(user_id)
    if request.parent_id is not None:
        await require_subtask_parent(user_id, request.parent_id, assignee=Assignee.USER)
    draft = TaskDocument(
        user_id=user_id,
        title=request.title,
        body=request.body,
        assignee=Assignee.USER,
        priority=request.priority,
        subtasks=_with_ids(request.subtasks),
        parent_id=request.parent_id,
        when=await _ready_when(user_id, request.when) if request.when else NoWhen(),
        notify=request.notify,
    )
    draft.nudge_at = first_nudge_at(draft)
    created = await task_repository.create(draft)
    await arm_task(created)
    log.set_ns("task", id=created.id, when_kind=created.when.kind.value)
    capture(
        UserId(user_id),
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


async def list_tasks(user_id: str, query: TaskQuery) -> TaskPage:
    return await task_repository.list_page(user_id=user_id, query=query)


async def task_counts(user_id: str, window: TodoDayWindow) -> TaskCounts:
    return await task_repository.compute_counts(user_id=user_id, window=window)


async def update_task(user_id: str, task_id: str, request: TaskUpdateRequest) -> TaskDocument:
    """Apply the user's edit; ticking a task off closes its subtasks, reopening one stamps it open."""
    current = await require_task(user_id, task_id)
    fields = request.model_dump(exclude_unset=True, exclude={"completed"})
    if request.when is not None:
        fields["when"] = await _ready_when(user_id, request.when)
    if request.completed is False and current.completed:
        await require_reopenable(current)
        fields.update(completed=False, completed_at=None)
    update = with_round_fields(current, TaskUpdate(**fields))
    updated = current
    if update.model_fields_set:
        written = await task_repository.update(task_id, user_id=user_id, update=update)
        if written is None:
            raise TaskNotFoundError(task_id)
        updated = written
        await arm_task(updated)
    if request.completed and not updated.completed:
        updated = await complete_task(updated, "Completed by the user") or await require_task(
            user_id, task_id
        )
    log.set_ns("task", id=task_id, changed=sorted(request.model_fields_set))
    if request.completed is False and current.completed:
        capture(UserId(user_id), TaskToggled(task_id=task_id, completed=False))
    elif changed := sorted(request.model_fields_set - {"completed"}):
        capture(UserId(user_id), TaskUpdated(task_id=task_id, changed_fields=changed))
    return updated


async def _with_subtasks(user_id: str, task_ids: list[str]) -> list[str]:
    """Return task_ids and every task filed under them, at any depth."""
    found = list(dict.fromkeys(task_ids))
    frontier = found
    while frontier:
        children = [c.id for c in await task_repository.find_subtasks(user_id, frontier)]
        frontier = [c for c in children if c not in found]
        found.extend(frontier)
    return found


async def delete_tasks(user_id: str, task_ids: list[str]) -> list[str]:
    """Delete the user's tasks and every subtask under them; returns the requested ids that existed."""
    existing = {task.id for task in await task_repository.find_by_ids(user_id, task_ids)}
    doomed = await _with_subtasks(user_id, [t for t in task_ids if t in existing])
    # The runs, chats and Composio instances first: a failed task delete keeps the task,
    # and a retry deletes all.
    for task in await task_repository.find_by_ids(user_id, doomed):
        await release_subscriptions(task)
    await task_run_repository.delete_for_tasks(user_id, doomed)
    await delete_task_conversations(user_id, doomed)
    deleted = await task_repository.bulk_delete(user_id, doomed) if doomed else 0
    log.set_ns("task", deleted=deleted)
    if deleted:
        capture(UserId(user_id), TaskDeleted(count=deleted))
    return [t for t in task_ids if t in existing]


async def list_runs(
    user_id: str, task_id: str, *, limit: int, offset: int
) -> tuple[list[TaskRunDocument], int]:
    """Return a page of the task's run records, newest first, and their total."""
    await require_task(user_id, task_id)
    return await task_run_repository.list_for_task(task_id, user_id, limit=limit, offset=offset)


async def open_conversation(user_id: str, task_id: str) -> str:
    """Return the id of a GAIA task's chat, creating it when no run has yet."""
    task = await require_task(user_id, task_id)
    if task.assignee is not Assignee.GAIA:
        raise NoChatError(task_id)
    conversation_id = await get_or_create_task_conversation(user_id, task.id, task.title)
    capture(UserId(user_id), TaskChatOpened(task_id=task.id))
    return conversation_id


async def delete_task(user_id: str, task_id: str) -> None:
    if not await delete_tasks(user_id, [task_id]):
        raise TaskNotFoundError(task_id)


async def complete_tasks(user_id: str, task_ids: list[str]) -> list[str]:
    """Tick off each of the user's tasks; returns the ids that existed."""
    done: list[str] = []
    for task_id in dict.fromkeys(task_ids):
        try:
            await update_task(user_id, task_id, TaskUpdateRequest(completed=True))
        except TaskNotFoundError:
            continue
        done.append(task_id)
    return done


async def add_subtask(user_id: str, task_id: str, title: str) -> TaskDocument:
    item = SubTask(id=str(uuid.uuid4()), title=title, completed=False)
    updated = await task_repository.add_subtask(task_id, user_id=user_id, subtask=item)
    if updated is None:
        raise TaskNotFoundError(task_id)
    capture(
        UserId(user_id),
        TaskUpdated(task_id=task_id, changed_fields=["subtasks"], is_checklist=True),
    )
    return updated


async def update_subtask(
    user_id: str,
    task_id: str,
    subtask_id: str,
    *,
    title: str | None,
    completed: bool | None,
) -> TaskDocument:
    current = await require_task(user_id, task_id)
    if not any(s.id == subtask_id for s in current.subtasks):
        raise SubtaskNotFoundError(task_id, subtask_id)
    if title is None and completed is None:
        return current
    updated = await task_repository.set_subtask_fields(
        task_id, user_id=user_id, subtask_id=subtask_id, title=title, completed=completed
    )
    if updated is None:
        raise TaskNotFoundError(task_id)
    if completed is not None:
        capture(
            UserId(user_id), TaskToggled(task_id=task_id, completed=completed, is_checklist=True)
        )
    else:
        capture(
            UserId(user_id),
            TaskUpdated(task_id=task_id, changed_fields=["subtasks"], is_checklist=True),
        )
    return updated


async def delete_subtask(user_id: str, task_id: str, subtask_id: str) -> TaskDocument:
    current = await require_task(user_id, task_id)
    if not any(s.id == subtask_id for s in current.subtasks):
        raise SubtaskNotFoundError(task_id, subtask_id)
    updated = await task_repository.remove_subtask(task_id, user_id=user_id, subtask_id=subtask_id)
    if updated is None:
        raise TaskNotFoundError(task_id)
    capture(
        UserId(user_id),
        TaskUpdated(task_id=task_id, changed_fields=["subtasks"], is_checklist=True),
    )
    return updated
