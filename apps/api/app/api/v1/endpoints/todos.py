import asyncio
from typing import Annotated
import uuid

from fastapi import (
    APIRouter,
    Body,
    Depends,
    HTTPException,
    Query,
    Response,
    status,
)
from fastapi.responses import JSONResponse

from app.api.v1.dependencies.oauth_dependencies import (
    get_current_user,
    get_user_id,
    get_user_timezone_from_preferences,
)
from app.constants.log_tags import LogTag
from app.constants.todos import FACET_FIELDS, FACET_NOTES
from app.db.redis import delete_cache, get_cache, set_cache
from app.db.repositories.projects import project_repository
from app.db.repositories.todos import todo_repository
from app.decorators import tiered_rate_limit
from app.models.todo_models import (
    BulkMoveRequest,
    BulkOperationResponse,
    BulkUpdateRequest,
    ProjectCreate,
    ProjectResponse,
    SubTask,
    SubtaskCreateRequest,
    SubtaskUpdateRequest,
    TodoCanvasResponse,
    TodoCounts,
    TodoLabelCount,
    TodoListQuery,
    TodoListResponse,
    TodoModel,
    TodoResponse,
    TodoUpdate,
    TodoUpdateRequest,
    TodoWorkflowGenerationResponse,
    TodoWorkflowGenerationStatus,
    TodoWorkflowStatus,
    TodoWorkflowStatusResponse,
    UpdateProjectRequest,
)
from app.models.user_models import AuthenticatedUser
from app.services.analytics_service import AnalyticsEvents, capture_context_event
from app.services.payments.payment_service import payment_service
from app.services.todo_canvas_storage import read_artifacts, read_facet
from app.services.todos import gaia_todo_lifecycle as lifecycle
from app.services.todos.gaia_todo_lifecycle import (
    ExecutionQuotaError,
    InvalidTransitionError,
)
from app.services.todos.todo_classification import schedule_classification
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
    query: Annotated[TodoListQuery, Query()],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
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
    log.set(
        user={"id": user["user_id"]},
        todo={
            "operation": "list",
            "search_mode": query.mode.value,
            "query": query.q,
            "page": query.page,
            "per_page": query.per_page,
            "filters_applied": query.applied_filters(),
            "project_id": query.project_id,
        },
    )

    params = query.to_search_params()

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
        created = await TodoService.create_todo(todo, user["user_id"])
        # Capture stays instant: GAIA quietly classifies the new todo in the
        # background (offer / prep / silent) without blocking the response.
        schedule_classification(created.id, user["user_id"], created.title, created.description)
        return created
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
    """Return a tracked todo's notes facet.

    Migration alias for the pre-facet frontend: ``canvas`` mapped to what is now
    the notes facet. Kept until the frontend is facet-aware, then removed.
    """
    log.set(user={"id": user["user_id"]}, todo={"operation": "get_canvas", "id": todo_id})
    content = await read_facet(todo_id, user["user_id"], FACET_NOTES)
    if content is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Todo not found")
    return TodoCanvasResponse(content=content)


@router.get("/todos/{todo_id}/facets/{facet}")
async def get_todo_facet(
    todo_id: str, facet: str, user: Annotated[dict, Depends(get_current_user)]
) -> JSONResponse:
    """Return a single facet (deliverable | notes | log) of a tracked todo."""
    log.set(user={"id": user["user_id"]}, todo={"operation": "get_facet", "id": todo_id})
    if facet not in FACET_FIELDS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown facet '{facet}'. Expected one of: {', '.join(sorted(FACET_FIELDS))}.",
        )
    content = await read_facet(todo_id, user["user_id"], facet)
    if content is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Todo not found")
    return JSONResponse(content={"facet": facet, "content": content})


