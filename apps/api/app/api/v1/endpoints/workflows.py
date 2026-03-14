"""
Clean workflow API router for GAIA workflow system.
Provides CRUD operations, execution, and status endpoints.
"""

from datetime import datetime, timezone

from app.api.v1.dependencies.oauth_dependencies import (
    get_current_user,
    get_user_timezone_from_preferences,
)
from app.api.v1.middleware.rate_limiter import limiter
from shared.py.wide_events import log, WorkflowContext
from app.db.mongodb.collections import workflows_collection
from app.decorators import tiered_rate_limit
from app.models.workflow_models import (
    CreateWorkflowRequest,
    GenerateWorkflowPromptRequest,
    GenerateWorkflowPromptResponse,
    PublicWorkflowsResponse,
    PublishWorkflowResponse,
    RegenerateStepsRequest,
    TriggerConfig,
    TriggerType,
    UpdateWorkflowRequest,
    Workflow,
    WorkflowExecutionRequest,
    WorkflowExecutionResponse,
    WorkflowListResponse,
    WorkflowResponse,
    WorkflowStatusResponse,
)
from app.models.workflow_execution_models import WorkflowExecutionsResponse
from app.services.workflow import WorkflowService
from app.services.workflow.service import generate_unique_workflow_slug
from app.services.workflow.generation_service import WorkflowGenerationService
from app.services.workflow.execution_service import (
    get_workflow_executions as get_executions,
)
from app.helpers.slug_helpers import parse_workflow_slug
from app.services.system_workflows.provisioner import reset_system_workflow_to_default
from app.utils.exceptions import TriggerRegistrationError
from app.utils.workflow_utils import transform_workflow_document
from fastapi import APIRouter, Depends, HTTPException, Request, status

router = APIRouter()


@router.post("/workflows", response_model=WorkflowResponse)
@tiered_rate_limit("workflow_operations")
async def create_workflow(
    request: CreateWorkflowRequest,
    user: dict = Depends(get_current_user),
    user_timezone: str = Depends(get_user_timezone_from_preferences),
):
    """Create a new workflow with automatic timezone detection."""
    log.set(
        user={"id": user["user_id"]},
        workflow=WorkflowContext(
            operation="create",
            title=request.title,
            trigger_type=str(request.trigger_config.type)
            if request.trigger_config
            else None,
        ),
    )

    try:
        # Strip system fields — these are set by the provisioner only
        request.is_system_workflow = False
        request.source_integration = None
        request.system_workflow_key = None
        # Pass user timezone to the service for automatic population
        workflow = await WorkflowService.create_workflow(
            request, user["user_id"], user_timezone=user_timezone
        )
        log.set(
            workflow=WorkflowContext(
                id=str(workflow.id),
                title=workflow.title,
                steps_count=len(workflow.steps) if workflow.steps else None,
                trigger_type=str(workflow.trigger_type)
                if hasattr(workflow, "trigger_type") and workflow.trigger_type
                else None,
            ),
            outcome="success",
        )
        return WorkflowResponse(
            workflow=workflow, message="Workflow created successfully"
        )

    except TriggerRegistrationError as e:
        # Specific error for trigger registration failures
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        log.error(f"Error creating workflow: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create workflow",
        )


@router.get("/workflows", response_model=WorkflowListResponse)
@limiter.limit("100/minute")
@limiter.limit("1000/hour")
async def list_workflows(request: Request, user: dict = Depends(get_current_user)):
    """List all workflows for the current user."""
    log.set(
        user={"id": user["user_id"]},
        workflow=WorkflowContext(operation="list"),
    )

    try:
        workflows = await WorkflowService.list_workflows(user["user_id"])
        log.set(
            workflow=WorkflowContext(result_count=len(workflows)),
            outcome="success",
        )
        return WorkflowListResponse(workflows=workflows)

    except Exception as e:
        log.error(f"Error listing workflows for user {user['user_id']}: {str(e)}")
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
    log.set(
        user={"id": user["user_id"]},
        workflow=WorkflowContext(operation="execute", id=workflow_id),
    )

    try:
        result = await WorkflowService.execute_workflow(
            workflow_id, request, user["user_id"]
        )
        log.set(
            workflow=WorkflowContext(
                execution_id=str(result.execution_id)
                if hasattr(result, "execution_id") and result.execution_id
                else None,
            ),
            outcome="success",
        )
        return result

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        log.error(f"Error executing workflow {workflow_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to execute workflow",
        )


