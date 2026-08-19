import asyncio
from datetime import UTC, datetime, timedelta
from typing import Annotated
import uuid

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Response, status

from app.api.v1.dependencies.oauth_dependencies import (
    get_current_user,
    get_user_id,
    get_user_timezone_from_preferences,
)
from app.constants.general import MAX_PAGE_NUMBER
from app.constants.log_tags import LogTag
from app.db.redis import delete_cache, get_cache, set_cache
from app.db.repositories.projects import project_repository
from app.db.repositories.todos import todo_repository
from app.decorators import tiered_rate_limit
from app.models.todo_models import (
    BulkMoveRequest,
    BulkOperationResponse,
    BulkUpdateRequest,
    Priority,
    ProjectCreate,
    ProjectResponse,
    SearchMode,
    SubTask,
    SubtaskCreateRequest,
    SubtaskUpdateRequest,
    TodoCanvasResponse,
    TodoCounts,
    TodoLabelCount,
    TodoListResponse,
    TodoModel,
    TodoResponse,
    TodoSearchParams,
    TodoUpdateRequest,
    TodoWorkflowGenerationResponse,
    TodoWorkflowGenerationStatus,
    TodoWorkflowStatus,
    TodoWorkflowStatusResponse,
    UpdateProjectRequest,
)
from app.models.user_models import AuthenticatedUser
from app.services.analytics_service import AnalyticsEvents, capture_context_event
from app.services.todo_canvas_storage import read_canvas
from app.services.todos.todo_service import ProjectService, TodoService
from app.services.tracked_todo_service import tracked_todo_service
from app.services.workflow.service import WorkflowService
from shared.py.wide_events import log

router = APIRouter()


# Counts endpoint for efficient dashboard data
@router.get("/todos/counts")
async def get_todo_counts(
    response: Response, user_id: Annotated[str, Depends(get_user_id)]
) -> TodoCounts:
    """
    Get all todo counts for dashboard/sidebar in a single efficient call.
    Returns inbox count, today count, upcoming count, and completed count.
    """
    response.headers["Cache-Control"] = "private, max-age=10"
    log.set(user={"id": user_id}, todo={"operation": "counts"})
    try:
        inbox = await project_repository.get_default_inbox(user_id)
        inbox_project_id = inbox.id if inbox else "no_inbox_found"
        counts = await todo_repository.compute_counts(
            user_id=user_id, inbox_project_id=inbox_project_id
        )
        return counts

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve counts: {e}",
        ) from e


# Labels endpoint — dedicated aggregation for most-used labels
@router.get("/todos/labels")
async def get_todo_labels(
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    limit: int = 10,
) -> list[TodoLabelCount]:
    """Get most-used labels for the current user's todos."""
    log.set(user={"id": user["user_id"]}, todo={"operation": "list_labels"})
    labels = await todo_repository.top_labels(user_id=user["user_id"], limit=limit)
    log.set_ns("todo", result_count=len(labels))
    return labels


