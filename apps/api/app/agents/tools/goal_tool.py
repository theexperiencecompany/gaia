import json
from typing import Annotated, Any, Dict, Optional

from app.config.loggers import chat_logger as logger
from app.constants.cache import DEFAULT_CACHE_TTL
from app.db.mongodb.collections import goals_collection
from app.db.redis import delete_cache, get_cache, set_cache
from app.decorators import with_doc, with_rate_limiting
from app.templates.docstrings.goal_tool_docs import (
    CREATE_GOAL,
    DELETE_GOAL,
    GENERATE_ROADMAP,
    GET_GOAL,
    GET_GOAL_STATISTICS,
    LIST_GOALS,
    SEARCH_GOALS,
    UPDATE_GOAL_NODE,
)
from app.models.goals_models import GoalCreate, UpdateNodeRequest
from app.services.goals_service import (
    delete_goal_service,
    generate_roadmap_with_llm_stream,
    get_goal_service,
    get_user_goals_service,
    update_goal_with_roadmap_service,
    update_node_status_service,
)
from app.utils.chat_utils import get_user_id_from_config
from bson import ObjectId
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.config import get_stream_writer


async def invalidate_goal_caches(user_id: str, goal_id: Optional[str] = None) -> None:
    """
    Invalidate goal-related caches for a user.

    This function ensures cache consistency by invalidating all relevant caches
    when goal data is modified. It invalidates:
    - User's goals list cache
    - Goal statistics cache (since stats depend on all goals)
    - Specific goal cache (if goal_id provided)

    Args:
        user_id: The user ID whose caches should be invalidated
        goal_id: Optional specific goal ID to invalidate
    """
    try:
        # Always invalidate user's goals list cache
        cache_key_goals = f"goals_cache:{user_id}"
        await delete_cache(cache_key_goals)

        # Invalidate goal statistics cache
        cache_key_stats = f"goal_stats_cache:{user_id}"
        await delete_cache(cache_key_stats)

        # Invalidate specific goal cache if provided
        if goal_id:
            cache_key_goal = f"goal_cache:{goal_id}"
            await delete_cache(cache_key_goal)

        logger.info(
            f"Goal caches invalidated for user {user_id}"
            + (f" and goal {goal_id}" if goal_id else "")
        )

    except Exception as e:
        logger.error(f"Error invalidating goal caches: {str(e)}")
        # Don't raise exception as cache invalidation failure shouldn't break the operation


@tool
@with_rate_limiting("goal_tracking")
@with_doc(CREATE_GOAL)
async def create_goal(
    config: RunnableConfig,
    title: Annotated[str, "Title of the goal (required)"],
    description: Annotated[Optional[str], "Detailed description of the goal"] = None,
) -> Dict[str, Any]:
    try:
        logger.info(f"Goal Tool: Creating goal with title '{title}'")
        user_id = get_user_id_from_config(config)
        if not user_id:
            return {"error": "User authentication required", "goal": None}
        user = {"user_id": user_id}

        # Stream progress update
        writer = get_stream_writer()
        writer(
            {
                "goal_data": {
                    "action": "creating",
                    "message": f"Creating goal: {title}",
                }
            }
        )

        goal_data = GoalCreate(
            title=title,
            description=description or "",
        )

        # Do not remove, circular import.
        from app.services.goals_service import create_goal_service

        result = await create_goal_service(goal_data, user)
        goal_dict = result.model_dump(mode="json")

        # Invalidate caches since we created a new goal
        await invalidate_goal_caches(user["user_id"])

        # Stream the created goal to frontend
        writer(
            {
                "goal_data": {
                    "goals": [goal_dict],
                    "action": "create",
                    "message": f"Goal created: {title}",
                }
            }
        )

        return {"goal": goal_dict, "error": None}

    except Exception as e:
        error_msg = f"Error creating goal: {str(e)}"
        logger.error(error_msg)
        return {"error": error_msg, "goal": None}


@tool
@with_doc(LIST_GOALS)
async def list_goals(config: RunnableConfig) -> Dict[str, Any]:
    try:
        logger.info("Goal Tool: Listing all goals")
        user_id = get_user_id_from_config(config)
        if not user_id:
            return {"error": "User authentication required", "goals": []}
        user = {"user_id": user_id}

        # Stream progress update
        writer = get_stream_writer()
        writer(
            {
                "goal_data": {
                    "action": "fetching",
                    "message": "Fetching your goals...",
                }
            }
        )

        results = await get_user_goals_service(user)

        # Stream the goals to frontend
        writer(
            {
                "goal_data": {
                    "goals": results,
                    "action": "list",
                    "message": f"Found {len(results)} goal{'s' if len(results) != 1 else ''}",
                }
            }
        )

        return {"goals": results, "count": len(results), "error": None}

    except Exception as e:
        error_msg = f"Error listing goals: {str(e)}"
        logger.error(error_msg)
        return {"error": error_msg, "goals": []}


