"""
Optimized bulk operations for todos.
"""

from fastapi import HTTPException, status

from app.constants.log_tags import LogTag
from app.db.repositories.projects import project_repository
from app.db.repositories.todos import todo_repository
from app.models.todo_models import TodoResponse, TodoUpdate
from app.services.analytics_service import AnalyticsEvents, capture_event
from app.services.tracked_todo_service import tracked_todo_service
from app.utils.canvas_vector_utils import delete_canvas_embedding
from shared.py.wide_events import log


async def bulk_complete_todos(todo_ids: list[str], user_id: str) -> list[TodoResponse]:
    """Mark multiple todos as completed using a bulk operation.

    Tracked todos run through their completion lifecycle first; the rest are
    updated in a single write.
    """
    log.set(
        component="todo_bulk_service",
        operation="bulk_complete_todos",
        user_id=user_id,
        todo_count=len(todo_ids),
    )
    try:
        docs = await todo_repository.find_by_ids(user_id, todo_ids)

        tracked = [doc for doc in docs if doc.vfs_path]
        for doc in tracked:
            try:
                await tracked_todo_service.complete_tracked_todo(
                    doc.id, user_id, "Completed via bulk operation"
                )
            except Exception as e:
                log.warning("tracked_todo.bulk_complete_failed", todo_id=doc.id, error=str(e))

        remaining_ids = [doc.id for doc in docs if not doc.vfs_path]
        modified = 0
        if remaining_ids:
            modified = await todo_repository.bulk_update(
                user_id, remaining_ids, TodoUpdate(completed=True)
            )

        if modified + len(tracked) == 0:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No todos found or already completed",
            )

        updated = await todo_repository.find_by_ids(user_id, todo_ids)
        log.info(
            f"{LogTag.TODO} Bulk completed todos",
            todo_count=modified + len(tracked),
            user_id=user_id,
        )
        capture_event(
            user_id,
            AnalyticsEvents.TODO_TOGGLED,
            {"count": modified + len(tracked)},
        )
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
        )


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
        )


async def bulk_delete_todos(todo_ids: list[str], user_id: str) -> None:
    """Delete multiple todos using a bulk operation."""
    log.set(
        component="todo_bulk_service",
        operation="bulk_delete_todos",
        user_id=user_id,
        todo_count=len(todo_ids),
    )
    try:
        docs = await todo_repository.find_by_ids(user_id, todo_ids)

        # Canvas/log content lives on each todo doc and is removed by the delete
        # below — only the ChromaDB canvas embedding needs explicit cleanup.
        for doc in docs:
            if not doc.vfs_path:
                continue
            try:
                await delete_canvas_embedding(doc.id)
            except Exception as e:
                log.warning(
                    "tracked_todo.bulk_delete_embedding_failed", todo_id=doc.id, error=str(e)
                )

        deleted = await todo_repository.bulk_delete(user_id, todo_ids)
        if deleted == 0:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="No todos found to delete"
            )

        log.info(f"{LogTag.TODO} Bulk deleted todos for user", deleted=deleted, user_id=user_id)
        capture_event(user_id, AnalyticsEvents.TODO_DELETED, {"count": deleted})

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
        )