@router.get("/todos/{todo_id}/artifacts")
async def get_todo_artifacts(
    todo_id: str, user: Annotated[dict, Depends(get_current_user)]
) -> JSONResponse:
    """Return the artifacts (discrete rich outputs) attached to a tracked todo."""
    log.set(user={"id": user["user_id"]}, todo={"operation": "get_artifacts", "id": todo_id})
    artifacts = await read_artifacts(todo_id, user["user_id"])
    if artifacts is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Todo not found")
    return JSONResponse(content={"artifacts": artifacts})


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

        # Atomic operation: verify ownership and add subtask in one query
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
        # Atomic operation: verify ownership, find subtask, and update in one query
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

        # Verify subtask exists (if no match, the update still succeeds but doesn't modify)
        subtask_found = any(s.id == subtask_id for s in updated_todo.subtasks)
        if not subtask_found:
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
        # Atomic operation: verify ownership and remove subtask in one query
        updated_todo = await todo_repository.remove_subtask(
            todo_id, user_id=user["user_id"], subtask_id=subtask_id
        )

        if not updated_todo:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"Todo {todo_id} not found"
            )

        # Verify subtask was actually removed by checking if it still exists in the result
        subtask_still_exists = any(s.id == subtask_id for s in updated_todo.subtasks)
        if subtask_still_exists:
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
        # First, get current completion status to toggle
        todo = await todo_repository.get(todo_id, user_id=user["user_id"])

        if not todo:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"Todo {todo_id} not found"
            )

        # Find the subtask to get current completion status
        subtask = next((s for s in todo.subtasks if s.id == subtask_id), None)
        if not subtask:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subtask not found")

        new_completed = not subtask.completed

        # Atomic operation: toggle completion using array filter
        updated_todo = await todo_repository.set_subtask_fields(
            todo_id,
            user_id=user["user_id"],
            subtask_id=subtask_id,
            completed=new_completed,
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


# --- GAIA todo lifecycle (assignee model) -----------------------------------
# Approve is the ONLY proposed→queued path and the free→pro conversion surface:
# at quota it returns 402 with the staged work as the pitch instead of a
# silent failure. Dismiss/handoff complete the user-facing lifecycle.


@router.post("/todos/{todo_id}/approve", status_code=status.HTTP_200_OK)
async def approve_gaia_todo(
    todo_id: str,
    user: Annotated[dict, Depends(get_current_user)],
    channel: str = Body(default="web", embed=True),
    instruction: str | None = Body(default=None, embed=True),
) -> JSONResponse:
    """Approve a proposed GAIA todo: meter quota, queue it, enqueue execution."""
    user_id = user["user_id"]
    log.set(user={"id": user_id}, todo={"operation": "approve", "id": todo_id})
    user_plan = await payment_service.get_cached_plan_type(user_id)
    try:
        await lifecycle.approve(
            todo_id, user_id, user_plan, channel=channel, instruction=instruction
        )
    except ExecutionQuotaError as e:
        return JSONResponse(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            content={
                "error": "gaia_execution_quota",
                "todo_id": e.todo_id,
                "pitch": e.pitch,
                "plan_required": e.plan_required,
                "reset_time": e.reset_time,
            },
        )
    except InvalidTransitionError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e
    return JSONResponse(content={"success": True, "todo_id": todo_id, "execution_status": "queued"})


@router.post("/todos/{todo_id}/dismiss", status_code=status.HTTP_200_OK)
async def dismiss_gaia_todo(
    todo_id: str,
    user: Annotated[dict, Depends(get_current_user)],
    reason: str | None = Body(default=None, embed=True),
    channel: str = Body(default="web", embed=True),
) -> JSONResponse:
    """Dismiss a proposed GAIA todo; the rejection teaches memory (3-strike rule)."""
    user_id = user["user_id"]
    log.set(user={"id": user_id}, todo={"operation": "dismiss", "id": todo_id})
    try:
        await lifecycle.dismiss(todo_id, user_id, reason=reason, channel=channel)
    except InvalidTransitionError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e
    return JSONResponse(
        content={"success": True, "todo_id": todo_id, "execution_status": "dismissed"}
    )


@router.post("/todos/{todo_id}/answer", status_code=status.HTTP_200_OK)
async def answer_gaia_todo(
    todo_id: str,
    user: Annotated[dict, Depends(get_current_user)],
    answer: str = Body(embed=True, min_length=1),
    channel: str = Body(default="web", embed=True),
) -> JSONResponse:
    """Answer a blocked (needs_you) GAIA todo: record the reply and re-queue the run."""
    user_id = user["user_id"]
    log.set(user={"id": user_id}, todo={"operation": "answer", "id": todo_id})
    try:
        await lifecycle.answer(todo_id, user_id, answer, channel=channel)
    except InvalidTransitionError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e
    return JSONResponse(content={"success": True, "todo_id": todo_id, "execution_status": "queued"})


@router.post("/todos/{todo_id}/handoff", status_code=status.HTTP_200_OK)
async def handoff_todo_to_gaia(
    todo_id: str,
    user: Annotated[dict, Depends(get_current_user)],
) -> JSONResponse:
    """Hand a user todo to GAIA (entry state queued; outward steps escalate mid-run)."""
    user_id = user["user_id"]
    log.set(user={"id": user_id}, todo={"operation": "handoff", "id": todo_id})
    try:
        await lifecycle.handoff(todo_id, user_id)
    except InvalidTransitionError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e
    return JSONResponse(content={"success": True, "todo_id": todo_id, "execution_status": "queued"})


@router.post("/todos/{todo_id}/retry", status_code=status.HTTP_200_OK)
async def retry_gaia_todo(
    todo_id: str,
    user: Annotated[dict, Depends(get_current_user)],
    channel: str = Body(default="web", embed=True),
) -> JSONResponse:
    """Re-run a failed GAIA todo: clear the failure state and re-queue execution."""
    user_id = user["user_id"]
    log.set(user={"id": user_id}, todo={"operation": "retry", "id": todo_id})
    try:
        await lifecycle.retry(todo_id, user_id, channel=channel)
    except InvalidTransitionError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e
    log.set(todo={"execution_status": "queued"})
    return JSONResponse(content={"success": True, "todo_id": todo_id, "execution_status": "queued"})


@router.post("/todos/{todo_id}/dismiss_offer", status_code=status.HTTP_200_OK)
async def dismiss_gaia_offer(
    todo_id: str,
    user: Annotated[dict, Depends(get_current_user)],
) -> JSONResponse:
    """Dismiss the GAIA-takeover offer on a user todo, suppressing it everywhere."""
    user_id = user["user_id"]
    log.set(user={"id": user_id}, todo={"operation": "dismiss_offer", "id": todo_id})
    updated = await todo_repository.update(
        todo_id, user_id=user_id, update=TodoUpdate(gaia_offer_dismissed=True)
    )
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Todo not found")
    return JSONResponse(content={"success": True, "todo_id": todo_id, "gaia_offer_dismissed": True})