@tool
@with_doc(GET_GOAL)
async def get_goal(
    config: RunnableConfig,
    goal_id: Annotated[str, "ID of the goal to retrieve (required)"],
) -> Dict[str, Any]:
    try:
        logger.info(f"Goal Tool: Getting goal {goal_id}")
        user_id = get_user_id_from_config(config)
        if not user_id:
            return {"error": "User authentication required", "goal": None}
        user = {"user_id": user_id}

        # Stream progress update
        writer = get_stream_writer()
        writer(
            {
                "goal_data": {
                    "action": "fetching",
                    "message": "Fetching goal details...",
                }
            }
        )

        result = await get_goal_service(goal_id, user)

        # Handle case where roadmap is not available
        if isinstance(result, dict) and "message" in result:
            writer(
                {
                    "goal_data": {
                        "action": "roadmap_needed",
                        "message": result["message"],
                        "goal_id": goal_id,
                    }
                }
            )
            return {"goal": result, "error": None}

        # Stream the goal to frontend
        writer(
            {
                "goal_data": {
                    "goals": [result],
                    "action": "get",
                    "message": "Goal details retrieved",
                }
            }
        )

        return {"goal": result, "error": None}

    except Exception as e:
        error_msg = f"Error getting goal: {str(e)}"
        logger.error(error_msg)
        return {"error": error_msg, "goal": None}


@tool
@with_doc(DELETE_GOAL)
async def delete_goal(
    config: RunnableConfig,
    goal_id: Annotated[str, "ID of the goal to delete (required)"],
) -> Dict[str, Any]:
    try:
        logger.info(f"Goal Tool: Deleting goal {goal_id}")
        user_id = get_user_id_from_config(config)
        if not user_id:
            return {"error": "User authentication required", "success": False}
        user = {"user_id": user_id}

        # Stream progress update
        writer = get_stream_writer()
        writer(
            {
                "goal_data": {
                    "action": "deleting",
                    "message": "Deleting goal...",
                }
            }
        )

        result = await delete_goal_service(goal_id, user)
        goal_title = result.get("title", "Unknown Goal")

        # Invalidate caches since we deleted a goal
        await invalidate_goal_caches(user["user_id"], goal_id)

        # Stream the deletion confirmation to frontend
        writer(
            {
                "goal_data": {
                    "action": "delete",
                    "message": f"Deleted goal: {goal_title}",
                    "deleted_goal_id": goal_id,
                }
            }
        )

        return {"success": True, "deleted_goal": result, "error": None}

    except Exception as e:
        error_msg = f"Error deleting goal: {str(e)}"
        logger.error(error_msg)
        return {"error": error_msg, "success": False}


