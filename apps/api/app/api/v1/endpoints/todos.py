import asyncio
from datetime import datetime, timedelta, timezone
from typing import Annotated, List, Optional
import uuid

from bson import ObjectId
from pymongo import ReturnDocument

from app.api.v1.dependencies.oauth_dependencies import (
    get_current_user,
    get_user_timezone_from_preferences,
)
from shared.py.wide_events import log
from app.db.mongodb.collections import projects_collection, todos_collection
from app.decorators import tiered_rate_limit
from app.models.todo_models import (
    BulkMoveRequest,
    BulkOperationResponse,
    BulkUpdateRequest,
    Priority,
    ProjectCreate,
    ProjectResponse,
    SearchMode,
    SubtaskCreateRequest,
    SubtaskUpdateRequest,
    TodoListResponse,
    TodoModel,
    TodoResponse,
    TodoSearchParams,
    TodoUpdateRequest,
    UpdateProjectRequest,
)
from app.services.todos.sync_service import sync_subtask_to_goal_completion
from app.services.todos.todo_service import ProjectService, TodoService
from app.services.workflow.service import WorkflowService
from app.db.redis import delete_cache, get_cache, set_cache
from app.db.utils import serialize_document
from fastapi import APIRouter, Body, Depends, HTTPException, Query, Response, status

router = APIRouter()


# Counts endpoint for efficient dashboard data
@router.get("/todos/counts")
async def get_todo_counts(
    response: Response, user: Annotated[dict, Depends(get_current_user)]
):
    """
    Get all todo counts for dashboard/sidebar in a single efficient call.
    Returns inbox count, today count, upcoming count, and completed count.
    """
    response.headers["Cache-Control"] = "private, max-age=10"
    log.set(user={"id": user["user_id"]}, todo={"operation": "counts"})
    try:
        cache_key = f"counts:{user['user_id']}"
        cached = await get_cache(cache_key)
        if cached:
            return cached

        # Get today's date for filtering
        today = datetime.now(timezone.utc).date()
        today_start = datetime.combine(today, datetime.min.time()).replace(
            tzinfo=timezone.utc
        )
        today_end = datetime.combine(today, datetime.max.time()).replace(
            tzinfo=timezone.utc
        )

        # Get upcoming end date (7 days from now)
        upcoming_end = datetime.now(timezone.utc) + timedelta(days=7)

        # Get inbox project
        inbox_project = await projects_collection.find_one(
            {"user_id": user["user_id"], "is_default": True}
        )
        inbox_project_id = (
            str(inbox_project["_id"]) if inbox_project else "no_inbox_found"
        )

        # Get current time for overdue calculation
        now = datetime.now(timezone.utc)

        # Count todos efficiently with a single aggregation
        counts_pipeline = [
            {"$match": {"user_id": user["user_id"]}},
            {
                "$facet": {
                    "inbox": [
                        {
                            "$match": {
                                "project_id": inbox_project_id,
                                "completed": False,
                            }
                        },
                        {"$count": "count"},
                    ],
                    "today": [
                        {
                            "$match": {
                                "due_date": {"$gte": today_start, "$lte": today_end},
                                "completed": False,
                            }
                        },
                        {"$count": "count"},
                    ],
                    "upcoming": [
                        {
                            "$match": {
                                "due_date": {"$gt": today_end, "$lte": upcoming_end},
                                "completed": False,
                            }
                        },
                        {"$count": "count"},
                    ],
                    "overdue": [
                        {
                            "$match": {
                                "due_date": {"$lt": now},
                                "completed": False,
                            }
                        },
                        {"$count": "count"},
                    ],
                    "completed": [
                        {"$match": {"completed": True}},
                        {"$count": "count"},
                    ],
                }
            },
        ]

        counts_result = await todos_collection.aggregate(counts_pipeline).to_list(1)
        facets = counts_result[0] if counts_result else {}

        # Safely extract counts from facets (handle empty arrays)
        def safe_get_count(facet_result):
            return facet_result[0].get("count", 0) if facet_result else 0

        result = {
            "inbox": safe_get_count(facets.get("inbox", [])),
            "today": safe_get_count(facets.get("today", [])),
            "upcoming": safe_get_count(facets.get("upcoming", [])),
            "completed": safe_get_count(facets.get("completed", [])),
            "overdue": safe_get_count(facets.get("overdue", [])),
        }
        await set_cache(cache_key, result, ttl=30)
        return result

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve counts: {e}",
        )


