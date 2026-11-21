"""The /tasks API: the user's to-dos and GAIA's tasks, their checklists and bulk actions."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.v1.dependencies.oauth_dependencies import get_user_id
from app.decorators import tiered_rate_limit
from app.schemas.tasks import (
    ChecklistItemCreateRequest,
    ChecklistItemUpdateRequest,
    TaskBulkResponse,
    TaskChatResponse,
    TaskCountsResponse,
    TaskCreateRequest,
    TaskIdsRequest,
    TaskListParams,
    TaskListResponse,
    TaskNotesResponse,
    TaskResponse,
    TaskRunListResponse,
    TaskRunResponse,
    TaskUpdateRequest,
)
from app.services.tasks import task_service
from shared.py.wide_events import log

router = APIRouter()

#: The plan allowance every task write counts against.
TASK_WRITES = "todo_operations"


@router.get("/tasks/counts")
async def get_task_counts(
    response: Response, user_id: Annotated[str, Depends(get_user_id)]
) -> TaskCountsResponse:
    """Count the user's open tasks due today, this week and overdue, and their done ones."""
    response.headers["Cache-Control"] = "private, max-age=10"
    log.set(user={"id": user_id}, task={"operation": "counts"})
    counts = await task_service.task_counts(user_id)
    log.set_ns("task", overdue=counts.overdue)
    return TaskCountsResponse(**counts.model_dump())


@router.get("/tasks")
async def list_tasks(
    params: Annotated[TaskListParams, Depends()], user_id: Annotated[str, Depends(get_user_id)]
) -> TaskListResponse:
    """List the user's tasks, newest first, narrowed by the query."""
    log.set(
        user={"id": user_id},
        task={"operation": "list", "page": params.page, "has_query": bool(params.q)},
    )
    page = await task_service.list_tasks(user_id, params.to_query())
    log.set_ns("task", result_count=len(page.items), total=page.total)
    return TaskListResponse(
        tasks=await task_service.task_responses(user_id, page.items),
        total=page.total,
        page=params.page,
        per_page=params.per_page,
    )


@router.post("/tasks", status_code=status.HTTP_201_CREATED)
@tiered_rate_limit(TASK_WRITES)
async def create_task(
    request: TaskCreateRequest, user_id: Annotated[str, Depends(get_user_id)]
) -> TaskResponse:
    """Make a to-do the user does themselves."""
    log.set(
        user={"id": user_id}, task={"operation": "create", "has_parent": bool(request.parent_id)}
    )
    created = await task_service.create_task(user_id, request)
    log.set_ns("task", id=created.id)
    return await task_service.task_response(user_id, created)


# The literal /tasks/bulk paths are declared before /tasks/{task_id}, which would capture them.
@router.post("/tasks/bulk/complete")
@tiered_rate_limit(TASK_WRITES)
async def bulk_complete_tasks(
    request: TaskIdsRequest, user_id: Annotated[str, Depends(get_user_id)]
) -> TaskBulkResponse:
    """Tick off several tasks at once."""
    log.set(
        user={"id": user_id}, task={"operation": "bulk_complete", "count": len(request.task_ids)}
    )
    done = await task_service.complete_tasks(user_id, request.task_ids)
    log.set_ns("task", succeeded=len(done))
    return TaskBulkResponse(
        succeeded=done, not_found=[t for t in request.task_ids if t not in done]
    )


@router.delete("/tasks/bulk")
@tiered_rate_limit(TASK_WRITES)
async def bulk_delete_tasks(
    request: TaskIdsRequest, user_id: Annotated[str, Depends(get_user_id)]
) -> TaskBulkResponse:
    """Delete several tasks at once, with every subtask under them."""
    log.set(user={"id": user_id}, task={"operation": "bulk_delete", "count": len(request.task_ids)})
    deleted = await task_service.delete_tasks(user_id, request.task_ids)
    log.set_ns("task", succeeded=len(deleted))
    return TaskBulkResponse(
        succeeded=deleted, not_found=[t for t in request.task_ids if t not in deleted]
    )


@router.get("/tasks/{task_id}")
async def get_task(task_id: str, user_id: Annotated[str, Depends(get_user_id)]) -> TaskResponse:
    """Return one of the user's tasks."""
    log.set(user={"id": user_id}, task={"operation": "get", "id": task_id})
    task = await task_service.require_task(user_id, task_id)
    log.set_ns("task", assignee=task.assignee.value)
    return await task_service.task_response(user_id, task)


