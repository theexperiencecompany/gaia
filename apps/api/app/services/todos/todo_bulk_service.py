"""Optimized bulk operations for todos."""

from fastapi import HTTPException, status

from app.constants.log_tags import LogTag
from app.db.repositories.projects import project_repository
from app.db.repositories.todos import todo_repository
from app.models.todo_models import (
    BulkUpdateRequest,
    TodoResponse,
    TodoUpdate,
    TodoUpdateRequest,
)
from app.services.analytics_service import AnalyticsEvents, capture_event
from app.services.todos.todo_service import TodoService
from shared.py.wide_events import log


async def bulk_complete_todos(todo_ids: list[str], user_id: str) -> list[TodoResponse]:
    """Mark multiple todos as completed; tracked ones run their completion lifecycle."""
    log.set(
        component="todo_bulk_service",
        operation="bulk_complete_todos",
        user_id=user_id,
        todo_count=len(todo_ids),
    )
    try:
        result = await TodoService.bulk_update_todos(
            BulkUpdateRequest(todo_ids=todo_ids, updates=TodoUpdateRequest(completed=True)),
            user_id,
        )
        if not result.success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No todos found or already completed",
            )

        updated = await todo_repository.find_by_ids(user_id, todo_ids)
        log.info(
            f"{LogTag.TODO} Bulk completed todos", todo_count=len(result.success), user_id=user_id
        )
        capture_event(user_id, AnalyticsEvents.TODO_TOGGLED, {"count": len(result.success)})
        return [TodoResponse.from_document(todo) for todo in updated]

    except HTTPException:
        raise
    except Exception as e:
        log.error(
            f"{LogTag.TODO} Error bulk completing todos",
            error=str(e),
            error_type=type(e).__name__,
            user_id=user_id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to bulk complete todos: {e!s}",
        ) from e


async def bulk_move_todos(todo_ids: list[str], project_id: str, user_id: str) -> list[TodoResponse]:
    """Move multiple todos to a different project using a bulk operation."""
    log.set(
        component="todo_bulk_service",
        operation="bulk_move_todos",
        user_id=user_id,
        target_project_id=project_id,
        todo_count=len(todo_ids),
    )
    try:
        project = await project_repository.get(project_id, user_id=user_id)
        if not project:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Project with id {project_id} not found",
            )

        modified = await todo_repository.bulk_update(
            user_id, todo_ids, TodoUpdate(project_id=project_id)
        )
        if modified == 0:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="No todos found to move"
            )

        updated = await todo_repository.find_by_ids(user_id, todo_ids)
        log.info(
            f"{LogTag.TODO} Bulk moved todos to project for user",
            modified=modified,
            project_id=project_id,
            user_id=user_id,
        )
        return [TodoResponse.from_document(todo) for todo in updated]

    except HTTPException:
        raise
    except Exception as e:
        log.error(
            f"{LogTag.TODO} Error bulk moving todos",
            error=str(e),
            error_type=type(e).__name__,
            user_id=user_id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to bulk move todos: {e!s}",
        ) from e


async def bulk_delete_todos(todo_ids: list[str], user_id: str) -> None:
    """Delete multiple todos, with the sub-todos of any parent among them."""
    log.set(
        component="todo_bulk_service",
        operation="bulk_delete_todos",
        user_id=user_id,
        todo_count=len(todo_ids),
    )
    try:
        result = await TodoService.bulk_delete_todos(todo_ids, user_id)
        if not result.success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="No todos found to delete"
            )
        log.info(
            f"{LogTag.TODO} Bulk deleted todos for user",
            deleted=len(result.success),
            user_id=user_id,
        )

    except HTTPException:
        raise
    except Exception as e:
        log.error(
            f"{LogTag.TODO} Error bulk deleting todos",
            error=str(e),
            error_type=type(e).__name__,
            user_id=user_id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to bulk delete todos: {e!s}",
        ) from e