# Labels endpoint — dedicated aggregation for most-used labels
@router.get("/todos/labels")
async def get_todo_labels(
    user: Annotated[dict, Depends(get_current_user)],
    limit: int = 10,
) -> list[dict]:
    """Get most-used labels for the current user's todos."""
    user_id = user["user_id"]
    pipeline = [
        {"$match": {"user_id": user_id, "completed": False}},
        {"$unwind": "$labels"},
        {"$group": {"_id": "$labels", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": limit},
        {"$project": {"name": "$_id", "count": 1, "_id": 0}},
    ]
    result: list[dict] = await todos_collection.aggregate(pipeline).to_list(limit)
    return result


# Main Todo CRUD Endpoints
@router.get("/todos", response_model=TodoListResponse)
async def list_todos(
    # Search parameters
    q: Optional[str] = Query(None, description="Search query"),
    mode: SearchMode = Query(
        SearchMode.HYBRID, description="Search mode: text, semantic, or hybrid"
    ),
    # Filter parameters
    project_id: Optional[str] = Query(None),
    completed: Optional[bool] = Query(None),
    priority: Optional[Priority] = Query(None),
    has_due_date: Optional[bool] = Query(None),
    overdue: Optional[bool] = Query(None),
    labels: Optional[List[str]] = Query(None),
    # Date range filters
    due_after: Optional[datetime] = Query(None, description="Due date after this date"),
    due_before: Optional[datetime] = Query(
        None, description="Due date before this date"
    ),
    # Special date filters
    due_today: bool = Query(False, description="Only todos due today"),
    due_this_week: bool = Query(False, description="Only todos due this week"),
    # Pagination
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100),
    # Options
    include_stats: bool = Query(False, description="Include statistics in response"),
    user: dict = Depends(get_current_user),
):
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
            "search_mode": mode.value if hasattr(mode, "value") else str(mode),
            "query": q,
            "page": page,
            "per_page": per_page,
            "filters_applied": filters_applied,
            "project_id": project_id,
        },
    )

    # Handle special date filters
    if due_today:
        today = datetime.now(timezone.utc).date()
        due_after = datetime.combine(today, datetime.min.time()).replace(
            tzinfo=timezone.utc
        )
        due_before = datetime.combine(today, datetime.max.time()).replace(
            tzinfo=timezone.utc
        )
    elif due_this_week:
        today = datetime.now(timezone.utc)
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
        log.set(
            todo={
                "operation": "list",
                "result_count": len(result.todos) if hasattr(result, "todos") else 0,
            }
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve todos",
        )


@router.post("/todos", response_model=TodoResponse, status_code=status.HTTP_201_CREATED)
@tiered_rate_limit("todo_operations")
async def create_todo(todo: TodoModel, user: dict = Depends(get_current_user)):
    """Create a new todo. If no project is specified, it will be added to Inbox."""
    log.set(
        user={"id": user["user_id"]},
        todo={
            "operation": "create",
            "priority": todo.priority.value
            if todo.priority and hasattr(todo.priority, "value")
            else str(todo.priority)
            if todo.priority
            else None,
            "has_due_date": todo.due_date is not None,
            "project_id": todo.project_id if hasattr(todo, "project_id") else None,
        },
    )
    try:
        return await TodoService.create_todo(todo, user["user_id"])
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create todo",
        )


