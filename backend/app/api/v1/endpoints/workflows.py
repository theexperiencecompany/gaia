"""
Clean workflow API router for GAIA workflow system.
Provides CRUD operations, execution, and status endpoints.
"""

from datetime import datetime, timezone

from app.api.v1.dependencies.oauth_dependencies import (
    get_current_user,
    get_user_timezone_from_preferences,
)
from app.config.loggers import general_logger as logger
from app.db.mongodb.collections import workflows_collection
from app.decorators import tiered_rate_limit
from app.models.workflow_models import (
    CreateWorkflowRequest,
    PublicWorkflowsResponse,
    PublishWorkflowResponse,
    RegenerateStepsRequest,
    TriggerConfig,
    TriggerType,
    UpdateWorkflowRequest,
    WorkflowExecutionRequest,
    WorkflowExecutionResponse,
    WorkflowListResponse,
    WorkflowResponse,
    WorkflowStatusResponse,
)
from app.services.workflow import WorkflowService
from fastapi import APIRouter, Depends, HTTPException, status

router = APIRouter()


@router.post("/workflows", response_model=WorkflowResponse)
@tiered_rate_limit("workflow_operations")
async def create_workflow(
    request: CreateWorkflowRequest,
    user: dict = Depends(get_current_user),
    user_timezone: str = Depends(get_user_timezone_from_preferences),
):
    """Create a new workflow with automatic timezone detection."""
    try:
        # Pass user timezone to the service for automatic population
        workflow = await WorkflowService.create_workflow(
            request, user["user_id"], user_timezone=user_timezone
        )
        return WorkflowResponse(
            workflow=workflow, message="Workflow created successfully"
        )

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Error creating workflow: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create workflow",
        )


@router.get("/workflows", response_model=WorkflowListResponse)
async def list_workflows(user: dict = Depends(get_current_user)):
    """List all workflows for the current user."""
    try:
        workflows = await WorkflowService.list_workflows(user["user_id"])
        return WorkflowListResponse(workflows=workflows)

    except Exception as e:
        logger.error(f"Error listing workflows for user {user['user_id']}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list workflows",
        )


@router.post(
    "/workflows/{workflow_id}/execute", response_model=WorkflowExecutionResponse
)
@tiered_rate_limit("workflow_operations")
async def execute_workflow(
    workflow_id: str,
    request: WorkflowExecutionRequest,
    user: dict = Depends(get_current_user),
):
    """Execute a workflow (run now)."""
    try:
        result = await WorkflowService.execute_workflow(
            workflow_id, request, user["user_id"]
        )
        return result

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Error executing workflow {workflow_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to execute workflow",
        )


@router.get("/workflows/{workflow_id}/status", response_model=WorkflowStatusResponse)
async def get_workflow_status(workflow_id: str, user: dict = Depends(get_current_user)):
    """Get the current status of a workflow (for polling)."""
    try:
        status_response = await WorkflowService.get_workflow_status(
            workflow_id, user["user_id"]
        )
        return status_response

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        logger.error(f"Error getting workflow status {workflow_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get workflow status",
        )


@router.post("/workflows/{workflow_id}/activate", response_model=WorkflowResponse)
async def activate_workflow(
    workflow_id: str,
    user: dict = Depends(get_current_user),
    user_timezone: str = Depends(get_user_timezone_from_preferences),
):
    """Activate a workflow (enable its trigger)."""
    try:
        workflow = await WorkflowService.activate_workflow(
            workflow_id, user["user_id"], user_timezone=user_timezone
        )
        if not workflow:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Workflow {workflow_id} not found",
            )

        return WorkflowResponse(
            workflow=workflow, message="Workflow activated successfully"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error activating workflow {workflow_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to activate workflow",
        )


@router.post("/workflows/{workflow_id}/deactivate", response_model=WorkflowResponse)
async def deactivate_workflow(
    workflow_id: str,
    user: dict = Depends(get_current_user),
    user_timezone: str = Depends(get_user_timezone_from_preferences),
):
    """Deactivate a workflow (disable its trigger)."""
    try:
        workflow = await WorkflowService.deactivate_workflow(
            workflow_id, user["user_id"], user_timezone=user_timezone
        )
        if not workflow:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Workflow {workflow_id} not found",
            )

        return WorkflowResponse(
            workflow=workflow, message="Workflow deactivated successfully"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deactivating workflow {workflow_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to deactivate workflow",
        )


@router.post(
    "/workflows/{workflow_id}/regenerate-steps", response_model=WorkflowResponse
)
@tiered_rate_limit("workflow_operations")
async def regenerate_workflow_steps(
    workflow_id: str,
    request: RegenerateStepsRequest,
    user: dict = Depends(get_current_user),
):
    """Regenerate steps for an existing workflow with optional parameters."""
    try:
        workflow = await WorkflowService.regenerate_workflow_steps(
            workflow_id,
            user["user_id"],
            regeneration_reason=request.reason,
            force_different_tools=request.force_different_tools,
        )
        if not workflow:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Workflow not found",
            )

        return WorkflowResponse(
            workflow=workflow, message="Workflow regeneration started"
        )

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Error regenerating workflow steps: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to regenerate workflow steps",
        )


