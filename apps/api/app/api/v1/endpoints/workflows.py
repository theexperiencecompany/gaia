"""
Clean workflow API router for GAIA workflow system.
Provides CRUD operations, execution, and status endpoints.
"""

from typing import cast

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pymongo.errors import DuplicateKeyError

from app.api.v1.dependencies.oauth_dependencies import (
    get_current_user,
    get_user_id,
    get_user_timezone_from_preferences,
)
from app.api.v1.middleware.rate_limiter import limiter
from app.constants.log_tags import LogTag
from app.db.repositories.workflows import workflow_repository
from app.decorators import tiered_rate_limit
from app.models.user_models import AuthenticatedUser
from app.models.workflow_execution_models import WorkflowExecutionsResponse
from app.models.workflow_models import (
    CreateWorkflowFromTodoRequest,
    CreateWorkflowRequest,
    GenerateWorkflowPromptRequest,
    GenerateWorkflowPromptResponse,
    PublicWorkflowsResponse,
    PublishWorkflowResponse,
    RegenerateStepsRequest,
    ResetWorkflowResponse,
    TriggerConfig,
    TriggerType,
    UpdateWorkflowRequest,
    WorkflowExecutionRequest,
    WorkflowExecutionResponse,
    WorkflowListResponse,
    WorkflowMessageResponse,
    WorkflowResponse,
    WorkflowStatusResponse,
)
from app.services.analytics_service import AnalyticsEvents, capture_context_event
from app.services.oauth.oauth_service import get_all_integrations_status
from app.services.system_workflows.provisioner import reset_system_workflow_to_default
from app.services.workflow import WorkflowService
from app.services.workflow.execution_service import (
    get_workflow_executions as get_executions,
)
from app.services.workflow.generation_service import WorkflowGenerationService
from app.services.workflow.service import (
    ensure_public_workflow_slug,
    generate_unique_workflow_slug,
)
from app.utils.creator import format_creator
from app.utils.exceptions import TriggerRegistrationError
from shared.py.wide_events import WorkflowContext, log

router = APIRouter()


@router.post("/workflows", response_model=WorkflowResponse)
@tiered_rate_limit("workflow_operations")
async def create_workflow(
    request: CreateWorkflowRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    user_timezone: str = Depends(get_user_timezone_from_preferences),
) -> WorkflowResponse:
    """Create a new workflow with automatic timezone detection."""
    log.set(
        user={"id": user["user_id"]},
        workflow=WorkflowContext(
            operation="create",
            title=request.title,
            trigger_type=str(request.trigger_config.type) if request.trigger_config else None,
        ),
    )

    try:
        # Strip system fields — these are set by the provisioner only
        request.is_system_workflow = False
        request.source_integration = None
        request.system_workflow_key = None
        # Default integration_ids to the user's connected integrations so
        # step generation is grounded in tools the user can actually use.
        if request.integration_ids is None:
            status_map = await get_all_integrations_status(user["user_id"])
            request.integration_ids = [
                integration_id
                for integration_id, is_connected in status_map.items()
                if is_connected
            ] or None
        # Pass user timezone to the service for automatic population
        workflow = await WorkflowService.create_workflow(
            request, user["user_id"], user_timezone=user_timezone
        )
        # The trigger type lives on the REQUEST (the pre-create log above reads
        # request.trigger_config.type) — the created Workflow model does not
        # carry a trigger_type attribute, so reading it off the workflow would
        # always yield None. Both fields are required, so no guard needed.
        trigger_type = request.trigger_config.type.value
        log.set(
            workflow=WorkflowContext(
                id=str(workflow.id),
                title=workflow.title,
                steps_count=len(workflow.steps) if workflow.steps else None,
                trigger_type=trigger_type,
            ),
            outcome="success",
        )
        capture_context_event(
            AnalyticsEvents.WORKFLOW_CREATED,
            {
                "trigger_type": trigger_type,
                "steps_count": len(workflow.steps) if workflow.steps else 0,
                "generated_immediately": request.generate_immediately,
            },
        )
        return WorkflowResponse(workflow=workflow, message="Workflow created successfully")

    except TriggerRegistrationError as e:
        # Specific error for trigger registration failures
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except Exception as e:
        log.error(
            f"{LogTag.WORKFLOW} Error creating workflow",
            user_id=user["user_id"],
            error_type=type(e).__name__,
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create workflow",
        ) from e