@router.get("/todos/{todo_id}", response_model=TodoResponse)
async def get_todo(todo_id: str, user: dict = Depends(get_current_user)):
    """Get a specific todo by ID."""
    log.set(user={"id": user["user_id"]}, todo={"operation": "get", "id": todo_id})
    try:
        return await TodoService.get_todo(todo_id, user["user_id"])
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve todo",
        )


@router.put("/todos/{todo_id}", response_model=TodoResponse)
@tiered_rate_limit("todo_operations")
async def update_todo(
    todo_id: str, updates: TodoUpdateRequest, user: dict = Depends(get_current_user)
):
    """Update a todo."""
    log.set(
        user={"id": user["user_id"]},
        todo={
            "operation": "update",
            "id": todo_id,
            "completion_toggled": updates.completed is not None
            if hasattr(updates, "completed")
            else False,
        },
    )
    try:
        return await TodoService.update_todo(todo_id, updates, user["user_id"])
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update todo",
        )


@router.delete("/todos/{todo_id}", status_code=status.HTTP_204_NO_CONTENT)
@tiered_rate_limit("todo_operations")
async def delete_todo(todo_id: str, user: dict = Depends(get_current_user)):
    """Delete a todo."""
    log.set(user={"id": user["user_id"]}, todo={"operation": "delete", "id": todo_id})
    try:
        await TodoService.delete_todo(todo_id, user["user_id"])
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete todo",
        )


# Workflow Generation Endpoint
@router.post("/todos/{todo_id}/workflow")
@tiered_rate_limit("todo_operations")
async def generate_workflow(
    todo_id: str,
    user: dict = Depends(get_current_user),
    user_timezone: str = Depends(get_user_timezone_from_preferences),
):
    """Generate a workflow for a todo (background generation + WebSocket notification).

    This endpoint returns immediately with 'generating' status. The frontend should
    display a skeleton and listen for the 'workflow.generated' WebSocket event.
    """
    from app.services.workflow.queue_service import WorkflowQueueService

    log.set(
        user={"id": user["user_id"]},
        todo={"operation": "generate_workflow", "id": todo_id},
    )
    try:
        todo: TodoResponse = await TodoService.get_todo(todo_id, user["user_id"])

        # Check if workflow already exists for this todo
        if todo.workflow_id:
            existing_workflow = await WorkflowService.get_workflow(
                todo.workflow_id, user["user_id"]
            )
            if (
                existing_workflow
                and existing_workflow.steps
                and len(existing_workflow.steps) > 0
            ):
                return {
                    "status": "exists",
                    "workflow": existing_workflow,
                    "message": "Workflow already exists for this todo",
                }
            # Empty or failed workflow — delete it and allow regeneration
            if existing_workflow and existing_workflow.id:
                await WorkflowService.delete_workflow(
                    existing_workflow.id, user["user_id"]
                )
            await todos_collection.update_one(
                {"_id": ObjectId(todo_id), "user_id": user["user_id"]},
                {"$unset": {"workflow_id": ""}},
            )

        # Invalidate cached workflow status so next poll reflects generating state
        await delete_cache(f"workflow_status:{user['user_id']}:{todo_id}")

        # Queue background generation - will send WebSocket event when complete
        success = await WorkflowQueueService.queue_todo_workflow_generation(
            todo_id=todo_id,
            user_id=user["user_id"],
            title=todo.title,
            description=todo.description or "",
        )

        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to queue workflow generation",
            )

        return {
            "status": "generating",
            "todo_id": todo_id,
            "message": "Workflow generation started. Listen for 'workflow.generated' WebSocket event.",
        }

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate workflow",
        )