# Main Todo CRUD Endpoints
@router.get("/todos", response_model=TodoListResponse)
async def list_todos(
    # Keyword-only: FastAPI binds query parameters by NAME, so the star costs
    # nothing at the wire and keeps the signature honest about how it is called.
    *,
    # Search parameters
    q: str | None = Query(None, description="Search query"),
    mode: SearchMode = Query(
        SearchMode.HYBRID, description="Search mode: text, semantic, or hybrid"
    ),
    # Filter parameters
    project_id: str | None = Query(None),
    completed: bool | None = Query(None),
    priority: Priority | None = Query(None),
    has_due_date: bool | None = Query(None),
    overdue: bool | None = Query(None),
    labels: list[str] | None = Query(None),
    # Date range filters
    due_after: datetime | None = Query(None, description="Due date after this date"),
    due_before: datetime | None = Query(None, description="Due date before this date"),
    # Special date filters
    due_today: bool = Query(False, description="Only todos due today"),
    due_this_week: bool = Query(False, description="Only todos due this week"),
    # Pagination
    page: int = Query(1, ge=1, le=MAX_PAGE_NUMBER),
    per_page: int = Query(50, ge=1, le=100),
    # Options
    include_stats: bool = Query(False, description="Include statistics in response"),
    user: AuthenticatedUser = Depends(get_current_user),
) -> TodoListResponse:
    """
    List todos with comprehensive filtering and search options.

    This endpoint consolidates all todo retrieval operations:
    - Search (text, semantic, or hybrid)
    - Filtering by various criteria
    - Date-based queries (today, this week, custom range)
    - Pagination with metadata
    - Optional statistics
    """
    filters_applied = []
    if q:
        filters_applied.append("query")
    if project_id:
        filters_applied.append("project")
    if completed is not None:
        filters_applied.append("completed")
    if priority:
        filters_applied.append("priority")
    if labels:
        filters_applied.append("labels")
    if due_today:
        filters_applied.append("due_today")
    if due_this_week:
        filters_applied.append("due_this_week")
    if due_after or due_before:
        filters_applied.append("date_range")

    log.set(
        user={"id": user["user_id"]},
        todo={
            "operation": "list",
            "search_mode": mode.value,
            "query": q,
            "page": page,
            "per_page": per_page,
            "filters_applied": filters_applied,
            "project_id": project_id,
        },
    )

    # Handle special date filters
    if due_today:
        today = datetime.now(UTC).date()
        due_after = datetime.combine(today, datetime.min.time()).replace(tzinfo=UTC)
        due_before = datetime.combine(today, datetime.max.time()).replace(tzinfo=UTC)
    elif due_this_week:
        today = datetime.now(UTC)
        due_after = today
        due_before = today + timedelta(days=7)

    params = TodoSearchParams(
        q=q,
        mode=mode,
        project_id=project_id,
        completed=completed,
        priority=priority,
        has_due_date=has_due_date,
        overdue=overdue,
        due_date_start=due_after,
        due_date_end=due_before,
        labels=labels,
        page=page,
        per_page=per_page,
        include_stats=include_stats,
    )

    try:
        result = await TodoService.list_todos(user["user_id"], params)
        # set_ns: log.set(todo={...}) would clobber the search context set above
        log.set_ns("todo", result_count=len(result.data))
        return result
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve todos",
        ) from e


@router.post("/todos", response_model=TodoResponse, status_code=status.HTTP_201_CREATED)
@tiered_rate_limit("todo_operations")
async def create_todo(
    todo: TodoModel, user: AuthenticatedUser = Depends(get_current_user)
) -> TodoResponse:
    """Create a new todo. If no project is specified, it will be added to Inbox."""
    log.set(
        user={"id": user["user_id"]},
        todo={
            "operation": "create",
            "priority": todo.priority.value,
            "has_due_date": todo.due_date is not None,
            "project_id": todo.project_id,
        },
    )
    try:
        return await TodoService.create_todo(todo, user["user_id"])
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create todo",
        ) from e


# Bulk Operations
# These literal ``/todos/bulk`` paths MUST be declared before the parameterized
# ``/todos/{todo_id}`` routes below: FastAPI matches in declaration order, so if
# ``PUT/DELETE /todos/{todo_id}`` came first they would capture ``/todos/bulk``
# with todo_id="bulk" and 500 instead of running the bulk operation.
@router.put("/todos/bulk", response_model=BulkOperationResponse)
@tiered_rate_limit("todo_operations")
async def bulk_update_todos(
    request: BulkUpdateRequest, user: AuthenticatedUser = Depends(get_current_user)
) -> BulkOperationResponse:
    """
    Bulk update multiple todos with the same changes.

    Example:
    ```json
    {
        "todo_ids": ["id1", "id2", "id3"],
        "updates": {
            "completed": true,
            "priority": "high"
        }
    }
    ```
    """
    log.set(
        user={"id": user["user_id"]},
        todo={"operation": "bulk_update", "bulk_count": len(request.todo_ids)},
    )
    try:
        result = await TodoService.bulk_update_todos(request, user["user_id"])
        capture_context_event(AnalyticsEvents.TODO_UPDATED, {"bulk_count": len(request.todo_ids)})
        return result
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Bulk update failed",
        ) from e