@router.get("/workflows", response_model=WorkflowListResponse)
@limiter.limit("100/minute")
@limiter.limit("1000/hour")
async def list_workflows(
    request: Request, user: AuthenticatedUser = Depends(get_current_user)
) -> WorkflowListResponse:
    """List all workflows for the current user."""
    log.set(
        user={"id": user["user_id"]},
        workflow=WorkflowContext(operation="list"),
    )

    try:
        workflows, _total = await WorkflowService.list_workflows(user["user_id"])
        log.set(
            workflow=WorkflowContext(result_count=len(workflows)),
            outcome="success",
        )
        return WorkflowListResponse(workflows=workflows)

    except Exception as e:
        log.error(
            f"{LogTag.WORKFLOW} Error listing workflows",
            user_id=user["user_id"],
            error_type=type(e).__name__,
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list workflows",
        ) from e


@router.post("/workflows/{workflow_id}/execute", response_model=WorkflowExecutionResponse)
@tiered_rate_limit("workflow_operations")
async def execute_workflow(
    workflow_id: str,
    request: WorkflowExecutionRequest,
    user: AuthenticatedUser = Depends(get_current_user),
) -> WorkflowExecutionResponse:
    """Execute a workflow (run now)."""
    log.set(
        user={"id": user["user_id"]},
        workflow=WorkflowContext(operation="execute", id=workflow_id),
    )

    try:
        result = await WorkflowService.execute_workflow(workflow_id, request, user["user_id"])
        # execute_workflow is typed to return WorkflowExecutionResponse, whose
        # execution_id is required — the hasattr guard was dead defensive code.
        log.set(
            workflow=WorkflowContext(
                execution_id=str(result.execution_id),
            ),
            outcome="success",
        )
        capture_context_event(AnalyticsEvents.WORKFLOW_EXECUTED)
        return result

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except Exception as e:
        log.error(
            f"{LogTag.WORKFLOW} Error executing workflow",
            workflow_id=workflow_id,
            user_id=user["user_id"],
            error_type=type(e).__name__,
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to execute workflow",
        ) from e


@router.get("/workflows/{workflow_id}/executions", response_model=WorkflowExecutionsResponse)
@limiter.limit("100/minute")
async def get_workflow_executions(
    request: Request,
    workflow_id: str,
    limit: int = 10,
    offset: int = 0,
    user: AuthenticatedUser = Depends(get_current_user),
) -> WorkflowExecutionsResponse:
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
        log.error(
            f"{LogTag.WORKFLOW} Error getting executions for workflow",
            workflow_id=workflow_id,
            user_id=user["user_id"],
            error_type=type(e).__name__,
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get workflow executions",
        ) from e


@router.get("/workflows/{workflow_id}/status", response_model=WorkflowStatusResponse)
async def get_workflow_status(
    workflow_id: str, user: AuthenticatedUser = Depends(get_current_user)
) -> WorkflowStatusResponse:
    """Get the current status of a workflow (for polling)."""
    log.set(
        user={"id": user["user_id"]},
        workflow=WorkflowContext(operation="status", id=workflow_id),
    )

    try:
        status_response = await WorkflowService.get_workflow_status(workflow_id, user["user_id"])
        log.set(
            workflow=WorkflowContext(
                execution_id=str(status_response.execution_id)
                if hasattr(status_response, "execution_id") and status_response.execution_id
                else None,
            ),
            outcome="success",
        )
        return status_response

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except Exception as e:
        log.error(
            f"{LogTag.WORKFLOW} Error getting workflow status",
            workflow_id=workflow_id,
            user_id=user["user_id"],
            error_type=type(e).__name__,
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get workflow status",
        ) from e


@router.post("/workflows/{workflow_id}/activate", response_model=WorkflowResponse)
async def activate_workflow(
    workflow_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    user_timezone: str = Depends(get_user_timezone_from_preferences),
) -> WorkflowResponse:
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
        capture_context_event(AnalyticsEvents.WORKFLOW_ACTIVATED)
        return WorkflowResponse(workflow=workflow, message="Workflow activated successfully")

    except TriggerRegistrationError as e:
        # Specific error for trigger registration failures
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e
    except ValueError as e:
        # Missing step integrations or other validation failures
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e
    except HTTPException:
        raise
    except Exception as e:
        log.error(
            f"{LogTag.WORKFLOW} Error activating workflow",
            workflow_id=workflow_id,
            user_id=user["user_id"],
            error_type=type(e).__name__,
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to activate workflow",
        ) from e