@router.get("/todos/{todo_id}/workflow-status")
async def get_workflow_status(
    todo_id: str, response: Response, user: Annotated[dict, Depends(get_current_user)]
):
    """
    Get the standalone workflow for a todo.
    Returns the workflow if it exists, otherwise returns None.
    Detects generating state when:
    - Workflow generation is queued (Redis flag)
    - Workflow exists but has no steps yet
    """
    response.headers["Cache-Control"] = "private, max-age=15"
    log.set(
        user={"id": user["user_id"]},
        todo={"operation": "get_workflow_status", "id": todo_id},
    )
    try:
        from app.services.workflow.queue_service import WorkflowQueueService
        from app.services.workflow.service import WorkflowService

        wf_cache_key = f"workflow_status:{user['user_id']}:{todo_id}"
        cached_wf = await get_cache(wf_cache_key)
        if cached_wf:
            return cached_wf

        # Parallelize independent fetch + generating check
        todo, is_generating = await asyncio.gather(
            TodoService.get_todo(todo_id, user["user_id"]),
            WorkflowQueueService.is_workflow_generating(todo_id),
        )

        # Get standalone workflow if workflow_id exists
        workflow = None
        has_workflow = False
        workflow_status = "not_started"

        # Check if workflow generation is queued/pending (Redis flag)
        if is_generating:
            workflow_status = "generating"
        elif todo.workflow_id:
            workflow = await WorkflowService.get_workflow(
                todo.workflow_id, user["user_id"]
            )

            if workflow:
                # Workflow exists - check if steps are generated
                has_steps = workflow.steps and len(workflow.steps) > 0
                if has_steps:
                    workflow_status = "completed"
                    has_workflow = True
                elif await WorkflowQueueService.is_workflow_generating(todo_id):
                    is_generating = True
                    workflow_status = "generating"
                else:
                    # Workflow exists but empty steps and not generating = failed
                    workflow_status = "failed"

        wf_result = {
            "todo_id": todo_id,
            "has_workflow": has_workflow,
            "is_generating": is_generating,
            "workflow_status": workflow_status,
            "workflow": workflow if has_workflow else None,
        }
        if not is_generating:
            await set_cache(wf_cache_key, wf_result, ttl=60)
        return wf_result
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get workflow status",
        )


# Bulk Operations
@router.put("/todos/bulk", response_model=BulkOperationResponse)
@tiered_rate_limit("todo_operations")
async def bulk_update_todos(
    request: BulkUpdateRequest, user: dict = Depends(get_current_user)
):
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
        todo={
            "operation": "bulk_update",
            "bulk_count": len(request.todo_ids) if hasattr(request, "todo_ids") else 0,
        },
    )
    try:
        return await TodoService.bulk_update_todos(request, user["user_id"])
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Bulk update failed",
        )


@router.post("/todos/bulk/move", response_model=BulkOperationResponse)
@tiered_rate_limit("todo_operations")
async def bulk_move_todos(
    request: BulkMoveRequest, user: dict = Depends(get_current_user)
):
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
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Bulk move failed"
        )


@router.delete("/todos/bulk", response_model=BulkOperationResponse)
@tiered_rate_limit("todo_operations")
async def bulk_delete_todos(
    todo_ids: List[str] = Body(..., min_length=1, max_length=100),
    user: dict = Depends(get_current_user),
):
    """Delete multiple todos."""
    log.set(
        user={"id": user["user_id"]},
        todo={"operation": "bulk_delete", "bulk_count": len(todo_ids)},
    )
    try:
        return await TodoService.bulk_delete_todos(todo_ids, user["user_id"])
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Bulk delete failed",
        )


# Special mark complete endpoint for convenience
@router.post("/todos/bulk/complete", response_model=BulkOperationResponse)
@tiered_rate_limit("todo_operations")
async def bulk_complete_todos(
    todo_ids: List[str] = Body(..., min_length=1, max_length=100),
    user: dict = Depends(get_current_user),
):
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
        return await TodoService.bulk_update_todos(request, user["user_id"])
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Bulk complete failed",
        )


# Project Endpoints
@router.get("/projects", response_model=List[ProjectResponse])
async def list_projects(user: dict = Depends(get_current_user)):
    """List all projects with todo counts."""
    log.set(user={"id": user["user_id"]}, todo={"operation": "list_projects"})
    try:
        return await ProjectService.list_projects(user["user_id"])
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve projects",
        )