@router.get(
    "/workflows/{workflow_id}/executions", response_model=WorkflowExecutionsResponse
)
@limiter.limit("100/minute")
async def get_workflow_executions(
    request: Request,
    workflow_id: str,
    limit: int = 10,
    offset: int = 0,
    user: dict = Depends(get_current_user),
):
    """Get execution history for a workflow."""
    log.set(
        user={"id": user["user_id"]},
        workflow=WorkflowContext(operation="list_executions", id=workflow_id),
    )

    try:
        limit = max(1, min(limit, 100))
        offset = max(0, offset)
        result = await get_executions(
            workflow_id=workflow_id,
            user_id=user["user_id"],
            limit=limit,
            offset=offset,
        )
        log.set(
            workflow=WorkflowContext(
                result_count=len(result.executions)
                if hasattr(result, "executions") and result.executions is not None
                else None,
            ),
            outcome="success",
        )
        return result
    except Exception as e:
        log.error(f"Error getting executions for workflow {workflow_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get workflow executions",
        )


@router.get("/workflows/{workflow_id}/status", response_model=WorkflowStatusResponse)
async def get_workflow_status(workflow_id: str, user: dict = Depends(get_current_user)):
    """Get the current status of a workflow (for polling)."""
    log.set(
        user={"id": user["user_id"]},
        workflow=WorkflowContext(operation="status", id=workflow_id),
    )

    try:
        status_response = await WorkflowService.get_workflow_status(
            workflow_id, user["user_id"]
        )
        log.set(
            workflow=WorkflowContext(
                execution_id=str(status_response.execution_id)
                if hasattr(status_response, "execution_id")
                and status_response.execution_id
                else None,
            ),
            outcome="success",
        )
        return status_response

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        log.error(f"Error getting workflow status {workflow_id}: {str(e)}")
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
    log.set(
        user={"id": user["user_id"]},
        workflow=WorkflowContext(id=workflow_id),
    )

    try:
        workflow = await WorkflowService.activate_workflow(
            workflow_id, user["user_id"], user_timezone=user_timezone
        )
        if not workflow:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Workflow {workflow_id} not found",
            )

        log.set(outcome="success")
        return WorkflowResponse(
            workflow=workflow, message="Workflow activated successfully"
        )

    except TriggerRegistrationError as e:
        # Specific error for trigger registration failures
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Error activating workflow {workflow_id}: {str(e)}")
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
    log.set(
        user={"id": user["user_id"]},
        workflow=WorkflowContext(id=workflow_id),
    )

    try:
        workflow = await WorkflowService.deactivate_workflow(
            workflow_id, user["user_id"], user_timezone=user_timezone
        )
        if not workflow:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Workflow {workflow_id} not found",
            )

        log.set(outcome="success")
        return WorkflowResponse(
            workflow=workflow, message="Workflow deactivated successfully"
        )

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Error deactivating workflow {workflow_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to deactivate workflow",
        )


@router.post(
    "/workflows/{workflow_id}/regenerate-steps", response_model=WorkflowResponse
)
async def regenerate_workflow_steps(
    workflow_id: str,
    request: RegenerateStepsRequest,
    user: dict = Depends(get_current_user),
):
    """Regenerate steps for an existing workflow with optional parameters."""
    log.set(
        user={"id": user["user_id"]},
        workflow=WorkflowContext(operation="regenerate_steps", id=workflow_id),
    )

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

        log.set(outcome="success")
        return WorkflowResponse(
            workflow=workflow, message="Workflow regeneration started"
        )

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        log.error(f"Error regenerating workflow steps: {str(e)}")
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
    log.set(
        user={"id": user["user_id"]},
        workflow=WorkflowContext(operation="create"),
    )

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
            description=f"Workflow for todo: {todo_title}",
            prompt=todo_description or f"Complete todo: {todo_title}",
            trigger_config=TriggerConfig(type=TriggerType.MANUAL, enabled=True),
            generate_immediately=True,  # Generate steps immediately for todos
        )

        workflow = await WorkflowService.create_workflow(
            workflow_request, user["user_id"], user_timezone=user_timezone
        )

        log.set(
            workflow=WorkflowContext(
                id=str(workflow.id),
                title=workflow.title,
                steps_count=len(workflow.steps) if workflow.steps else None,
            ),
            outcome="success",
        )
        return WorkflowResponse(
            workflow=workflow, message="Workflow created from todo successfully"
        )

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Error creating workflow from todo: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create workflow from todo",
        )


