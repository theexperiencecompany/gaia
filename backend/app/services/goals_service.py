import json
from datetime import datetime

from app.config.loggers import goals_logger as logger
from app.db.mongodb.collections import goals_collection
from app.db.redis import ONE_YEAR_TTL, get_cache, set_cache
from app.agents.llm.client import init_llm
from app.agents.prompts.goal_prompts import (
    ROADMAP_GENERATOR,
    ROADMAP_INSTRUCTIONS,
    ROADMAP_JSON_STRUCTURE,
)
from app.models.goals_models import GoalCreate, GoalResponse, UpdateNodeRequest
from app.services.todos.sync_service import (
    _invalidate_goal_caches,
    create_goal_project_and_todo,
    sync_goal_node_completion,
)
from app.utils.goals_utils import goal_helper
from bson import ObjectId
from fastapi import HTTPException
from langchain_core.messages import HumanMessage


async def generate_roadmap_with_llm_stream(title: str):
    """
    Generate a roadmap using LLM streaming for real-time updates.

    Args:
        title (str): The goal title to generate a roadmap for

    Yields:
        dict: Streaming progress updates and final roadmap data
    """
    detailed_prompt = ROADMAP_GENERATOR.format(
        title=title,
        instructions=ROADMAP_INSTRUCTIONS,
        json_structure=json.dumps(ROADMAP_JSON_STRUCTURE, indent=2),
    )

    try:
        # Initialize the LLM client
        llm = init_llm()

        # Send initial progress message
        yield {"progress": f"Starting roadmap generation for '{title}'..."}

        # Create message for LLM
        messages = [HumanMessage(content=detailed_prompt)]

        # Stream the response
        complete_response = ""
        chunk_count = 0

        async for chunk in llm.astream(messages):
            chunk_count += 1
            content = chunk if isinstance(chunk, str) else chunk.text()

            if content:
                complete_response += str(content)

                # Send progress updates every 10 chunks
                if chunk_count % 10 == 0:
                    yield {
                        "progress": f"Generating roadmap... ({len(complete_response)} characters)"
                    }

        # Send completion message
        yield {"progress": "Processing generated roadmap..."}

        # Try to parse the complete response as JSON
        try:
            # Clean the response - sometimes LLM adds extra text
            json_start = complete_response.find("{")
            json_end = complete_response.rfind("}") + 1

            if json_start != -1 and json_end != 0:
                json_str = complete_response[json_start:json_end]
                roadmap_data = json.loads(json_str)

                # Validate the structure
                if "nodes" in roadmap_data and "edges" in roadmap_data:
                    yield {"progress": "Roadmap generation completed successfully!"}
                    yield {"roadmap": roadmap_data}
                else:
                    logger.error("Generated roadmap missing required fields")
                    yield {"error": "Generated roadmap is missing required structure"}
            else:
                logger.error("No valid JSON found in LLM response")
                yield {"error": "Could not parse roadmap from LLM response"}

        except json.JSONDecodeError as e:
            logger.error(f"JSON parsing error: {e}")
            logger.error(f"Raw response: {complete_response}")
            yield {"error": f"Failed to parse roadmap JSON: {str(e)}"}

    except Exception as e:
        logger.error(f"LLM Generation Error: {e}")
        yield {"error": f"Roadmap generation failed: {str(e)}"}


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
        logger.info(f"Goal created successfully for user {user_id}. Cache invalidated.")
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
        logger.warning("Unauthorized attempt to access goal details.")
        raise HTTPException(status_code=403, detail="Not authenticated")

    cache_key = f"goal_cache:{goal_id}"
    cached_goal = await get_cache(cache_key)
    if cached_goal:
        logger.info(f"Goal {goal_id} fetched from cache.")
        # Handle both string and dict cached data
        if isinstance(cached_goal, str):
            return json.loads(cached_goal)
        else:
            return cached_goal

    goal = await goals_collection.find_one({"_id": ObjectId(goal_id)})
    if not goal:
        logger.error(f"Goal with ID {goal_id} not found.")
        raise HTTPException(status_code=404, detail="Goal not found")

    roadmap = goal.get("roadmap", {})
    if not roadmap.get("nodes") or not roadmap.get("edges"):
        logger.info(f"Goal {goal_id} has no roadmap. Prompting user to generate one.")
        return {
            "message": "Roadmap not available. Please generate it using the WebSocket.",
            "id": goal_id,
            "title": goal["title"],
        }

    goal_helper_result = goal_helper(goal)
    await set_cache(cache_key, json.dumps(goal_helper_result), ONE_YEAR_TTL)
    logger.info(f"Goal {goal_id} details fetched successfully.")
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
        logger.warning("Unauthorized attempt to list user goals.")
        raise HTTPException(status_code=403, detail="Not authenticated")

    cache_key = f"goals_cache:{user_id}"
    cached_goals = await get_cache(cache_key)
    if cached_goals:
        logger.info(f"Fetched user goals from cache for user {user_id}.")
        # Handle both string and dict cached data
        if isinstance(cached_goals, str):
            parsed_data = json.loads(cached_goals)
            return parsed_data.get("goals", [])
        else:
            return cached_goals.get("goals", [])

    goals = await goals_collection.find({"user_id": user_id}).to_list(None)
    goals_list = [goal_helper(goal) for goal in goals]

    # Cache the goals list as JSON string for consistency
    await set_cache(cache_key, json.dumps({"goals": goals_list}), ONE_YEAR_TTL)
    logger.info(f"Listed all goals for user {user_id}.")
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
        logger.warning("Unauthorized attempt to delete goal.")
        raise HTTPException(status_code=403, detail="Not authenticated")

    goal = await goals_collection.find_one(
        {"_id": ObjectId(goal_id), "user_id": user_id}
    )
    if not goal:
        logger.error(f"Goal {goal_id} not found for user {user_id}.")
        raise HTTPException(status_code=404, detail="Goal not found")

    result = await goals_collection.delete_one({"_id": ObjectId(goal_id)})
    if result.deleted_count == 0:
        logger.error(f"Failed to delete goal {goal_id}.")
        raise HTTPException(status_code=500, detail="Failed to delete the goal")

    await _invalidate_goal_caches(user_id, goal_id)

    logger.info(f"Goal {goal_id} deleted successfully by user {user_id}.")
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
        logger.warning("Unauthorized attempt to update node status.")
        raise HTTPException(status_code=403, detail="Not authenticated")

    # Use atomic find_one_and_update with positional operator
    # First, verify the node exists in the goal
    goal = await goals_collection.find_one(
        {"_id": ObjectId(goal_id), "roadmap.nodes.id": node_id}
    )
    if not goal:
        # Check if goal exists at all
        goal_exists = await goals_collection.find_one({"_id": ObjectId(goal_id)})
        if not goal_exists:
            logger.error(f"Goal {goal_id} not found.")
            raise HTTPException(status_code=404, detail="Goal not found")
        else:
            logger.error(f"Node {node_id} not found in goal {goal_id}.")
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

    logger.info(f"Node status updated for node {node_id} in goal {goal_id}.")
    return goal_helper(updated_goal)