@router.post(
    "/projects", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED
)
@tiered_rate_limit("todo_operations")
async def create_project(
    project: ProjectCreate, user: dict = Depends(get_current_user)
):
    """Create a new project."""
    log.set(user={"id": user["user_id"]}, todo={"operation": "create_project"})
    try:
        return await ProjectService.create_project(project, user["user_id"])
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create project",
        )


@router.put("/projects/{project_id}", response_model=ProjectResponse)
@tiered_rate_limit("todo_operations")
async def update_project(
    project_id: str,
    updates: UpdateProjectRequest,
    user: dict = Depends(get_current_user),
):
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
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update project",
        )


@router.delete("/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
@tiered_rate_limit("todo_operations")
async def delete_project(project_id: str, user: dict = Depends(get_current_user)):
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
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete project",
        )


# Subtask Management Endpoints
@router.post(
    "/todos/{todo_id}/subtasks",
    response_model=TodoResponse,
    status_code=status.HTTP_201_CREATED,
)
@tiered_rate_limit("todo_operations")
async def create_subtask(
    todo_id: str, subtask: SubtaskCreateRequest, user: dict = Depends(get_current_user)
):
    """Add a new subtask to a todo."""
    log.set(
        user={"id": user["user_id"]},
        todo={"operation": "create_subtask", "id": todo_id},
    )
    try:
        new_subtask = {
            "id": str(uuid.uuid4()),
            "title": subtask.title,
            "completed": False,
        }

        # Atomic operation: verify ownership and add subtask in one query
        updated_todo = await todos_collection.find_one_and_update(
            {"_id": ObjectId(todo_id), "user_id": user["user_id"]},
            {
                "$push": {"subtasks": new_subtask},
                "$set": {"updated_at": datetime.now(timezone.utc)},
            },
            return_document=ReturnDocument.AFTER,
        )

        if not updated_todo:
            raise ValueError(f"Todo {todo_id} not found")

        # Invalidate cache
        await TodoService._invalidate_cache(
            user["user_id"],
            updated_todo.get("project_id"),
            todo_id,
            "update_minor",
        )

        return TodoResponse(**serialize_document(updated_todo))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create subtask",
        )


@router.put("/todos/{todo_id}/subtasks/{subtask_id}", response_model=TodoResponse)
@tiered_rate_limit("todo_operations")
async def update_subtask(
    todo_id: str,
    subtask_id: str,
    updates: SubtaskUpdateRequest,
    user: dict = Depends(get_current_user),
):
    """Update a specific subtask."""
    log.set(
        user={"id": user["user_id"]},
        todo={"operation": "update_subtask", "id": todo_id},
    )
    try:
        # Build update operations
        from typing import Any

        update_ops: dict[str, Any] = {
            "$set": {"updated_at": datetime.now(timezone.utc)}
        }

        if updates.title is not None:
            update_ops["$set"]["subtasks.$[elem].title"] = updates.title
        if updates.completed is not None:
            update_ops["$set"]["subtasks.$[elem].completed"] = updates.completed

        # Atomic operation: verify ownership, find subtask, and update in one query
        updated_todo = await todos_collection.find_one_and_update(
            {"_id": ObjectId(todo_id), "user_id": user["user_id"]},
            update_ops,
            array_filters=[{"elem.id": subtask_id}],
            return_document=ReturnDocument.AFTER,
        )

        if not updated_todo:
            raise ValueError(f"Todo {todo_id} not found")

        # Verify subtask exists (if no match, the update still succeeds but doesn't modify)
        subtask_found = any(
            s.get("id") == subtask_id for s in updated_todo.get("subtasks", [])
        )
        if not subtask_found:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Subtask not found"
            )

        # Invalidate cache and handle goal sync if completion changed
        await TodoService._invalidate_cache(
            user["user_id"],
            updated_todo.get("project_id"),
            todo_id,
            "update_minor",
        )

        # Sync to goal if completion status changed
        if updates.completed is not None:
            try:
                await sync_subtask_to_goal_completion(
                    todo_id, subtask_id, updates.completed, user["user_id"]
                )
            except Exception as e:
                log.warning(f"Failed to sync subtask to goal: {str(e)}")

        return TodoResponse(**serialize_document(updated_todo))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update subtask",
        )