@router.post("/workflows/{workflow_id}/publish", response_model=PublishWorkflowResponse)
async def publish_workflow(
    workflow_id: str,
    user: dict = Depends(get_current_user),
):
    """Publish a workflow to the community marketplace."""
    log.set(
        user={"id": user["user_id"]},
        workflow=WorkflowContext(operation="publish", id=workflow_id),
    )

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

        # Generate slug if not already set
        publish_set: dict = {
            "is_public": True,
            "created_by": user["user_id"],
            "updated_at": datetime.now(timezone.utc),
        }
        if not workflow.get("slug"):
            publish_set["slug"] = await generate_unique_workflow_slug(
                workflow.get("title", ""),
                exclude_id=workflow_id,
            )

        # Update workflow to be public
        await workflows_collection.update_one(
            {"_id": workflow_id},
            {"$set": publish_set},
        )

        log.set(outcome="success")
        log.info(f"Published workflow {workflow_id} by user {user['user_id']}")

        return PublishWorkflowResponse(
            message="Workflow published successfully", workflow_id=workflow_id
        )

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Error publishing workflow {workflow_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to publish workflow",
        )


@router.post("/workflows/{workflow_id}/unpublish")
async def unpublish_workflow(
    workflow_id: str,
    user: dict = Depends(get_current_user),
):
    """Remove a workflow from the community marketplace."""
    log.set(
        user={"id": user["user_id"]},
        workflow=WorkflowContext(id=workflow_id),
    )

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
            },
        )

        log.set(outcome="success")
        log.info(f"Unpublished workflow {workflow_id} by user {user['user_id']}")

        return {"message": "Workflow unpublished successfully"}

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Error unpublishing workflow {workflow_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to unpublish workflow",
        )


@router.get("/workflows/explore", response_model=PublicWorkflowsResponse)
@limiter.limit("500/minute")
@limiter.limit("5000/hour")
async def get_explore_workflows(
    request: Request,
    limit: int = 25,
    offset: int = 0,
):
    """Get explore/featured workflows for the discover section."""
    try:
        return await WorkflowService.get_explore_workflows(limit=limit, offset=offset)
    except Exception as e:
        log.error(f"Error fetching explore workflows: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch explore workflows",
        )


@router.get("/workflows/community", response_model=PublicWorkflowsResponse)
@limiter.limit("500/minute")
@limiter.limit("5000/hour")
async def get_public_workflows(
    request: Request,
    limit: int = 20,
    offset: int = 0,
):
    """Get public workflows from the community marketplace."""
    try:
        return await WorkflowService.get_community_workflows(
            limit=limit, offset=offset, user_id=None
        )
    except Exception as e:
        log.error(f"Error fetching public workflows: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch public workflows",
        )


@router.get("/workflows/public/{workflow_ref}", response_model=WorkflowResponse)
@limiter.limit("500/minute")
@limiter.limit("5000/hour")
async def get_public_workflow(request: Request, workflow_ref: str):
    """Get a public workflow by ID (wf_xxx) or slug."""
    try:
        # IDs always start with "wf_" — slugs never do
        if workflow_ref.startswith("wf_"):
            query: dict = {"_id": workflow_ref, "is_public": True}
        else:
            query = {"slug": workflow_ref, "is_public": True}

        workflow_doc = await workflows_collection.find_one(query)

        # Fallback: parse slug to extract 8-char ID prefix
        if not workflow_doc:
            short_id = parse_workflow_slug(workflow_ref)
            if short_id:
                workflow_doc = await workflows_collection.find_one(
                    {
                        "_id": {"$regex": f"^wf_{short_id}"},
                        "is_public": True,
                    }
                )

        if not workflow_doc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Public workflow not found",
            )

        transformed_doc = transform_workflow_document(workflow_doc)
        workflow = Workflow(**transformed_doc)

        return WorkflowResponse(
            workflow=workflow, message="Workflow retrieved successfully"
        )
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Error getting public workflow {workflow_ref}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get workflow",
        )


