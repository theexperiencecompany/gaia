"""Which task may sit under which: subtasks go one level deep, under an open top-level parent.

A GAIA subtask needs a GAIA parent, which reads its subtasks' states on every run and may
wait on them; a to-do may sit under any open top-level task.
"""

from app.constants.tasks import Assignee
from app.db.repositories.tasks import task_repository
from app.models.task_models import TaskDocument
from app.services.tasks.errors import SubtaskParentError


async def require_subtask_parent(
    user_id: str, parent_id: str, *, assignee: Assignee, child: TaskDocument | None = None
) -> TaskDocument:
    """Return the parent a task of assignee may be filed under; child is a task being moved there."""
    parent = await task_repository.get(parent_id, user_id=user_id)
    if parent is None:
        raise SubtaskParentError(f"The user has no task with the id {parent_id}.")
    if assignee is Assignee.GAIA and parent.assignee is not Assignee.GAIA:
        raise SubtaskParentError(
            f'"{parent.title}" is the user\'s own to-do, so GAIA cannot file subtasks under it.'
        )
    if parent.completed:
        raise SubtaskParentError(f'"{parent.title}" is done; a subtask needs an open parent.')
    if parent.parent_id is not None:
        raise SubtaskParentError(
            f'"{parent.title}" is itself a subtask; subtasks go one level deep.'
        )
    if child is None:
        return parent
    if child.id == parent_id:
        raise SubtaskParentError("A task cannot be its own parent.")
    if child.completed:
        raise SubtaskParentError(f"{child.id} is done; only an open task can become a subtask.")
    if await task_repository.find_subtasks(user_id, [child.id]):
        raise SubtaskParentError(f"{child.id} has subtasks of its own, so it cannot become one.")
    return parent


async def require_reopenable(task: TaskDocument) -> None:
    """Refuse reopening a subtask whose parent is done: it would run outside its parent's cascade."""
    if task.parent_id is None:
        return
    parent = await task_repository.get(task.parent_id, user_id=task.user_id)
    if parent is not None and parent.completed:
        raise SubtaskParentError(
            f"Subtask {task.id} cannot reopen while its parent is done; reopen the parent first."
        )
