"""
Optimized bulk operations for todos.
"""

from datetime import UTC, datetime

from bson import ObjectId
from fastapi import HTTPException, status

from app.db.mongodb.collections import todos_collection
from app.db.redis import delete_cache
from app.db.utils import serialize_document
from app.models.todo_models import TodoResponse
from app.services.tracked_todo_service import tracked_todo_service
from app.services.vfs.mongo_vfs import MongoVFS
from app.utils.canvas_vector_utils import delete_canvas_embedding
from shared.py.wide_events import log


async def bulk_complete_todos(todo_ids: list[str], user_id: str) -> list[TodoResponse]:
    """
    Mark multiple todos as completed using bulk operation.

    Args:
        todo_ids: List of todo IDs to complete
        user_id: ID of the user

    Returns:
        List[TodoResponse]: Updated todos
    """
    log.set(
        service="todo_bulk_service",
        operation="bulk_complete_todos",
        user_id=user_id,
        todo_count=len(todo_ids),
    )
    try:
        # Convert string IDs to ObjectIds
        object_ids = [ObjectId(todo_id) for todo_id in todo_ids]

        # Handle tracked todos lifecycle before bulk update
        tracked_cursor = todos_collection.find(
            {
                "_id": {"$in": object_ids},
                "user_id": user_id,
                "vfs_path": {"$exists": True, "$ne": None},
            },
            {"_id": 1},
        )
        tracked_docs = await tracked_cursor.to_list(length=None)
        tracked_ids = {doc["_id"] for doc in tracked_docs}
        for doc in tracked_docs:
            try:
                await tracked_todo_service.complete_tracked_todo(
                    str(doc["_id"]), user_id, "Completed via bulk operation"
                )
            except Exception as e:
                log.warning(
                    "tracked_todo.bulk_complete_failed",
                    todo_id=str(doc["_id"]),
                    error=str(e),
                )

        # Only bulk-update the non-tracked todos (tracked ones already updated by service)
        remaining_ids = [oid for oid in object_ids if oid not in tracked_ids]

        if not remaining_ids and not tracked_ids:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No todos found or already completed",
            )

        modified_count = 0
        if remaining_ids:
            result = await todos_collection.update_many(
                {"_id": {"$in": remaining_ids}, "user_id": user_id},
                {
                    "$set": {
                        "completed": True,
                        "updated_at": datetime.now(UTC),
                    }
                },
            )
            modified_count = result.modified_count

        total_modified = modified_count + len(tracked_ids)
        if total_modified == 0:
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

        log.info(f"Bulk completed {total_modified} todos for user {user_id}")

        return [TodoResponse(**serialize_document(todo)) for todo in todos]

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Error bulk completing todos: {e!s}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to bulk complete todos: {e!s}",
        )


async def bulk_move_todos(todo_ids: list[str], project_id: str, user_id: str) -> list[TodoResponse]:
    """
    Move multiple todos to a different project using bulk operation.

    Args:
        todo_ids: List of todo IDs to move
        project_id: Target project ID
        user_id: ID of the user

    Returns:
        List[TodoResponse]: Updated todos
    """
    log.set(
        service="todo_bulk_service",
        operation="bulk_move_todos",
        user_id=user_id,
        target_project_id=project_id,
        todo_count=len(todo_ids),
    )
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
                    "updated_at": datetime.now(UTC),
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

        log.info(
            f"Bulk moved {result.modified_count} todos to project {project_id} for user {user_id}"
        )

        return [TodoResponse(**serialize_document(todo)) for todo in todos]

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Error bulk moving todos: {e!s}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to bulk move todos: {e!s}",
        )


async def bulk_delete_todos(todo_ids: list[str], user_id: str) -> None:
    """
    Delete multiple todos using bulk operation.

    Args:
        todo_ids: List of todo IDs to delete
        user_id: ID of the user
    """
    log.set(
        service="todo_bulk_service",
        operation="bulk_delete_todos",
        user_id=user_id,
        todo_count=len(todo_ids),
    )
    try:
        # Convert string IDs to ObjectIds
        object_ids = [ObjectId(todo_id) for todo_id in todo_ids]

        # Get project IDs and vfs_path for cache clearing and tracked todo cleanup
        cursor = todos_collection.find(
            {"_id": {"$in": object_ids}, "user_id": user_id},
            {"project_id": 1, "vfs_path": 1},
        )
        todos_to_delete = await cursor.to_list(length=None)
        project_ids = set(
            todo.get("project_id") for todo in todos_to_delete if todo.get("project_id")
        )

        # Clean up tracked todo assets before deletion
        tracked_cursor = todos_collection.find(
            {
                "_id": {"$in": object_ids},
                "user_id": user_id,
                "vfs_path": {"$exists": True, "$ne": None},
            },
            {"_id": 1, "vfs_path": 1},
        )
        tracked_docs = await tracked_cursor.to_list(length=None)
        for doc in tracked_docs:
            tid = str(doc["_id"])
            try:
                await delete_canvas_embedding(tid)
            except Exception as e:
                log.warning(
                    "tracked_todo.bulk_delete_embedding_failed",
                    todo_id=tid,
                    error=str(e),
                )
            try:
                vfs = MongoVFS()
                await vfs.delete(path=doc["vfs_path"], user_id=user_id, recursive=True)
            except Exception as e:
                log.warning("tracked_todo.bulk_delete_vfs_failed", todo_id=tid, error=str(e))

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

        log.info(f"Bulk deleted {result.deleted_count} todos for user {user_id}")

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Error bulk deleting todos: {e!s}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to bulk delete todos: {e!s}",
        )
