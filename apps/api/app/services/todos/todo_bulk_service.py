"""Optimized bulk operations for todos."""

from fastapi import HTTPException, status

from app.constants.log_tags import LogTag
from app.db.repositories.projects import project_repository
from app.db.repositories.todos import todo_repository
from app.models.todo_models import (
    BulkOperationResponse,
    TodoResponse,
    TodoUpdate,
)
from app.services.todos.todo_service import TodoService
from shared.py.wide_events import log


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


async def bulk_delete_todos(todo_ids: list[str], user_id: str) -> BulkOperationResponse:
    """Delete multiple todos, with the sub-todos of any parent among them; say which were not found."""
    log.set(
        component="todo_bulk_service",
        operation="bulk_delete_todos",
        user_id=user_id,
        todo_count=len(todo_ids),
    )
    try:
        result = await TodoService.bulk_delete_todos(todo_ids, user_id)
        log.info(
            f"{LogTag.TODO} Bulk deleted todos for user",
            deleted=len(result.success),
            not_found=len(result.failed),
            user_id=user_id,
        )
        # Unknown ids are reported in result.failed for the caller to name, not raised.
        return result
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