@router.post("/todos/bulk/move", response_model=BulkOperationResponse)
@tiered_rate_limit("todo_operations")
async def bulk_move_todos(
    request: BulkMoveRequest, user: AuthenticatedUser = Depends(get_current_user)
) -> BulkOperationResponse:
    """Move multiple todos to a different project."""
    log.set(
        user={"id": user["user_id"]},
        todo={
            "operation": "bulk_move",
            "bulk_count": len(request.todo_ids),
            "project_id": request.project_id,
        },
    )
    try:
        return await TodoService.bulk_move_todos(request, user["user_id"])
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Bulk move failed"
        ) from e


@router.delete("/todos/bulk", response_model=BulkOperationResponse)
@tiered_rate_limit("todo_operations")
async def bulk_delete_todos(
    todo_ids: list[str] = Body(..., min_length=1, max_length=100),
    user: AuthenticatedUser = Depends(get_current_user),
) -> BulkOperationResponse:
    """Delete multiple todos."""
    log.set(
        user={"id": user["user_id"]},
        todo={"operation": "bulk_delete", "bulk_count": len(todo_ids)},
    )
    try:
        return await TodoService.bulk_delete_todos(todo_ids, user["user_id"])
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Bulk delete failed",
        ) from e


# Special mark complete endpoint for convenience
@router.post("/todos/bulk/complete", response_model=BulkOperationResponse)
@tiered_rate_limit("todo_operations")
async def bulk_complete_todos(
    todo_ids: list[str] = Body(..., min_length=1, max_length=100),
    user: AuthenticatedUser = Depends(get_current_user),
) -> BulkOperationResponse:
    """Mark multiple todos as completed (convenience endpoint)."""
    log.set(
        user={"id": user["user_id"]},
        todo={"operation": "bulk_complete", "bulk_count": len(todo_ids)},
    )
    request = BulkUpdateRequest(
        todo_ids=todo_ids,
        updates=TodoUpdateRequest(completed=True),
    )
    try:
        result = await TodoService.bulk_update_todos(request, user["user_id"])
        capture_context_event(AnalyticsEvents.TODO_TOGGLED, {"bulk_count": len(todo_ids)})
        return result
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Bulk complete failed",
        ) from e


@router.get("/todos/{todo_id}", response_model=TodoResponse)
async def get_todo(
    todo_id: str, user: AuthenticatedUser = Depends(get_current_user)
) -> TodoResponse:
    """Get a specific todo by ID."""
    log.set(user={"id": user["user_id"]}, todo={"operation": "get", "id": todo_id})
    try:
        return await TodoService.get_todo(todo_id, user["user_id"])
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve todo",
        ) from e


@router.get("/todos/{todo_id}/canvas")
async def get_todo_canvas(
    todo_id: str, user: Annotated[AuthenticatedUser, Depends(get_current_user)]
) -> TodoCanvasResponse:
    """Return the canvas markdown for a tracked todo."""
    log.set(user={"id": user["user_id"]}, todo={"operation": "get_canvas", "id": todo_id})
    content = await read_canvas(todo_id, user["user_id"])
    if content is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Todo not found")
    return TodoCanvasResponse(content=content)


@router.put("/todos/{todo_id}", response_model=TodoResponse)
@tiered_rate_limit("todo_operations")
async def update_todo(
    todo_id: str, updates: TodoUpdateRequest, user: AuthenticatedUser = Depends(get_current_user)
) -> TodoResponse:
    """Update a todo."""
    log.set(
        user={"id": user["user_id"]},
        todo={
            "operation": "update",
            "id": todo_id,
            "completion_toggled": updates.completed is not None,
        },
    )
    try:
        updated_todo = await TodoService.update_todo(todo_id, updates, user["user_id"])

        # If this is a tracked todo and scheduled_at changed, reschedule ARQ job
        if updates.scheduled_at is not None and updated_todo.vfs_path:
            try:
                await tracked_todo_service.reschedule_execution(todo_id, updates.scheduled_at)
            except Exception as e:
                log.warning(
                    f"{LogTag.TODO} Failed to reschedule todo after update",
                    todo_id=todo_id,
                    user_id=user["user_id"],
                    error_type=type(e).__name__,
                    error=str(e),
                )

        return updated_todo
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update todo",
        ) from e


