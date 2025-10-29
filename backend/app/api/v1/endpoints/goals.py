from typing import List, Union

from bson import ObjectId
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from fastapi.websockets import WebSocketState

from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.config.loggers import goals_logger as logger
from app.decorators import tiered_rate_limit
from app.db.mongodb.collections import goals_collection
from app.models.goals_models import (
    GoalCreate,
    GoalResponse,
    RoadmapUnavailableResponse,
    UpdateNodeRequest,
)
from app.services.goals_service import (
    create_goal_service,
    delete_goal_service,
    generate_roadmap_with_llm_stream,
    get_goal_service,
    get_user_goals_service,
    update_goal_with_roadmap_service,
    update_node_status_service,
)

router = APIRouter()


@router.post(
    "/goals",
    response_model=GoalResponse,
    summary="Create a goal",
    description="Creates a new goal for the authenticated user.",
)
@tiered_rate_limit("goal_tracking")
async def create_goal(goal: GoalCreate, user: dict = Depends(get_current_user)):
    """
    Create a new goal.
    """
    return await create_goal_service(goal, user)


@router.get(
    "/goals/{goal_id}",
    response_model=Union[GoalResponse, RoadmapUnavailableResponse],
    summary="Get goal details",
    description="Fetch the details of a specific goal using its ID.",
)
async def get_goal(goal_id: str, user: dict = Depends(get_current_user)):
    """
    Retrieve a goal by its ID.
    """
    return await get_goal_service(goal_id, user)


@router.get(
    "/goals",
    response_model=List[GoalResponse],
    summary="List all goals",
    description="Fetch all goals for the authenticated user.",
)
async def get_user_goals(user: dict = Depends(get_current_user)):
    """
    List all goals for the current user.
    """
    return await get_user_goals_service(user)


@router.delete(
    "/goals/{goal_id}",
    response_model=GoalResponse,
    summary="Delete a goal",
    description="Deletes a specific goal using its ID.",
)
async def delete_goal(goal_id: str, user: dict = Depends(get_current_user)):
    """
    Delete a goal by its ID.
    """
    return await delete_goal_service(goal_id, user)


@router.patch(
    "/goals/{goal_id}/roadmap/nodes/{node_id}",
    response_model=GoalResponse,
    summary="Update node status",
    description="Updates the completion status of a node in the roadmap.",
)
async def update_node_status(
    goal_id: str,
    node_id: str,
    update_data: UpdateNodeRequest,
    user: dict = Depends(get_current_user),
):
    """
    Update the status of a node in the roadmap.
    """
    return await update_node_status_service(goal_id, node_id, update_data, user)


@router.websocket("/ws/roadmap")
async def websocket_generate_roadmap(websocket: WebSocket):
    """
    WebSocket for generating roadmaps.

    Expects a JSON message containing 'goal_id' and 'goal_title' and streams
    the generated roadmap back to the client.
    """
    await websocket.accept()
    try:
        data = await websocket.receive_json()
        goal_id = data.get("goal_id")
        goal_title = data.get("goal_title")

        if not goal_id or not goal_title:
            logger.warning("Invalid data received in websocket for roadmap generation.")
            await websocket.send_json({"error": "Invalid data received"})
            return

        # Verify goal exists before proceeding
        goal = await goals_collection.find_one({"_id": ObjectId(goal_id)})
        if not goal:
            logger.error(f"Goal {goal_id} not found")
            await websocket.send_json({"error": "Goal not found"})
            return

        logger.info(
            f"Starting roadmap generation for goal {goal_id} titled '{goal_title}'."
        )
        await websocket.send_json({"status": "Generating roadmap..."})

        try:
            generated_roadmap = None

            async for chunk_data in generate_roadmap_with_llm_stream(goal_title):
                # Send progress updates to the client
                if "progress" in chunk_data:
                    await websocket.send_json({"status": chunk_data["progress"]})
                elif "roadmap" in chunk_data:
                    # Store the final roadmap data
                    generated_roadmap = chunk_data["roadmap"]
                    await websocket.send_json(
                        {
                            "status": "Roadmap generated successfully!",
                            "roadmap": generated_roadmap,
                        }
                    )
                elif "error" in chunk_data:
                    # Send error message and stop processing
                    await websocket.send_json({"error": chunk_data["error"]})
                    return

            # Update the goal with the generated roadmap
            if generated_roadmap:
                update_success = await update_goal_with_roadmap_service(
                    goal_id, generated_roadmap
                )

                if update_success:
                    # Send final success message
                    await websocket.send_json(
                        {
                            "status": "Goal updated successfully with roadmap!",
                            "goal_id": goal_id,
                            "success": True,
                        }
                    )
                else:
                    await websocket.send_json(
                        {"error": "Failed to update goal with roadmap"}
                    )
            else:
                await websocket.send_json({"error": "No roadmap was generated"})

        except Exception as e:
            logger.error(f"Error generating roadmap for goal {goal_id}: {str(e)}")
            await websocket.send_json({"error": f"Roadmap generation failed: {str(e)}"})

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected.")
    except Exception as e:
        logger.error(f"WebSocket error: {str(e)}")
        try:
            await websocket.send_json({"error": f"WebSocket error: {str(e)}"})
        except Exception as send_error:
            logger.error(
                f"Failed to send error message via WebSocket: {str(send_error)}"
            )
    finally:
        # Ensure WebSocket is closed
        try:
            if websocket.client_state == WebSocketState.CONNECTED:
                await websocket.close()
        except Exception as close_error:
            logger.error(f"Failed to close WebSocket: {str(close_error)}")
