"""The agent's tools for a task's checklist, and for reopening, bulk-closing and deleting tasks."""

from typing import Annotated, Literal

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from app.decorators import with_doc
from app.models.agent_models import get_user_id
from app.schemas.tasks import TaskUpdateRequest
from app.services.tasks import task_service
from app.services.tasks.errors import SubtaskNotFoundError, TaskNotFoundError
from app.templates.docstrings.task_tool_docs import (
    COMPLETE_TASKS,
    DELETE_TASKS,
    EDIT_CHECKLIST,
    REOPEN_TASK,
)

#: What edit_checklist does to one item.
ChecklistChange = Literal["add", "rename", "tick", "untick", "remove"]


def _missing_note(asked: list[str], found: list[str]) -> str:
    missing = [task_id for task_id in asked if task_id not in found]
    return f" Not found: {', '.join(missing)}." if missing else ""


@tool
@with_doc(EDIT_CHECKLIST)
async def edit_checklist(
    config: RunnableConfig,
    task_id: Annotated[str, "Id of the task whose checklist changes"],
    change: Annotated[ChecklistChange, "'add', 'rename', 'tick', 'untick' or 'remove'"],
    item_id: Annotated[
        str | None, "The checklist item's id from get_task; every change but 'add' needs it"
    ] = None,
    title: Annotated[str | None, "The item's text: required for 'add' and 'rename'"] = None,
) -> str:
    user_id = get_user_id(config)
    if change in ("add", "rename") and not title:
        return f"Error: '{change}' needs the item's title."
    if change != "add" and item_id is None:
        return f"Error: '{change}' needs the item_id get_task shows."
    try:
        match change:
            case "add":
                task = await task_service.add_subtask(user_id, task_id, title or "")
                return f"Added '{title}' to the checklist of {task.title} (item id {task.subtasks[-1].id})."
            case "remove":
                task = await task_service.delete_subtask(user_id, task_id, item_id or "")
            case _:
                task = await task_service.update_subtask(
                    user_id,
                    task_id,
                    item_id or "",
                    title=title if change == "rename" else None,
                    completed={"tick": True, "untick": False}.get(change),
                )
    except (TaskNotFoundError, SubtaskNotFoundError) as missing:
        return f"Error: {missing.message}"
    return f"Checklist of {task.title}: item {item_id} {change}{'d' if change.endswith('e') else 'ed'}."


@tool
@with_doc(REOPEN_TASK)
async def reopen_task(
    config: RunnableConfig, task_id: Annotated[str, "Id of the done task to put back on the list"]
) -> str:
    user_id = get_user_id(config)
    try:
        task = await task_service.update_task(user_id, task_id, TaskUpdateRequest(completed=False))
    except TaskNotFoundError as missing:
        return f"Error: {missing.message}"
    return f"Reopened {task.title}."


@tool
@with_doc(COMPLETE_TASKS)
async def complete_tasks(
    config: RunnableConfig,
    task_ids: Annotated[list[str], "Ids of the user's to-dos to tick off, from list_tasks"],
) -> str:
    user_id = get_user_id(config)
    done = await task_service.complete_tasks(user_id, task_ids)
    return f"Ticked off {len(done)} task(s).{_missing_note(task_ids, done)}"


@tool
@with_doc(DELETE_TASKS)
async def delete_tasks(
    config: RunnableConfig,
    task_ids: Annotated[list[str], "Ids of the tasks to delete for good, from list_tasks"],
) -> str:
    user_id = get_user_id(config)
    deleted = await task_service.delete_tasks(user_id, task_ids)
    return f"Deleted {len(deleted)} task(s) and their subtasks.{_missing_note(task_ids, deleted)}"


tools = [edit_checklist, reopen_task, complete_tasks, delete_tasks]