@router.post("/workflows/from-todo", response_model=WorkflowResponse)
@tiered_rate_limit("workflow_operations")
async def create_workflow_from_todo(
    request: dict,  # {todo_id: str, todo_title: str, todo_description?: str}
    user: dict = Depends(get_current_user),
    user_timezone: str = Depends(get_user_timezone_from_preferences),
):
    """Create a workflow from a todo item with automatic timezone detection."""
    try:
        todo_id = request.get("todo_id")
        todo_title = request.get("todo_title")
        todo_description = request.get("todo_description", "")

        if not todo_id or not todo_title:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="todo_id and todo_title are required",
            )

        # Create workflow using modern workflow system
        workflow_request = CreateWorkflowRequest(
            title=f"Todo: {todo_title}",
            description=todo_description or f"Workflow for todo: {todo_title}",
            trigger_config=TriggerConfig(type=TriggerType.MANUAL, enabled=True),
            generate_immediately=True,  # Generate steps immediately for todos
        )

        workflow = await WorkflowService.create_workflow(
            workflow_request, user["user_id"], user_timezone=user_timezone
        )

        return WorkflowResponse(
            workflow=workflow, message="Workflow created from todo successfully"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating workflow from todo: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create workflow from todo",
        )


@router.post("/workflows/{workflow_id}/publish", response_model=PublishWorkflowResponse)
@tiered_rate_limit("workflow_operations")
async def publish_workflow(
    workflow_id: str,
    user: dict = Depends(get_current_user),
):
    """Publish a workflow to the community marketplace."""
    try:
        # Check if workflow exists and belongs to user
        workflow = await workflows_collection.find_one(
            {"_id": workflow_id, "user_id": user["user_id"]}
        )

        if not workflow:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Workflow not found or access denied",
            )

        # Update workflow to be public
        await workflows_collection.update_one(
            {"_id": workflow_id},
            {
                "$set": {
                    "is_public": True,
                    "created_by": user["user_id"],
                    "updated_at": datetime.now(timezone.utc),
                }
            },
        )

        logger.info(f"Published workflow {workflow_id} by user {user['user_id']}")

        return PublishWorkflowResponse(
            message="Workflow published successfully", workflow_id=workflow_id
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error publishing workflow {workflow_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to publish workflow",
        )


@router.post("/workflows/{workflow_id}/unpublish")
@tiered_rate_limit("workflow_operations")
async def unpublish_workflow(
    workflow_id: str,
    user: dict = Depends(get_current_user),
):
    """Remove a workflow from the community marketplace."""
    try:
        # Check if workflow exists and belongs to user
        workflow = await workflows_collection.find_one(
            {"_id": workflow_id, "user_id": user["user_id"]}
        )

        if not workflow:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Workflow not found or access denied",
            )

        # Update workflow to be private
        await workflows_collection.update_one(
            {"_id": workflow_id},
            {
                "$set": {"is_public": False, "updated_at": datetime.now(timezone.utc)},
                "$unset": {"upvotes": "", "upvoted_by": ""},
            },
        )

        logger.info(f"Unpublished workflow {workflow_id} by user {user['user_id']}")

        return {"message": "Workflow unpublished successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error unpublishing workflow {workflow_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to unpublish workflow",
        )