@router.post("/workflows/{workflow_id}/deactivate", response_model=WorkflowResponse)
async def deactivate_workflow(
    workflow_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    user_timezone: str = Depends(get_user_timezone_from_preferences),
) -> WorkflowResponse:
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
        return WorkflowResponse(workflow=workflow, message="Workflow deactivated successfully")

    except HTTPException:
        raise
    except Exception as e:
        log.error(
            f"{LogTag.WORKFLOW} Error deactivating workflow",
            workflow_id=workflow_id,
            user_id=user["user_id"],
            error_type=type(e).__name__,
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to deactivate workflow",
        ) from e


@router.post("/workflows/{workflow_id}/regenerate-steps", response_model=WorkflowResponse)
async def regenerate_workflow_steps(
    workflow_id: str,
    request: RegenerateStepsRequest,
    user: AuthenticatedUser = Depends(get_current_user),
) -> WorkflowResponse:
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
            integration_ids=request.integration_ids,
        )
        if not workflow:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Workflow not found",
            )

        log.set(outcome="success")
        return WorkflowResponse(workflow=workflow, message="Workflow regeneration started")

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except Exception as e:
        log.error(
            f"{LogTag.WORKFLOW} Error regenerating workflow steps",
            workflow_id=workflow_id,
            user_id=user["user_id"],
            error_type=type(e).__name__,
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to regenerate workflow steps",
        ) from e


@router.post("/workflows/from-todo", response_model=WorkflowResponse)
@tiered_rate_limit("workflow_operations")
async def create_workflow_from_todo(
    request: CreateWorkflowFromTodoRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    user_timezone: str = Depends(get_user_timezone_from_preferences),
) -> WorkflowResponse:
    """Create a workflow from a todo item with automatic timezone detection."""
    log.set(
        user={"id": user["user_id"]},
        workflow=WorkflowContext(operation="create"),
    )

    try:
        todo_title = request.todo_title
        todo_description = request.todo_description

        if not request.todo_id or not todo_title:
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
        log.error(
            f"{LogTag.WORKFLOW} Error creating workflow from todo",
            user_id=user["user_id"],
            error_type=type(e).__name__,
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create workflow from todo",
        ) from e


@router.post("/workflows/{workflow_id}/publish", response_model=PublishWorkflowResponse)
async def publish_workflow(
    workflow_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
) -> PublishWorkflowResponse:
    """Publish a workflow to the community marketplace."""
    log.set(
        user={"id": user["user_id"]},
        workflow=WorkflowContext(operation="publish", id=workflow_id),
    )

    try:
        workflow = await workflow_repository.get_for_user(workflow_id, user["user_id"])

        if not workflow:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Workflow not found or access denied",
            )

        existing_slug = workflow.slug
        slug = existing_slug

        # Retry on DuplicateKeyError so a concurrent publish racing on the
        # same suffix can't corrupt the unique index. Only a freshly generated
        # slug is retried; an existing slug that collides re-raises.
        for _ in range(5):
            if not existing_slug:
                slug = await generate_unique_workflow_slug(workflow.title, exclude_id=workflow_id)
            try:
                await workflow_repository.publish(
                    workflow_id, created_by=user["user_id"], slug=slug or ""
                )
                break
            except DuplicateKeyError:
                if existing_slug:
                    raise
                continue
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Could not allocate a unique slug, please retry",
            )

        log.set(outcome="success")
        log.info(
            f"{LogTag.WORKFLOW} Published workflow",
            workflow_id=workflow_id,
            user_id=user["user_id"],
        )
        capture_context_event(AnalyticsEvents.WORKFLOW_PUBLISHED)

        return PublishWorkflowResponse(
            message="Workflow published successfully",
            workflow_id=workflow_id,
            slug=slug,
        )

    except HTTPException:
        raise
    except Exception as e:
        log.error(
            f"{LogTag.WORKFLOW} Error publishing workflow",
            workflow_id=workflow_id,
            user_id=user["user_id"],
            error_type=type(e).__name__,
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to publish workflow",
        ) from e