async def update_goal_with_roadmap_service(goal_id: str, roadmap_data: dict) -> bool:
    """
    Update a goal with generated roadmap data, create todo project, and invalidate caches.

    Args:
        goal_id (str): The ID of the goal to update
        roadmap_data (dict): The roadmap data to save

    Returns:
        bool: True if update was successful, False otherwise
    """
    try:
        # Get the goal to find the user_id - we need this for create_goal_project_and_todo
        goal = await goals_collection.find_one({"_id": ObjectId(goal_id)})
        if not goal:
            logger.error(f"Goal {goal_id} not found for roadmap update")
            return False

        user_id = goal.get("user_id")
        goal_title = goal.get("title", "Untitled Goal")

        # Create project and todo with subtasks for the roadmap
        # This function will update the goal with subtask_ids and todo info
        project_id = await create_goal_project_and_todo(
            goal_id, goal_title, roadmap_data, user_id
        )

        # Invalidate relevant caches
        if user_id:
            await _invalidate_goal_caches(user_id, goal_id)
            logger.info(
                f"Goal caches invalidated for goal {goal_id} and user {user_id}"
            )

        logger.info(
            f"Goal {goal_id} successfully updated with roadmap and todo project {project_id}"
        )
        return True

    except Exception as e:
        logger.error(f"Error updating goal {goal_id} with roadmap: {str(e)}")
        return False
