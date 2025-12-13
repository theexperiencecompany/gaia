"""
Optimized bulk operations for todos.
"""

from datetime import datetime, timezone
from typing import List

from bson import ObjectId
from fastapi import HTTPException, status

from app.config.loggers import todos_logger
from app.db.mongodb.collections import todos_collection
from app.db.redis import delete_cache
from app.db.utils import serialize_document
from app.models.todo_models import TodoResponse


async def bulk_complete_todos(todo_ids: List[str], user_id: str) -> List[TodoResponse]:
    """
    Mark multiple todos as completed using bulk operation.

    Args:
        todo_ids: List of todo IDs to complete
        user_id: ID of the user

    Returns:
        List[TodoResponse]: Updated todos
    """
    try:
        # Convert string IDs to ObjectIds
        object_ids = [ObjectId(todo_id) for todo_id in todo_ids]

        # Perform bulk update
        result = await todos_collection.update_many(
            {"_id": {"$in": object_ids}, "user_id": user_id},
            {
                "$set": {
                    "completed": True,
                    "updated_at": datetime.now(timezone.utc),
                }
            },
        )

        if result.modified_count == 0:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No todos found or already completed",
            )

        # Fetch updated todos
        cursor = todos_collection.find({"_id": {"$in": object_ids}, "user_id": user_id})
        todos = await cursor.to_list(length=None)

        # Clear cache
        await delete_cache(f"todos:{user_id}")
        for todo in todos:
            await delete_cache(f"todo:{user_id}:{todo['_id']}")
            if todo.get("project_id"):
                await delete_cache(f"todos:{user_id}:project:{todo['project_id']}")

        todos_logger.info(
            f"Bulk completed {result.modified_count} todos for user {user_id}"
        )

        return [TodoResponse(**serialize_document(todo)) for todo in todos]

    except HTTPException:
        raise
    except Exception as e:
        todos_logger.error(f"Error bulk completing todos: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to bulk complete todos: {str(e)}",
        )


async def bulk_move_todos(
    todo_ids: List[str], project_id: str, user_id: str
) -> List[TodoResponse]:
    """
    Move multiple todos to a different project using bulk operation.

    Args:
        todo_ids: List of todo IDs to move
        project_id: Target project ID
        user_id: ID of the user

    Returns:
        List[TodoResponse]: Updated todos
    """
    try:
        # Verify project exists
        from app.db.mongodb.collections import projects_collection

        project = await projects_collection.find_one(
            {"_id": ObjectId(project_id), "user_id": user_id}
        )

        if not project:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Project with id {project_id} not found",
            )

        # Convert string IDs to ObjectIds
        object_ids = [ObjectId(todo_id) for todo_id in todo_ids]

        # Get old project IDs for cache clearing
        cursor = todos_collection.find(
            {"_id": {"$in": object_ids}, "user_id": user_id}, {"project_id": 1}
        )
        old_todos = await cursor.to_list(length=None)
        old_project_ids = set(
            todo.get("project_id") for todo in old_todos if todo.get("project_id")
        )

        # Perform bulk update
        result = await todos_collection.update_many(
            {"_id": {"$in": object_ids}, "user_id": user_id},
            {
                "$set": {
                    "project_id": project_id,
                    "updated_at": datetime.now(timezone.utc),
                }
            },
        )

        if result.modified_count == 0:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="No todos found to move"
            )

        # Fetch updated todos
        cursor = todos_collection.find({"_id": {"$in": object_ids}, "user_id": user_id})
        todos = await cursor.to_list(length=None)

        # Clear cache
        await delete_cache(f"todos:{user_id}")
        await delete_cache(f"todos:{user_id}:project:{project_id}")
        for old_project_id in old_project_ids:
            await delete_cache(f"todos:{user_id}:project:{old_project_id}")
        for todo_id in todo_ids:
            await delete_cache(f"todo:{user_id}:{todo_id}")

        todos_logger.info(
            f"Bulk moved {result.modified_count} todos to project {project_id} for user {user_id}"
        )

        return [TodoResponse(**serialize_document(todo)) for todo in todos]

    except HTTPException:
        raise
    except Exception as e:
        todos_logger.error(f"Error bulk moving todos: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to bulk move todos: {str(e)}",
        )


async def bulk_delete_todos(todo_ids: List[str], user_id: str) -> None:
    """
    Delete multiple todos using bulk operation.

    Args:
        todo_ids: List of todo IDs to delete
        user_id: ID of the user
    """
    try:
        # Convert string IDs to ObjectIds
        object_ids = [ObjectId(todo_id) for todo_id in todo_ids]

        # Get project IDs for cache clearing
        cursor = todos_collection.find(
            {"_id": {"$in": object_ids}, "user_id": user_id}, {"project_id": 1}
        )
        todos_to_delete = await cursor.to_list(length=None)
        project_ids = set(
            todo.get("project_id") for todo in todos_to_delete if todo.get("project_id")
        )

        # Perform bulk delete
        result = await todos_collection.delete_many(
            {"_id": {"$in": object_ids}, "user_id": user_id}
        )

        if result.deleted_count == 0:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="No todos found to delete"
            )

        # Clear cache
        await delete_cache(f"todos:{user_id}")
        for project_id in project_ids:
            await delete_cache(f"todos:{user_id}:project:{project_id}")
        for todo_id in todo_ids:
            await delete_cache(f"todo:{user_id}:{todo_id}")

        todos_logger.info(
            f"Bulk deleted {result.deleted_count} todos for user {user_id}"
        )

    except HTTPException:
        raise
    except Exception as e:
        todos_logger.error(f"Error bulk deleting todos: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to bulk delete todos: {str(e)}",
        )