@router.post(
    "/workflows/generate-prompt", response_model=GenerateWorkflowPromptResponse
)
async def generate_workflow_prompt_endpoint(
    request: GenerateWorkflowPromptRequest,
    user: dict = Depends(get_current_user),
) -> GenerateWorkflowPromptResponse:
    """Generate or improve workflow instructions using AI."""
    log.set(
        workflow=WorkflowContext(operation="generate_prompt"),
    )

    try:
        result = await WorkflowGenerationService.generate_workflow_prompt(
            title=request.title,
            description=request.description,
            trigger_config=request.trigger_config,
            existing_prompt=request.existing_prompt,
        )
        log.set(outcome="success")
        return GenerateWorkflowPromptResponse(**result)
    except Exception as e:
        log.error(f"Error generating workflow prompt: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate workflow prompt",
        )


@router.get("/workflows/{workflow_id}", response_model=WorkflowResponse)
@limiter.limit("500/minute")
@limiter.limit("5000/hour")
async def get_workflow(
    request: Request, workflow_id: str, user: dict = Depends(get_current_user)
):
    """Get a specific workflow by ID."""
    log.set(
        user={"id": user["user_id"]},
        workflow=WorkflowContext(operation="get", id=workflow_id),
    )

    try:
        workflow = await WorkflowService.get_workflow(workflow_id, user["user_id"])
        if not workflow:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Workflow {workflow_id} not found",
            )

        log.set(
            workflow=WorkflowContext(
                title=workflow.title,
                steps_count=len(workflow.steps)
                if hasattr(workflow, "steps") and workflow.steps
                else None,
            ),
            outcome="success",
        )
        return WorkflowResponse(
            workflow=workflow, message="Workflow retrieved successfully"
        )

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Error getting workflow {workflow_id}: {str(e)}")
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
    log.set(
        user={"id": user["user_id"]},
        workflow=WorkflowContext(operation="update", id=workflow_id),
    )

    try:
        workflow = await WorkflowService.update_workflow(
            workflow_id, request, user["user_id"], user_timezone=user_timezone
        )
        if not workflow:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Workflow {workflow_id} not found",
            )

        log.set(outcome="success")
        return WorkflowResponse(
            workflow=workflow, message="Workflow updated successfully"
        )

    except TriggerRegistrationError as e:
        # Specific error for trigger registration failures
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Error updating workflow {workflow_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update workflow",
        )


@router.post("/workflows/{workflow_id}/reset-to-default")
async def reset_workflow_to_default(
    workflow_id: str, user: dict = Depends(get_current_user)
):
    """Reset a GAIA system workflow to its original definition.

    Restores the workflow's title, description, steps, and trigger config to
    the defaults that were set when it was auto-provisioned. Preserves the
    workflow ID, activated state, and execution statistics.

    Only works on workflows where is_system_workflow=True.
    """
    log.set(
        user={"id": user["user_id"]},
        workflow=WorkflowContext(id=workflow_id),
    )

    try:
        success = await reset_system_workflow_to_default(
            workflow_id=workflow_id,
            user_id=user["user_id"],
        )
        if not success:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Workflow not found or is not a resettable system workflow.",
            )
        log.set(outcome="success")
        return {"success": True, "message": "Workflow reset to default."}

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Error resetting workflow {workflow_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to reset workflow",
        )


@router.delete("/workflows/{workflow_id}")
async def delete_workflow(workflow_id: str, user: dict = Depends(get_current_user)):
    """Delete a workflow."""
    log.set(
        user={"id": user["user_id"]},
        workflow=WorkflowContext(operation="delete", id=workflow_id),
    )

    try:
        success = await WorkflowService.delete_workflow(workflow_id, user["user_id"])
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Workflow {workflow_id} not found",
            )

        log.set(outcome="success")
        return {"message": "Workflow deleted successfully"}

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Error deleting workflow {workflow_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete workflow",
        )