@router.delete("/todos/{todo_id}", status_code=status.HTTP_204_NO_CONTENT)
@tiered_rate_limit("todo_operations")
async def delete_todo(todo_id: str, user: AuthenticatedUser = Depends(get_current_user)) -> None:
    """Delete a todo."""
    log.set(user={"id": user["user_id"]}, todo={"operation": "delete", "id": todo_id})
    try:
        await TodoService.delete_todo(todo_id, user["user_id"])
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete todo",
        ) from e


# Workflow Generation Endpoint
@router.post("/todos/{todo_id}/workflow")
@tiered_rate_limit("todo_operations")
async def generate_workflow(
    todo_id: str,
    user_id: Annotated[str, Depends(get_user_id)],
    user_timezone: str = Depends(get_user_timezone_from_preferences),
) -> TodoWorkflowGenerationResponse:
    """Generate a workflow for a todo (background generation + WebSocket notification).

    This endpoint returns immediately with 'generating' status. The frontend should
    display a skeleton and listen for the 'workflow.generated' WebSocket event.
    """
    from app.services.workflow.queue_service import WorkflowQueueService

    log.set(
        user={"id": user_id},
        todo={"operation": "generate_workflow", "id": todo_id},
    )
    try:
        todo: TodoResponse = await TodoService.get_todo(todo_id, user_id)

        # Check if workflow already exists for this todo
        if todo.workflow_id:
            existing_workflow = await WorkflowService.get_workflow(todo.workflow_id, user_id)
            if existing_workflow and existing_workflow.steps and len(existing_workflow.steps) > 0:
                return TodoWorkflowGenerationResponse(
                    status=TodoWorkflowGenerationStatus.EXISTS,
                    workflow=existing_workflow,
                    message="Workflow already exists for this todo",
                )
            # Empty or failed workflow — delete it and allow regeneration
            if existing_workflow and existing_workflow.id:
                await WorkflowService.delete_workflow(existing_workflow.id, user_id)
            await todo_repository.clear_workflow_id(todo_id, user_id=user_id)

        # Invalidate cached workflow status so next poll reflects generating state
        await delete_cache(f"workflow_status:{user_id}:{todo_id}")

        # Queue background generation - will send WebSocket event when complete
        success = await WorkflowQueueService.queue_todo_workflow_generation(
            todo_id=todo_id,
            user_id=user_id,
            title=todo.title,
            description=todo.description or "",
        )

        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to queue workflow generation",
            )

        return TodoWorkflowGenerationResponse(
            status=TodoWorkflowGenerationStatus.GENERATING,
            todo_id=todo_id,
            message="Workflow generation started. Listen for 'workflow.generated' WebSocket event.",
        )

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate workflow",
        ) from e