@tool
@with_doc(GENERATE_ROADMAP)
async def generate_roadmap(
    config: RunnableConfig,
    goal_id: Annotated[str, "ID of the goal to generate roadmap for (required)"],
    regenerate: Annotated[
        Optional[bool], "Whether to overwrite existing roadmap"
    ] = False,
) -> Dict[str, Any]:
    try:
        logger.info(f"Goal Tool: Generating roadmap for goal {goal_id}")
        user_id = get_user_id_from_config(config)
        if not user_id:
            return {"error": "User authentication required", "roadmap": None}
        user = {"user_id": user_id}

        # Get the goal to check if it exists and get the title
        goal = await goals_collection.find_one({"_id": ObjectId(goal_id)})
        if not goal:
            return {"error": "Goal not found", "roadmap": None}

        # Check if roadmap already exists and regenerate is False
        existing_roadmap = goal.get("roadmap", {})
        if (
            not regenerate
            and existing_roadmap.get("nodes")
            and len(existing_roadmap.get("nodes", [])) > 0
        ):
            return {
                "error": "Roadmap already exists. Use regenerate=True to overwrite.",
                "roadmap": None,
            }

        goal_title = goal.get("title", "Untitled Goal")

        writer = get_stream_writer()

        # Stream initial progress
        writer(
            {
                "goal_data": {
                    "action": "generating_roadmap",
                    "message": f"Starting roadmap generation for '{goal_title}'...",
                    "goal_id": goal_id,
                }
            }
        )

        # Generate roadmap with streaming updates
        final_roadmap = None
        async for update in generate_roadmap_with_llm_stream(goal_title):
            if "progress" in update:
                # Stream progress updates
                writer(
                    {
                        "goal_data": {
                            "action": "generating_roadmap",
                            "message": update["progress"],
                            "goal_id": goal_id,
                        }
                    }
                )
            elif "roadmap" in update:
                final_roadmap = update["roadmap"]
            elif "error" in update:
                writer(
                    {
                        "goal_data": {
                            "action": "error",
                            "message": update["error"],
                            "goal_id": goal_id,
                        }
                    }
                )
                return {"error": update["error"], "roadmap": None}

        if final_roadmap and isinstance(final_roadmap, dict):
            # Update the goal with the roadmap and create todos
            success = await update_goal_with_roadmap_service(goal_id, final_roadmap)
            if success:
                # Get the updated goal
                updated_goal = await goals_collection.find_one(
                    {"_id": ObjectId(goal_id)}
                )
                if updated_goal:
                    from app.utils.goals_utils import goal_helper

                    goal_dict = goal_helper(updated_goal)

                    # Invalidate caches since we generated a roadmap
                    await invalidate_goal_caches(user["user_id"], goal_id)

                    # Stream the completed roadmap
                    writer(
                        {
                            "goal_data": {
                                "goals": [goal_dict],
                                "action": "roadmap_generated",
                                "message": f"Roadmap generated and todos created for '{goal_title}'",
                                "goal_id": goal_id,
                            }
                        }
                    )

                    return {"roadmap": final_roadmap, "goal": goal_dict, "error": None}

            return {"error": "Failed to save roadmap", "roadmap": None}
        else:
            return {"error": "Failed to generate roadmap", "roadmap": None}

    except Exception as e:
        error_msg = f"Error generating roadmap: {str(e)}"
        logger.error(error_msg)
        return {"error": error_msg, "roadmap": None}


@tool
@with_doc(UPDATE_GOAL_NODE)
async def update_goal_node(
    config: RunnableConfig,
    goal_id: Annotated[str, "ID of the goal containing the node (required)"],
    node_id: Annotated[str, "ID of the node to update (required)"],
    is_complete: Annotated[bool, "Whether the node/task is complete (required)"],
) -> Dict[str, Any]:
    try:
        logger.info(
            f"Goal Tool: Updating node {node_id} in goal {goal_id} to complete={is_complete}"
        )
        user_id = get_user_id_from_config(config)
        if not user_id:
            return {"error": "User authentication required", "goal": None}
        user = {"user_id": user_id}

        # Stream progress update
        writer = get_stream_writer()
        writer(
            {
                "goal_data": {
                    "action": "updating_progress",
                    "message": "Updating task progress...",
                }
            }
        )

        update_data = UpdateNodeRequest(is_complete=is_complete)
        result = await update_node_status_service(goal_id, node_id, update_data, user)

        # Invalidate caches since we updated goal progress
        await invalidate_goal_caches(user["user_id"], goal_id)

        goal_dict = result
        status_text = "completed" if is_complete else "reopened"

        # Stream the updated goal to frontend
        writer(
            {
                "goal_data": {
                    "goals": [goal_dict],
                    "action": "node_updated",
                    "message": f"Task {status_text} in goal: {goal_dict.get('title', 'Unknown')}",
                }
            }
        )

        return {"goal": goal_dict, "error": None}

    except Exception as e:
        error_msg = f"Error updating goal node: {str(e)}"
        logger.error(error_msg)
        return {"error": error_msg, "goal": None}


@tool
@with_doc(SEARCH_GOALS)
async def search_goals(
    config: RunnableConfig,
    query: Annotated[str, "Search query to match against goals (required)"],
    limit: Annotated[int, "Maximum number of results to return"] = 10,
) -> Dict[str, Any]:
    try:
        logger.info(f"Goal Tool: Searching goals with query '{query}'")
        user_id = get_user_id_from_config(config)
        if not user_id:
            return {"error": "User authentication required", "goals": []}
        user = {"user_id": user_id}

        # Stream progress update
        writer = get_stream_writer()
        writer(
            {
                "goal_data": {
                    "action": "searching",
                    "message": f"Searching goals for '{query}'...",
                }
            }
        )

        # Perform text search on goals collection
        # Using MongoDB text search on title and description
        search_filter = {
            "user_id": user["user_id"],
            "$or": [
                {"title": {"$regex": query, "$options": "i"}},
                {"description": {"$regex": query, "$options": "i"}},
            ],
        }

        cursor = goals_collection.find(search_filter).limit(limit)
        goals = await cursor.to_list(length=limit)

        # Convert to goal format
        from app.utils.goals_utils import goal_helper

        results = [goal_helper(goal) for goal in goals]

        # Stream the search results to frontend
        writer(
            {
                "goal_data": {
                    "goals": results,
                    "action": "search",
                    "message": f"Found {len(results)} goal{'s' if len(results) != 1 else ''} matching '{query}'",
                }
            }
        )

        return {
            "goals": results,
            "count": len(results),
            "search_query": query,
            "error": None,
        }

    except Exception as e:
        error_msg = f"Error searching goals: {str(e)}"
        logger.error(error_msg)
        return {"error": error_msg, "goals": []}