@router.get("/workflows/community", response_model=PublicWorkflowsResponse)
async def get_public_workflows(
    limit: int = 20,
    offset: int = 0,
    user: dict = Depends(get_current_user),
):
    """Get public workflows from the community marketplace."""
    try:
        # Get public workflows sorted by upvotes
        pipeline = [
            {"$match": {"is_public": True}},
            {"$sort": {"upvotes": -1, "created_at": -1}},
            {"$skip": offset},
            {"$limit": limit},
            {
                "$lookup": {
                    "from": "users",
                    "let": {"creator_id": "$created_by"},
                    "pipeline": [
                        {
                            "$match": {
                                "$expr": {
                                    "$eq": ["$_id", {"$toObjectId": "$$creator_id"}]
                                }
                            }
                        },
                        {"$project": {"name": 1, "email": 1, "picture": 1, "_id": 0}},
                    ],
                    "as": "creator_info",
                }
            },
            {
                "$project": {
                    "_id": 1,
                    "title": 1,
                    "description": 1,
                    "steps": {
                        "$map": {
                            "input": "$steps",
                            "as": "step",
                            "in": {
                                "title": "$$step.title",
                                "tool_name": "$$step.tool_name",
                                "tool_category": "$$step.tool_category",
                                "description": "$$step.description",
                            },
                        }
                    },
                    "upvotes": 1,
                    "upvoted_by": 1,
                    "created_at": 1,
                    "created_by": 1,
                    "creator_info": 1,
                }
            },
        ]

        workflows = await workflows_collection.aggregate(pipeline).to_list(length=limit)

        # Get total count
        total = await workflows_collection.count_documents({"is_public": True})

        # Format workflows with creator info
        formatted_workflows = []
        current_user_id = user["user_id"]

        for workflow in workflows:
            creator_info = (
                workflow.get("creator_info", [{}])[0]
                if workflow.get("creator_info")
                else {}
            )

            # Check if current user has upvoted this workflow
            upvoted_by = workflow.get("upvoted_by", [])
            is_upvoted = current_user_id in upvoted_by

            formatted_workflow = {
                "id": workflow["_id"],
                "title": workflow["title"],
                "description": workflow["description"],
                "steps": workflow.get("steps", []),
                "upvotes": workflow.get("upvotes", 0),
                "is_upvoted": is_upvoted,
                "created_at": workflow["created_at"],
                "creator": {
                    "id": workflow.get("created_by"),
                    "name": creator_info.get("name", "Unknown"),
                    "avatar": creator_info.get(
                        "picture"
                    ),  # Use 'picture' field from user model
                },
            }
            formatted_workflows.append(formatted_workflow)

        return PublicWorkflowsResponse(workflows=formatted_workflows, total=total)

    except Exception as e:
        logger.error(f"Error fetching public workflows: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch public workflows",
        )


@router.post("/workflows/{workflow_id}/upvote")
@tiered_rate_limit("workflow_operations")
async def upvote_workflow(
    workflow_id: str,
    user: dict = Depends(get_current_user),
):
    """Upvote a community workflow."""
    try:
        # Check if workflow exists and is public
        workflow = await workflows_collection.find_one(
            {"_id": workflow_id, "is_public": True}
        )

        if not workflow:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Public workflow not found",
            )

        user_id = user["user_id"]

        # Use atomic operations to prevent race conditions
        # Try to add upvote first (most common case)
        add_result = await workflows_collection.update_one(
            {
                "_id": workflow_id,
                "is_public": True,
                "upvoted_by": {"$ne": user_id},  # Only if user hasn't upvoted
            },
            {
                "$push": {"upvoted_by": user_id},
                "$inc": {"upvotes": 1},
                "$set": {"updated_at": datetime.now(timezone.utc)},
            },
        )

        if add_result.modified_count > 0:
            return {"message": "Upvote added successfully", "action": "added"}

        # If add failed, try to remove upvote (user already upvoted)
        remove_result = await workflows_collection.update_one(
            {
                "_id": workflow_id,
                "is_public": True,
                "upvoted_by": user_id,  # Only if user has upvoted
            },
            {
                "$pull": {"upvoted_by": user_id},
                "$inc": {"upvotes": -1},
                "$set": {"updated_at": datetime.now(timezone.utc)},
            },
        )

        if remove_result.modified_count > 0:
            return {"message": "Upvote removed successfully", "action": "removed"}

        # Neither add nor remove worked - workflow might not exist or be private
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workflow not found or not accessible",
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error upvoting workflow {workflow_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to upvote workflow",
        )


