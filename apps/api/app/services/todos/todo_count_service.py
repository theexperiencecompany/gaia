"""
Service for managing todo counts and ensuring consistency.
"""


from bson import ObjectId

from app.config.loggers import todos_logger
from app.db.mongodb.collections import projects_collection, todos_collection


async def update_project_todo_count(project_id: str, user_id: str) -> None:
    """
    Recalculate and update the todo count for a specific project.

    Args:
        project_id: ID of the project to update
        user_id: ID of the user who owns the project
    """
    try:
        # Count all todos (both completed and non-completed) for this project
        count = await todos_collection.count_documents(
            {"user_id": user_id, "project_id": project_id}
        )

        # Update the project's todo_count
        await projects_collection.update_one(
            {"_id": ObjectId(project_id), "user_id": user_id},
            {"$set": {"todo_count": count}},
        )

        todos_logger.info(f"Updated project {project_id} todo count to {count}")

    except Exception as e:
        todos_logger.error(f"Error updating project todo count: {str(e)}")


async def sync_all_project_counts(user_id: str) -> None:
    """
    Sync todo counts for all projects belonging to a user.

    Args:
        user_id: ID of the user
    """
    try:
        # Get all projects for the user
        projects = await projects_collection.find({"user_id": user_id}).to_list(
            length=None
        )

        for project in projects:
            project_id = (
                str(project["_id"]) if not project.get("is_default") else "inbox"
            )

            # Count todos for this project
            count = await todos_collection.count_documents(
                {"user_id": user_id, "project_id": project_id}
            )

            # Update the count
            await projects_collection.update_one(
                {"_id": project["_id"]}, {"$set": {"todo_count": count}}
            )

        todos_logger.info(f"Synced all project counts for user {user_id}")

    except Exception as e:
        todos_logger.error(f"Error syncing project counts: {str(e)}")