@router.get("/tasks/{task_id}/runs")
async def list_task_runs(
    task_id: str,
    user_id: Annotated[str, Depends(get_user_id)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> TaskRunListResponse:
    """List the task's runs, newest first, with what each did and how it ended."""
    log.set(user={"id": user_id}, task={"operation": "list_runs", "id": task_id})
    runs, total = await task_service.list_runs(user_id, task_id, limit=limit, offset=offset)
    log.set_ns("task", run_count=len(runs), total_runs=total)
    return TaskRunListResponse(runs=[TaskRunResponse.from_document(r) for r in runs], total=total)


@router.get("/tasks/{task_id}/notes")
async def get_task_notes(
    task_id: str, user_id: Annotated[str, Depends(get_user_id)]
) -> TaskNotesResponse:
    """Return GAIA's notes on the task."""
    log.set(user={"id": user_id}, task={"operation": "get_notes", "id": task_id})
    task = await task_service.require_task(user_id, task_id)
    log.set_ns("task", has_notes=bool(task.notes))
    return TaskNotesResponse(
        notes=task.notes or "", observations=task.observations or "", log=task.log or ""
    )


@router.post("/tasks/{task_id}/conversation")
async def open_task_conversation(
    task_id: str, user_id: Annotated[str, Depends(get_user_id)]
) -> TaskChatResponse:
    """Open the chat a GAIA task's runs execute in, creating it before its first run."""
    log.set(user={"id": user_id}, task={"operation": "open_conversation", "id": task_id})
    conversation_id = await task_service.open_conversation(user_id, task_id)
    log.set_ns("task", conversation_id=conversation_id)
    return TaskChatResponse(conversation_id=conversation_id)


@router.put("/tasks/{task_id}")
@tiered_rate_limit(TASK_WRITES)
async def update_task(
    task_id: str, request: TaskUpdateRequest, user_id: Annotated[str, Depends(get_user_id)]
) -> TaskResponse:
    """Edit a task; fields left out stay as they are."""
    log.set(
        user={"id": user_id},
        task={"operation": "update", "id": task_id, "fields": sorted(request.model_fields_set)},
    )
    updated = await task_service.update_task(user_id, task_id, request)
    log.set_ns("task", completed=updated.completed)
    return await task_service.task_response(user_id, updated)


@router.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
@tiered_rate_limit(TASK_WRITES)
async def delete_task(task_id: str, user_id: Annotated[str, Depends(get_user_id)]) -> None:
    """Delete a task and every subtask under it."""
    log.set(user={"id": user_id}, task={"operation": "delete", "id": task_id})
    await task_service.delete_task(user_id, task_id)
    log.set_ns("task", outcome="deleted")


@router.post("/tasks/{task_id}/subtasks", status_code=status.HTTP_201_CREATED)
@tiered_rate_limit(TASK_WRITES)
async def create_subtask(
    task_id: str, request: ChecklistItemCreateRequest, user_id: Annotated[str, Depends(get_user_id)]
) -> TaskResponse:
    """Add an item to the task's checklist."""
    log.set(user={"id": user_id}, task={"operation": "add_subtask", "id": task_id})
    updated = await task_service.add_subtask(user_id, task_id, request.title)
    log.set_ns("task", checklist_count=len(updated.subtasks))
    return await task_service.task_response(user_id, updated)


@router.put("/tasks/{task_id}/subtasks/{subtask_id}")
@tiered_rate_limit(TASK_WRITES)
async def update_subtask(
    task_id: str,
    subtask_id: str,
    request: ChecklistItemUpdateRequest,
    user_id: Annotated[str, Depends(get_user_id)],
) -> TaskResponse:
    """Rename a checklist item or tick it off."""
    log.set(
        user={"id": user_id},
        task={"operation": "update_subtask", "id": task_id, "subtask_id": subtask_id},
    )
    updated = await task_service.update_subtask(
        user_id, task_id, subtask_id, title=request.title, completed=request.completed
    )
    log.set_ns("task", checklist_count=len(updated.subtasks))
    return await task_service.task_response(user_id, updated)


@router.delete("/tasks/{task_id}/subtasks/{subtask_id}")
@tiered_rate_limit(TASK_WRITES)
async def delete_subtask(
    task_id: str, subtask_id: str, user_id: Annotated[str, Depends(get_user_id)]
) -> TaskResponse:
    """Remove an item from the task's checklist."""
    log.set(
        user={"id": user_id},
        task={"operation": "delete_subtask", "id": task_id, "subtask_id": subtask_id},
    )
    updated = await task_service.delete_subtask(user_id, task_id, subtask_id)
    log.set_ns("task", checklist_count=len(updated.subtasks))
    return await task_service.task_response(user_id, updated)
