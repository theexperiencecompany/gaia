from datetime import datetime
import json

from bson import ObjectId
from fastapi import HTTPException

from app.db.mongodb.collections import goals_collection
from app.db.redis import ONE_YEAR_TTL, get_cache, set_cache
from app.models.goals_models import GoalCreate, GoalResponse, UpdateNodeRequest
from app.services.todos.sync_service import (
    _invalidate_goal_caches,
    sync_goal_node_completion,
)
from app.utils.goals_utils import goal_helper
from shared.py.wide_events import log


async def create_goal_service(goal: GoalCreate, user: dict) -> GoalResponse:
    """
    Create a new goal for the authenticated user.

    Args:
        goal (GoalCreate): The goal data to be created.
        user (dict): The authenticated user's data.

    Returns:
        GoalResponse: The created goal's details.

    Raises:
        HTTPException: If goal creation fails.
    """
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(status_code=403, detail="Not authenticated")

    log.set(
        service="goals_service",
        operation="create_goal",
        user_id=user_id,
        goal={
            "title": goal.title,
            "node_count": 0,
            "is_completed": False,
        },
    )
    goal_data = {
        "title": goal.title,
        "description": goal.description,
        "created_at": datetime.now().isoformat(),
        "user_id": user_id,
        "roadmap": {"nodes": [], "edges": []},
    }

    try:
        result = await goals_collection.insert_one(goal_data)

        # Use the inserted data directly instead of fetching it back
        goal_data["_id"] = result.inserted_id

        # Invalidate user's goals list cache and statistics
        await _invalidate_goal_caches(user_id)

        formatted_goal = goal_helper(goal_data)
        log.info(f"Goal created successfully for user {user_id}. Cache invalidated.")
        return GoalResponse(**formatted_goal)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create goal {e}")


async def get_goal_service(goal_id: str, user: dict) -> dict:
    """
    Retrieve a goal by its ID for the authenticated user.

    Args:
        goal_id (str): The goal's ID.
        user (dict): The authenticated user's data.

    Returns:
        dict: The goal's details if found, or a message prompting roadmap generation.
    """
    user_id = user.get("user_id")
    if not user_id:
        log.warning("Unauthorized attempt to access goal details.")
        raise HTTPException(status_code=403, detail="Not authenticated")

    log.set(service="goals_service", operation="get_goal", user_id=user_id, goal_id=goal_id)
    cache_key = f"goal_cache:{goal_id}"
    cached_goal = await get_cache(cache_key)
    if cached_goal:
        log.info(f"Goal {goal_id} fetched from cache.")
        # Handle both string and dict cached data
        if isinstance(cached_goal, str):
            return json.loads(cached_goal)
        return cached_goal

    goal = await goals_collection.find_one({"_id": ObjectId(goal_id)})
    if not goal:
        log.error(f"Goal with ID {goal_id} not found.")
        raise HTTPException(status_code=404, detail="Goal not found")

    roadmap = goal.get("roadmap", {})
    if not roadmap.get("nodes") or not roadmap.get("edges"):
        log.info(f"Goal {goal_id} has no roadmap. Prompting user to generate one.")
        return {
            "message": "Roadmap not available. Please generate it using the WebSocket.",
            "id": goal_id,
            "title": goal["title"],
        }

    goal_helper_result = goal_helper(goal)
    await set_cache(cache_key, json.dumps(goal_helper_result), ONE_YEAR_TTL)
    log.info(f"Goal {goal_id} details fetched successfully.")
    return goal_helper_result