@router.post("/workflows/{workflow_id}/unpublish")
async def unpublish_workflow(
    workflow_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
) -> WorkflowMessageResponse:
    """Remove a workflow from the community marketplace."""
    log.set(
        user={"id": user["user_id"]},
        workflow=WorkflowContext(id=workflow_id),
    )

    try:
        # Check if workflow exists and belongs to user
        workflow = await workflow_repository.get_for_user(workflow_id, user["user_id"])

        if not workflow:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Workflow not found or access denied",
            )

        await workflow_repository.unpublish(workflow_id)

        log.set(outcome="success")
        log.info(
            f"{LogTag.WORKFLOW} Unpublished workflow",
            workflow_id=workflow_id,
            user_id=user["user_id"],
        )

        return WorkflowMessageResponse(message="Workflow unpublished successfully")

    except HTTPException:
        raise
    except Exception as e:
        log.error(
            f"{LogTag.WORKFLOW} Error unpublishing workflow",
            workflow_id=workflow_id,
            user_id=user["user_id"],
            error_type=type(e).__name__,
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to unpublish workflow",
        ) from e


@router.get("/workflows/explore", response_model=PublicWorkflowsResponse)
@limiter.limit("500/minute")
@limiter.limit("5000/hour")
async def get_explore_workflows(
    request: Request,
    limit: int = 25,
    offset: int = 0,
) -> PublicWorkflowsResponse:
    """Get explore/featured workflows for the discover section."""
    log.set(workflow=WorkflowContext(operation="explore"))
    try:
        result = await WorkflowService.get_explore_workflows(limit=limit, offset=offset)
        log.set_ns("workflow", result_count=len(result.workflows))
        # Cacheable erases the wrapped function's return type; get_explore_workflows
        # is declared -> PublicWorkflowsResponse, so this is correct by construction.
        return cast(PublicWorkflowsResponse, result)
    except Exception as e:
        log.error(
            f"{LogTag.WORKFLOW} Error fetching explore workflows",
            error_type=type(e).__name__,
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch explore workflows",
        ) from e


@router.get("/workflows/community", response_model=PublicWorkflowsResponse)
@limiter.limit("500/minute")
@limiter.limit("5000/hour")
async def get_public_workflows(
    request: Request,
    limit: int = 20,
    offset: int = 0,
) -> PublicWorkflowsResponse:
    """Get public workflows from the community marketplace."""
    log.set(workflow=WorkflowContext(operation="list_public"))
    try:
        result = await WorkflowService.get_community_workflows(
            limit=limit, offset=offset, user_id=None
        )
        log.set_ns("workflow", result_count=len(result.workflows))
        # Cacheable erases the wrapped function's return type; get_community_workflows
        # is declared -> PublicWorkflowsResponse, so this is correct by construction.
        return cast(PublicWorkflowsResponse, result)
    except Exception as e:
        log.error(
            f"{LogTag.WORKFLOW} Error fetching public workflows",
            error_type=type(e).__name__,
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch public workflows",
        ) from e


@router.get("/workflows/public/{workflow_ref}", response_model=WorkflowResponse)
@limiter.limit("500/minute")
@limiter.limit("5000/hour")
async def get_public_workflow(request: Request, workflow_ref: str) -> WorkflowResponse:
    """Get a public workflow by ID (wf_xxx) or slug."""
    lookup_mode = "id" if workflow_ref.startswith("wf_") else "slug"
    log.set(
        workflow=WorkflowContext(operation="get_public"),
        public_workflow={"ref": workflow_ref, "lookup_mode": lookup_mode},
    )
    try:
        workflow = await workflow_repository.get_public_with_creator(
            workflow_ref, by_slug=lookup_mode == "slug"
        )

        if not workflow:
            log.info(
                f"{LogTag.WORKFLOW} get_public_workflow: no public workflow found",
                workflow_ref=workflow_ref,
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Public workflow not found",
            )

        creator = format_creator(workflow)
        await ensure_public_workflow_slug(workflow)
        # The row IS-A Workflow; creator_info is excluded from serialization, so
        # handing it straight back emits the plain Workflow shape plus `creator`.
        workflow.creator = creator

        log.set(
            public_workflow={
                "id": workflow.id,
                "slug": workflow.slug,
                "creator_id": workflow.created_by,
                "creator_name": creator.get("name") if isinstance(creator, dict) else None,
                "step_count": len(workflow.steps) if workflow.steps else 0,
            }
        )
        return WorkflowResponse(workflow=workflow, message="Workflow retrieved successfully")
    except HTTPException:
        raise
    except Exception as e:
        log.error(
            f"{LogTag.WORKFLOW} Error getting public workflow",
            workflow_ref=workflow_ref,
            error_type=type(e).__name__,
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get workflow",
        ) from e