@router.get("/workflows/{workflow_id}", response_model=WorkflowResponse)
async def get_workflow(workflow_id: str, user: dict = Depends(get_current_user)):
    """Get a specific workflow by ID."""
    try:
        workflow = await WorkflowService.get_workflow(workflow_id, user["user_id"])
        if not workflow:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Workflow {workflow_id} not found",
            )

        return WorkflowResponse(
            workflow=workflow, message="Workflow retrieved successfully"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting workflow {workflow_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get workflow",
        )


@router.put("/workflows/{workflow_id}")
async def update_workflow(
    workflow_id: str,
    request: UpdateWorkflowRequest,
    user: dict = Depends(get_current_user),
    user_timezone: str = Depends(get_user_timezone_from_preferences),
):
    """Update an existing workflow with automatic timezone detection."""
    try:
        workflow = await WorkflowService.update_workflow(
            workflow_id, request, user["user_id"], user_timezone=user_timezone
        )
        if not workflow:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Workflow {workflow_id} not found",
            )

        return WorkflowResponse(
            workflow=workflow, message="Workflow updated successfully"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating workflow {workflow_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update workflow",
        )


@router.delete("/workflows/{workflow_id}")
async def delete_workflow(workflow_id: str, user: dict = Depends(get_current_user)):
    """Delete a workflow."""
    try:
        success = await WorkflowService.delete_workflow(workflow_id, user["user_id"])
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Workflow {workflow_id} not found",
            )

        return {"message": "Workflow deleted successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting workflow {workflow_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete workflow",
        )


@router.post("/workflows/validate-upvotes")
@tiered_rate_limit("workflow_operations")
async def validate_upvote_data(user: dict = Depends(get_current_user)):
    """Validate and fix upvote data consistency across all workflows."""
    try:
        # Only allow admins or system users to run this validation
        # You might want to add proper admin role checking here

        inconsistent_workflows = []
        fixed_count = 0

        # Find all public workflows
        async for workflow in workflows_collection.find({"is_public": True}):
            upvoted_by = workflow.get("upvoted_by", [])
            upvotes_count = workflow.get("upvotes", 0)
            actual_count = len(upvoted_by)

            # Check for inconsistency
            if upvotes_count != actual_count:
                inconsistent_workflows.append(
                    {
                        "workflow_id": workflow["_id"],
                        "stored_count": upvotes_count,
                        "actual_count": actual_count,
                        "difference": actual_count - upvotes_count,
                    }
                )

                # Fix the inconsistency
                await workflows_collection.update_one(
                    {"_id": workflow["_id"]},
                    {
                        "$set": {
                            "upvotes": actual_count,
                            "updated_at": datetime.now(timezone.utc),
                        }
                    },
                )
                fixed_count += 1

        return {
            "message": f"Validation complete. Fixed {fixed_count} inconsistent workflows.",
            "inconsistencies_found": len(inconsistent_workflows),
            "details": inconsistent_workflows,
        }

    except Exception as e:
        logger.error(f"Error validating upvote data: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to validate upvote data",
        )


@router.get("/workflows/{workflow_id}/upvote-status")
async def get_workflow_upvote_status(
    workflow_id: str, user: dict = Depends(get_current_user)
):
    """Check upvote status and data consistency for a specific workflow."""
    try:
        workflow = await workflows_collection.find_one(
            {"_id": workflow_id, "is_public": True}
        )

        if not workflow:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Public workflow not found",
            )

        upvoted_by = workflow.get("upvoted_by", [])
        upvotes_count = workflow.get("upvotes", 0)
        actual_count = len(upvoted_by)
        user_id = user["user_id"]

        return {
            "workflow_id": workflow_id,
            "upvotes_stored": upvotes_count,
            "upvotes_actual": actual_count,
            "is_consistent": upvotes_count == actual_count,
            "user_has_upvoted": user_id in upvoted_by,
            "total_unique_upvoters": actual_count,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Error checking upvote status for workflow {workflow_id}: {str(e)}"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to check upvote status",
        )