@router.delete("/todos/{todo_id}/subtasks/{subtask_id}", response_model=TodoResponse)
@tiered_rate_limit("todo_operations")
async def delete_subtask(
    todo_id: str, subtask_id: str, user: dict = Depends(get_current_user)
):
    """Delete a specific subtask."""
    log.set(
        user={"id": user["user_id"]},
        todo={"operation": "delete_subtask", "id": todo_id},
    )
    try:
        # Atomic operation: verify ownership and remove subtask in one query
        updated_todo = await todos_collection.find_one_and_update(
            {"_id": ObjectId(todo_id), "user_id": user["user_id"]},
            {
                "$pull": {"subtasks": {"id": subtask_id}},
                "$set": {"updated_at": datetime.now(timezone.utc)},
            },
            return_document=ReturnDocument.AFTER,
        )

        if not updated_todo:
            raise ValueError(f"Todo {todo_id} not found")

        # Verify subtask was actually removed by checking if it still exists in the result
        subtask_still_exists = any(
            s.get("id") == subtask_id for s in updated_todo.get("subtasks", [])
        )
        if subtask_still_exists:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Subtask not found"
            )

        # Invalidate cache
        await TodoService._invalidate_cache(
            user["user_id"],
            updated_todo.get("project_id"),
            todo_id,
            "update_minor",
        )

        return TodoResponse(**serialize_document(updated_todo))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete subtask",
        )


@router.post(
    "/todos/{todo_id}/subtasks/{subtask_id}/toggle", response_model=TodoResponse
)
@tiered_rate_limit("todo_operations")
async def toggle_subtask_completion(
    todo_id: str, subtask_id: str, user: dict = Depends(get_current_user)
):
    """Toggle the completion status of a subtask (convenience endpoint)."""
    log.set(
        user={"id": user["user_id"]},
        todo={"operation": "toggle_subtask", "id": todo_id},
    )
    try:
        # First, get current completion status to toggle and for goal sync

        todo = await todos_collection.find_one(
            {"_id": ObjectId(todo_id), "user_id": user["user_id"]},
            {"subtasks": 1, "project_id": 1},
        )

        if not todo:
            raise ValueError(f"Todo {todo_id} not found")

        # Find the subtask to get current completion status
        subtask = next(
            (s for s in todo.get("subtasks", []) if s.get("id") == subtask_id), None
        )
        if not subtask:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Subtask not found"
            )

        new_completed = not subtask.get("completed", False)

        # Atomic operation: toggle completion using array filter

        updated_todo = await todos_collection.find_one_and_update(
            {"_id": ObjectId(todo_id), "user_id": user["user_id"]},
            {
                "$set": {
                    "subtasks.$[elem].completed": new_completed,
                    "updated_at": datetime.now(timezone.utc),
                }
            },
            array_filters=[{"elem.id": subtask_id}],
            return_document=ReturnDocument.AFTER,
        )

        if not updated_todo:
            raise ValueError(f"Todo {todo_id} not found")

        # Invalidate cache
        await TodoService._invalidate_cache(
            user["user_id"],
            updated_todo.get("project_id"),
            todo_id,
            "update_minor",
        )

        # Sync to goal
        try:
            await sync_subtask_to_goal_completion(
                todo_id, subtask_id, new_completed, user["user_id"]
            )
        except Exception as e:
            log.warning(f"Failed to sync subtask to goal: {str(e)}")

        return TodoResponse(**serialize_document(updated_todo))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to toggle subtask",
        )