@router.post("/workflows/generate-prompt", response_model=GenerateWorkflowPromptResponse)
async def generate_workflow_prompt_endpoint(
    request: GenerateWorkflowPromptRequest,
    user: AuthenticatedUser = Depends(get_current_user),
) -> GenerateWorkflowPromptResponse:
    """Generate or improve workflow instructions using AI."""
    log.set(
        user={"id": user["user_id"]},
        workflow=WorkflowContext(operation="generate_prompt"),
    )

    try:
        result = await WorkflowGenerationService.generate_workflow_prompt(
            title=request.title,
            description=request.description,
            trigger_config=request.trigger_config,
            existing_prompt=request.existing_prompt,
            integration_ids=request.integration_ids,
            user_id=user["user_id"],
        )
        log.set(outcome="success")
        return GenerateWorkflowPromptResponse(**result)
    except Exception as e:
        log.error(
            f"{LogTag.WORKFLOW} Error generating workflow prompt",
            user_id=user["user_id"],
            error_type=type(e).__name__,
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate workflow prompt",
        ) from e


@router.get("/workflows/{workflow_id}", response_model=WorkflowResponse)
@limiter.limit("500/minute")
@limiter.limit("5000/hour")
async def get_workflow(
    request: Request, workflow_id: str, user: AuthenticatedUser = Depends(get_current_user)
) -> WorkflowResponse:
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
        return WorkflowResponse(workflow=workflow, message="Workflow retrieved successfully")

    except HTTPException:
        raise
    except Exception as e:
        log.error(
            f"{LogTag.WORKFLOW} Error getting workflow",
            workflow_id=workflow_id,
            user_id=user["user_id"],
            error_type=type(e).__name__,
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get workflow",
        ) from e


@router.put("/workflows/{workflow_id}")
async def update_workflow(
    workflow_id: str,
    request: UpdateWorkflowRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    user_timezone: str = Depends(get_user_timezone_from_preferences),
) -> WorkflowResponse:
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
        return WorkflowResponse(workflow=workflow, message="Workflow updated successfully")

    except TriggerRegistrationError as e:
        # Specific error for trigger registration failures
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e
    except HTTPException:
        raise
    except Exception as e:
        log.error(
            f"{LogTag.WORKFLOW} Error updating workflow",
            workflow_id=workflow_id,
            user_id=user["user_id"],
            error_type=type(e).__name__,
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update workflow",
        ) from e


@router.post("/workflows/{workflow_id}/reset-to-default")
async def reset_workflow_to_default(
    workflow_id: str, user_id: str = Depends(get_user_id)
) -> ResetWorkflowResponse:
    """Reset a GAIA system workflow to its original definition.

    Restores the workflow's title, description, steps, and trigger config to
    the defaults that were set when it was auto-provisioned. Preserves the
    workflow ID, activated state, and execution statistics.

    Only works on workflows where is_system_workflow=True.
    """
    log.set(
        user={"id": user_id},
        workflow=WorkflowContext(id=workflow_id),
    )

    try:
        success = await reset_system_workflow_to_default(
            workflow_id=workflow_id,
            user_id=user_id,
        )
        if not success:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Workflow not found or is not a resettable system workflow.",
            )
        log.set(outcome="success")
        return ResetWorkflowResponse(success=True, message="Workflow reset to default.")

    except HTTPException:
        raise
    except Exception as e:
        log.error(
            f"{LogTag.WORKFLOW} Error resetting workflow",
            workflow_id=workflow_id,
            user_id=user_id,
            error_type=type(e).__name__,
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to reset workflow",
        ) from e


@router.delete("/workflows/{workflow_id}")
async def delete_workflow(
    workflow_id: str, user: AuthenticatedUser = Depends(get_current_user)
) -> WorkflowMessageResponse:
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
        return WorkflowMessageResponse(message="Workflow deleted successfully")

    except HTTPException:
        raise
    except Exception as e:
        log.error(
            f"{LogTag.WORKFLOW} Error deleting workflow",
            workflow_id=workflow_id,
            user_id=user["user_id"],
            error_type=type(e).__name__,
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete workflow",
        ) from e