@router.get("/todos/{todo_id}/workflow-status")
async def get_workflow_status(
    todo_id: str, response: Response, user_id: Annotated[str, Depends(get_user_id)]
) -> TodoWorkflowStatusResponse:
    """
    Get the standalone workflow for a todo.
    Returns the workflow if it exists, otherwise returns None.
    Detects generating state when:
    - Workflow generation is queued (Redis flag)
    - Workflow exists but has no steps yet
    """
    response.headers["Cache-Control"] = "private, max-age=15"
    log.set(
        user={"id": user_id},
        todo={"operation": "get_workflow_status", "id": todo_id},
    )
    try:
        from app.services.workflow.queue_service import WorkflowQueueService
        from app.services.workflow.service import WorkflowService

        wf_cache_key = f"workflow_status:{user_id}:{todo_id}"
        cached_wf: TodoWorkflowStatusResponse | None = await get_cache(
            wf_cache_key, model=TodoWorkflowStatusResponse
        )
        if cached_wf:
            return cached_wf

        # Parallelize independent fetch + generating check
        todo, is_generating = await asyncio.gather(
            TodoService.get_todo(todo_id, user_id),
            WorkflowQueueService.is_workflow_generating(todo_id),
        )

        # Get standalone workflow if workflow_id exists
        workflow = None
        has_workflow = False
        workflow_status = TodoWorkflowStatus.NOT_STARTED

        # Check if workflow generation is queued/pending (Redis flag)
        if is_generating:
            workflow_status = TodoWorkflowStatus.GENERATING
        elif todo.workflow_id:
            workflow = await WorkflowService.get_workflow(todo.workflow_id, user_id)

            if workflow:
                # Workflow exists - check if steps are generated
                has_steps = workflow.steps and len(workflow.steps) > 0
                if has_steps:
                    workflow_status = TodoWorkflowStatus.COMPLETED
                    has_workflow = True
                elif await WorkflowQueueService.is_workflow_generating(todo_id):
                    is_generating = True
                    workflow_status = TodoWorkflowStatus.GENERATING
                else:
                    # Workflow exists but empty steps and not generating = failed
                    workflow_status = TodoWorkflowStatus.FAILED

        wf_result = TodoWorkflowStatusResponse(
            todo_id=todo_id,
            has_workflow=has_workflow,
            is_generating=is_generating,
            workflow_status=workflow_status,
            workflow=workflow if has_workflow else None,
        )
        if not is_generating:
            await set_cache(wf_cache_key, wf_result, ttl=60, model=TodoWorkflowStatusResponse)
        return wf_result
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get workflow status",
        ) from e


# Project Endpoints
@router.get("/projects", response_model=list[ProjectResponse])
async def list_projects(
    user: AuthenticatedUser = Depends(get_current_user),
) -> list[ProjectResponse]:
    """List all projects with todo counts."""
    log.set(user={"id": user["user_id"]}, todo={"operation": "list_projects"})
    try:
        return await ProjectService.list_projects(user["user_id"])
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve projects",
        ) from e


@router.post("/projects", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
@tiered_rate_limit("todo_operations")
async def create_project(
    project: ProjectCreate, user: AuthenticatedUser = Depends(get_current_user)
) -> ProjectResponse:
    """Create a new project."""
    log.set(user={"id": user["user_id"]}, todo={"operation": "create_project"})
    try:
        return await ProjectService.create_project(project, user["user_id"])
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create project",
        ) from e


@router.put("/projects/{project_id}", response_model=ProjectResponse)
@tiered_rate_limit("todo_operations")
async def update_project(
    project_id: str,
    updates: UpdateProjectRequest,
    user: AuthenticatedUser = Depends(get_current_user),
) -> ProjectResponse:
    """Update a project. Cannot update the default Inbox project."""
    log.set(
        user={"id": user["user_id"]},
        todo={"operation": "update_project", "project_id": project_id},
    )
    try:
        return await ProjectService.update_project(project_id, updates, user["user_id"])
    except ValueError as e:
        raise HTTPException(
            status_code=(
                status.HTTP_400_BAD_REQUEST
                if "Cannot update" in str(e)
                else status.HTTP_404_NOT_FOUND
            ),
            detail=str(e),
        ) from e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update project",
        ) from e


@router.delete("/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
@tiered_rate_limit("todo_operations")
async def delete_project(
    project_id: str, user: AuthenticatedUser = Depends(get_current_user)
) -> None:
    """Delete a project. All todos will be moved to Inbox. Cannot delete Inbox."""
    log.set(
        user={"id": user["user_id"]},
        todo={"operation": "delete_project", "project_id": project_id},
    )
    try:
        await ProjectService.delete_project(project_id, user["user_id"])
    except ValueError as e:
        raise HTTPException(
            status_code=(
                status.HTTP_400_BAD_REQUEST
                if "Cannot delete" in str(e)
                else status.HTTP_404_NOT_FOUND
            ),
            detail=str(e),
        ) from e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete project",
        ) from e


