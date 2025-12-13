from datetime import datetime, timedelta, timezone
from typing import List, Optional
import uuid

from bson import ObjectId
from pymongo import ReturnDocument

from app.api.v1.dependencies.oauth_dependencies import (
    get_current_user,
    get_user_timezone_from_preferences,
)
from app.config.loggers import todos_logger
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
    TodoStats,
    TodoUpdateRequest,
    UpdateProjectRequest,
)
from app.models.workflow_models import (
    CreateWorkflowRequest,
    TriggerConfig,
    TriggerType,
)
from app.services.todos.sync_service import sync_subtask_to_goal_completion
from app.services.todos.todo_service import ProjectService, TodoService
from app.services.workflow.service import WorkflowService
from app.db.utils import serialize_document
from fastapi import APIRouter, Body, Depends, HTTPException, Query, status

router = APIRouter()


# Counts endpoint for efficient dashboard data
@router.get("/todos/counts")
async def get_todo_counts(user: dict = Depends(get_current_user)):
    """
    Get all todo counts for dashboard/sidebar in a single efficient call.
    Returns inbox count, today count, upcoming count, and completed count.
    """
    try:
        # Use the stats calculation to get counts efficiently
        stats: TodoStats = await TodoService._calculate_stats(user["user_id"])

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
                }
            },
        ]

        counts_result = await todos_collection.aggregate(counts_pipeline).to_list(1)
        facets = counts_result[0] if counts_result else {}

        # Safely extract counts from facets (handle empty arrays)
        def safe_get_count(facet_result):
            return facet_result[0].get("count", 0) if facet_result else 0

        return {
            "inbox": safe_get_count(facets.get("inbox", [])),
            "today": safe_get_count(facets.get("today", [])),
            "upcoming": safe_get_count(facets.get("upcoming", [])),
            "completed": stats.completed,
            "overdue": safe_get_count(facets.get("overdue", [])),
        }

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve counts: {e}",
        )


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
        return await TodoService.list_todos(user["user_id"], params)
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
    """Generate a standalone workflow for a specific todo with automatic timezone detection."""
    try:
        todo: TodoResponse = await TodoService.get_todo(todo_id, user["user_id"])

        # Check if workflow already exists for this todo
        if todo.workflow_id:
            existing_workflow = await WorkflowService.get_workflow(
                todo.workflow_id, user["user_id"]
            )
            if existing_workflow:
                return {
                    "workflow": existing_workflow,
                    "message": "Workflow already exists for this todo",
                }

        # Create standalone workflow
        workflow_request = CreateWorkflowRequest(
            title=f"Todo: {todo.title}",
            description=todo.description or f"Workflow for todo: {todo.title}",
            trigger_config=TriggerConfig(type=TriggerType.MANUAL, enabled=True),
            generate_immediately=True,  # Generate steps immediately
        )

        workflow = await WorkflowService.create_workflow(
            workflow_request, user["user_id"], user_timezone=user_timezone
        )

        update_request = TodoUpdateRequest(workflow_id=workflow.id)
        await TodoService.update_todo(todo_id, update_request, user["user_id"])

        return {"workflow": workflow, "message": "Workflow generated successfully"}

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
# @tiered_rate_limit("todo_operations") # Commented out because it's a polling endpoint
async def get_workflow_status(todo_id: str, user: dict = Depends(get_current_user)):
    """
    Get the standalone workflow for a todo.
    Returns the workflow if it exists, otherwise returns None.
    """
    try:
        from app.services.workflow.service import WorkflowService

        # Verify todo exists and get workflow_id
        todo: TodoResponse = await TodoService.get_todo(todo_id, user["user_id"])

        # Get standalone workflow if workflow_id exists
        workflow = None
        if todo.workflow_id:
            workflow = await WorkflowService.get_workflow(
                todo.workflow_id, user["user_id"]
            )

        return {
            "todo_id": todo_id,
            "has_workflow": workflow is not None,
            "is_generating": False,  # Since we generate immediately now
            "workflow_status": "completed" if workflow else "not_started",
            "workflow": workflow,
        }
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
                todos_logger.warning(f"Failed to sync subtask to goal: {str(e)}")

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
    try:
        # Store original subtasks count to verify deletion
        todo_before = await todos_collection.find_one(
            {"_id": ObjectId(todo_id), "user_id": user["user_id"]}, {"subtasks": 1}
        )

        if not todo_before:
            raise ValueError(f"Todo {todo_id} not found")

        original_count = len(todo_before.get("subtasks", []))

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

        # Verify subtask was actually removed
        new_count = len(updated_todo.get("subtasks", []))
        if new_count == original_count:
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
            todos_logger.warning(f"Failed to sync subtask to goal: {str(e)}")

        return TodoResponse(**serialize_document(updated_todo))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to toggle subtask",
        )