@tool
@with_doc(GET_GOAL_STATISTICS)
async def get_goal_statistics(config: RunnableConfig) -> Dict[str, Any]:
    try:
        logger.info("Goal Tool: Getting goal statistics")
        user_id = get_user_id_from_config(config)
        if not user_id:
            return {"error": "User authentication required", "stats": None}
        user = {"user_id": user_id}

        # Stream progress update
        writer = get_stream_writer()
        writer(
            {
                "goal_data": {
                    "action": "calculating_stats",
                    "message": "Calculating goal statistics...",
                }
            }
        )

        user_id = user["user_id"]

        # Check cache first
        cache_key_stats = f"goal_stats_cache:{user_id}"
        cached_stats = await get_cache(cache_key_stats)
        if cached_stats:
            logger.info(f"Goal statistics fetched from cache for user {user_id}")
            if isinstance(cached_stats, str):
                stats = json.loads(cached_stats)
            else:
                stats = cached_stats

            # Stream cached stats to frontend
            writer(
                {
                    "goal_data": {
                        "stats": stats,
                        "action": "stats",
                        "message": "Here's your goal progress overview",
                    }
                }
            )
            return {"stats": stats, "error": None}

        # Get all goals for the user
        all_goals = await goals_collection.find({"user_id": user_id}).to_list(None)

        total_goals = len(all_goals)
        goals_with_roadmaps = 0
        total_nodes = 0
        completed_nodes = 0
        active_goals = []

        for goal in all_goals:
            roadmap = goal.get("roadmap", {})
            nodes = roadmap.get("nodes", [])

            if nodes:
                goals_with_roadmaps += 1
                goal_completed_nodes = 0
                goal_total_nodes = len(
                    [
                        n
                        for n in nodes
                        if n.get("data", {}).get("type") not in ["start", "end"]
                    ]
                )

                for node in nodes:
                    node_data = node.get("data", {})
                    if node_data.get("type") not in [
                        "start",
                        "end",
                    ]:  # Skip start/end nodes
                        total_nodes += 1
                        if node_data.get("isComplete"):
                            completed_nodes += 1
                            goal_completed_nodes += 1

                # Calculate goal progress
                if goal_total_nodes > 0:
                    goal_progress = round(
                        (goal_completed_nodes / goal_total_nodes) * 100
                    )
                else:
                    goal_progress = 0

                # Add to active goals if not 100% complete
                if goal_progress < 100:
                    from app.utils.goals_utils import goal_helper

                    goal_dict = goal_helper(goal)
                    goal_dict["progress"] = goal_progress
                    active_goals.append(goal_dict)

        # Calculate overall completion rate
        overall_completion_rate = (
            round((completed_nodes / total_nodes) * 100) if total_nodes > 0 else 0
        )

        stats = {
            "total_goals": total_goals,
            "goals_with_roadmaps": goals_with_roadmaps,
            "total_tasks": total_nodes,
            "completed_tasks": completed_nodes,
            "overall_completion_rate": overall_completion_rate,
            "active_goals": active_goals[:5],  # Limit to top 5 active goals
            "active_goals_count": len(active_goals),
        }

        # Cache the computed statistics (1 hour to balance freshness with performance)
        await set_cache(cache_key_stats, json.dumps(stats), DEFAULT_CACHE_TTL)
        logger.info(f"Goal statistics computed and cached for user {user_id}")

        # Stream the stats to frontend
        writer(
            {
                "goal_data": {
                    "stats": stats,
                    "action": "stats",
                    "message": "Here's your goal progress overview",
                }
            }
        )

        return {"stats": stats, "error": None}

    except Exception as e:
        error_msg = f"Error getting goal statistics: {str(e)}"
        logger.error(error_msg)
        return {"error": error_msg, "stats": None}


# Export all goal tools as a list for easy registration
tools = [
    create_goal,
    list_goals,
    get_goal,
    delete_goal,
    generate_roadmap,
    update_goal_node,
    search_goals,
    get_goal_statistics,
]