# Subtask Management Endpoints
@router.post(
    "/todos/{todo_id}/subtasks",
    response_model=TodoResponse,
    status_code=status.HTTP_201_CREATED,
)
@tiered_rate_limit("todo_operations")
async def create_subtask(
    todo_id: str, subtask: SubtaskCreateRequest, user: AuthenticatedUser = Depends(get_current_user)
) -> TodoResponse:
    """Add a new subtask to a todo."""
    log.set(
        user={"id": user["user_id"]},
        todo={"operation": "create_subtask", "id": todo_id},
    )
    try:
        new_subtask = SubTask(id=str(uuid.uuid4()), title=subtask.title, completed=False)
        updated_todo = await todo_repository.add_subtask(
            todo_id, user_id=user["user_id"], subtask=new_subtask
        )
        if not updated_todo:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"Todo {todo_id} not found"
            )
        return TodoResponse.from_document(updated_todo)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create subtask",
        ) from e


@router.put("/todos/{todo_id}/subtasks/{subtask_id}", response_model=TodoResponse)
@tiered_rate_limit("todo_operations")
async def update_subtask(
    todo_id: str,
    subtask_id: str,
    updates: SubtaskUpdateRequest,
    user: AuthenticatedUser = Depends(get_current_user),
) -> TodoResponse:
    """Update a specific subtask."""
    log.set(
        user={"id": user["user_id"]},
        todo={"operation": "update_subtask", "id": todo_id},
    )
    try:
        updated_todo = await todo_repository.set_subtask_fields(
            todo_id,
            user_id=user["user_id"],
            subtask_id=subtask_id,
            title=updates.title,
            completed=updates.completed,
        )
        if not updated_todo:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"Todo {todo_id} not found"
            )

        # Verify subtask exists (a non-matching id updates nothing but still succeeds)
        if not any(s.id == subtask_id for s in updated_todo.subtasks):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subtask not found")

        return TodoResponse.from_document(updated_todo)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update subtask",
        ) from e


@router.delete("/todos/{todo_id}/subtasks/{subtask_id}", response_model=TodoResponse)
@tiered_rate_limit("todo_operations")
async def delete_subtask(
    todo_id: str, subtask_id: str, user: AuthenticatedUser = Depends(get_current_user)
) -> TodoResponse:
    """Delete a specific subtask."""
    log.set(
        user={"id": user["user_id"]},
        todo={"operation": "delete_subtask", "id": todo_id},
    )
    try:
        updated_todo = await todo_repository.remove_subtask(
            todo_id, user_id=user["user_id"], subtask_id=subtask_id
        )
        if not updated_todo:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"Todo {todo_id} not found"
            )

        # If the subtask is still present, nothing was removed → it did not exist.
        if any(s.id == subtask_id for s in updated_todo.subtasks):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subtask not found")

        return TodoResponse.from_document(updated_todo)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete subtask",
        ) from e


@router.post("/todos/{todo_id}/subtasks/{subtask_id}/toggle", response_model=TodoResponse)
@tiered_rate_limit("todo_operations")
async def toggle_subtask_completion(
    todo_id: str, subtask_id: str, user: AuthenticatedUser = Depends(get_current_user)
) -> TodoResponse:
    """Toggle the completion status of a subtask (convenience endpoint)."""
    log.set(
        user={"id": user["user_id"]},
        todo={"operation": "toggle_subtask", "id": todo_id},
    )
    try:
        # First, read the current completion status to toggle.
        todo = await todo_repository.get(todo_id, user_id=user["user_id"])
        if not todo:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"Todo {todo_id} not found"
            )

        subtask = next((s for s in todo.subtasks if s.id == subtask_id), None)
        if not subtask:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subtask not found")

        updated_todo = await todo_repository.set_subtask_fields(
            todo_id,
            user_id=user["user_id"],
            subtask_id=subtask_id,
            completed=not subtask.completed,
        )
        if not updated_todo:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"Todo {todo_id} not found"
            )

        capture_context_event(
            AnalyticsEvents.TODO_TOGGLED,
            {"is_subtask": True, "completed": not subtask.completed},
        )
        return TodoResponse.from_document(updated_todo)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to toggle subtask",
        ) from e