async def get_user_goals_service(user: dict) -> list:
    """
    List all goals for the authenticated user.

    Args:
        user (dict): The authenticated user's data.

    Returns:
        list: A list of goals.
    """
    user_id = user.get("user_id")
    if not user_id:
        log.warning("Unauthorized attempt to list user goals.")
        raise HTTPException(status_code=403, detail="Not authenticated")

    cache_key = f"goals_cache:{user_id}"
    cached_goals = await get_cache(cache_key)
    if cached_goals:
        log.info(f"Fetched user goals from cache for user {user_id}.")
        # Handle both string and dict cached data
        if isinstance(cached_goals, str):
            parsed_data = json.loads(cached_goals)
            return parsed_data.get("goals", [])
        return cached_goals.get("goals", [])

    goals = await goals_collection.find({"user_id": user_id}).to_list(None)
    goals_list = [goal_helper(goal) for goal in goals]

    # Cache the goals list as JSON string for consistency
    await set_cache(cache_key, json.dumps({"goals": goals_list}), ONE_YEAR_TTL)
    log.info(f"Listed all goals for user {user_id}.")
    return goals_list


async def delete_goal_service(goal_id: str, user: dict) -> dict:
    """
    Delete a specific goal by its ID for the authenticated user.

    Args:
        goal_id (str): The ID of the goal to delete.
        user (dict): The authenticated user's data.

    Returns:
        dict: The details of the deleted goal.
    """
    user_id = user.get("user_id")
    if not user_id:
        log.warning("Unauthorized attempt to delete goal.")
        raise HTTPException(status_code=403, detail="Not authenticated")

    goal = await goals_collection.find_one({"_id": ObjectId(goal_id), "user_id": user_id})
    if not goal:
        log.error(f"Goal {goal_id} not found for user {user_id}.")
        raise HTTPException(status_code=404, detail="Goal not found")

    result = await goals_collection.delete_one({"_id": ObjectId(goal_id)})
    if result.deleted_count == 0:
        log.error(f"Failed to delete goal {goal_id}.")
        raise HTTPException(status_code=500, detail="Failed to delete the goal")

    await _invalidate_goal_caches(user_id, goal_id)

    log.info(f"Goal {goal_id} deleted successfully by user {user_id}.")
    return goal_helper(goal)


async def update_node_status_service(
    goal_id: str, node_id: str, update_data: UpdateNodeRequest, user: dict
) -> dict:
    """
    Update the completion status of a node in a goal's roadmap.

    Args:
        goal_id (str): The ID of the goal.
        node_id (str): The ID of the node to update.
        update_data (UpdateNodeRequest): Data containing the updated status.
        user (dict): The authenticated user's data.

    Returns:
        dict: The updated goal's details.
    """
    user_id = user.get("user_id")
    if not user_id:
        log.warning("Unauthorized attempt to update node status.")
        raise HTTPException(status_code=403, detail="Not authenticated")

    log.set(
        service="goals_service",
        operation="update_node_status",
        user_id=user_id,
        goal={
            "id": goal_id,
            "node_id": node_id,
            "is_complete": update_data.is_complete,
        },
    )
    # Use atomic find_one_and_update with positional operator
    # First, verify the node exists in the goal
    goal = await goals_collection.find_one({"_id": ObjectId(goal_id), "roadmap.nodes.id": node_id})
    if not goal:
        # Check if goal exists at all
        goal_exists = await goals_collection.find_one({"_id": ObjectId(goal_id)})
        if not goal_exists:
            log.error(f"Goal {goal_id} not found.")
            raise HTTPException(status_code=404, detail="Goal not found")
        log.error(f"Node {node_id} not found in goal {goal_id}.")
        raise HTTPException(status_code=404, detail="Node not found in roadmap")

    # Atomically update the specific node using positional operator
    updated_goal = await goals_collection.find_one_and_update(
        {"_id": ObjectId(goal_id), "roadmap.nodes.id": node_id},
        {"$set": {"roadmap.nodes.$.data.isComplete": update_data.is_complete}},
        return_document=True,
    )

    # Sync completion status with corresponding todo
    await sync_goal_node_completion(goal_id, node_id, update_data.is_complete, user_id)

    await _invalidate_goal_caches(user_id, goal_id)

    log.info(f"Node status updated for node {node_id} in goal {goal_id}.")
    return goal_helper(updated_goal)
