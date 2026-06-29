from typing import Union

from fastapi import APIRouter, Depends

from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.decorators import tiered_rate_limit
from app.models.goals_models import (
    GoalCreate,
    GoalResponse,
    RoadmapUnavailableResponse,
    UpdateNodeRequest,
)
from app.services.goals_service import (
    create_goal_service,
    delete_goal_service,
    get_goal_service,
    get_user_goals_service,
    update_node_status_service,
)
from shared.py.wide_events import log

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
    log.set(user={"id": user.get("user_id")}, goal={"operation": "create"})
    result = await create_goal_service(goal, user)
    log.set(
        goal={
            "operation": "create",
            "id": str(result.id) if hasattr(result, "id") else None,
        }
    )
    return result


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
    log.set(user={"id": user.get("user_id")}, goal={"operation": "get", "id": goal_id})
    return await get_goal_service(goal_id, user)


@router.get(
    "/goals",
    response_model=list[GoalResponse],
    summary="List all goals",
    description="Fetch all goals for the authenticated user.",
)
async def get_user_goals(user: dict = Depends(get_current_user)):
    """
    List all goals for the current user.
    """
    log.set(user={"id": user.get("user_id")}, goal={"operation": "list"})
    goals = await get_user_goals_service(user)
    log.set(goal={"operation": "list", "result_count": len(goals) if goals else 0})
    return goals


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
    log.set(user={"id": user.get("user_id")}, goal={"operation": "delete", "id": goal_id})
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
    log.set(
        user={"id": user.get("user_id")},
        goal={"operation": "update_node", "id": goal_id},
    )
    return await update_node_status_service(goal_id, node_id, update_data, user)
