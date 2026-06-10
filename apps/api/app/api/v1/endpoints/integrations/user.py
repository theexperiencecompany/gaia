"""User workspace integration routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.api.v1.dependencies.oauth_dependencies import get_user_id
from app.models.integration_instructions_models import InstructionsEditor
from app.models.integration_models import (
    UserIntegrationsListResponse as UserIntegrationsListResponseModel,
)
from app.schemas.integrations.requests import (
    AddUserIntegrationRequest,
    UpdateIntegrationInstructionsRequest,
)
from app.schemas.integrations.responses import (
    AddUserIntegrationResponse,
    IntegrationInstructionsResponse,
    IntegrationSuccessResponse,
    UserIntegrationsListResponse,
)
from app.services.integration_instructions_service import (
    get_instructions_record,
    upsert_instructions,
)
from app.services.integrations.user_integrations import (
    add_user_integration as add_user_integration_service,
    check_user_has_integration,
    get_user_integrations,
    remove_user_integration,
)
from app.services.storage.juicefs import ensure_safe_path_id
from shared.py.wide_events import log

router = APIRouter()


@router.get("", response_model=UserIntegrationsListResponse)
async def list_user_integrations(
    user_id: str = Depends(get_user_id),
) -> UserIntegrationsListResponseModel:
    """List the integrations the current user has added to their workspace."""
    try:
        log.set(operation="list_user_integrations", user={"id": user_id})
        result = await get_user_integrations(user_id)
        log.set(result_count=len(result.integrations) if hasattr(result, "integrations") else 0)
        log.set(outcome="success")
        return result
    except Exception as e:
        log.error(f"Error fetching user integrations: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch user integrations")


@router.post("", response_model=AddUserIntegrationResponse)
async def add_integration_to_workspace(
    request: AddUserIntegrationRequest,
    user_id: str = Depends(get_user_id),
) -> AddUserIntegrationResponse:
    """Add an integration to the current user's workspace."""
    try:
        log.set(
            operation="add_integration_to_workspace",
            integration_id=request.integration_id,
            user={"id": user_id},
        )
        user_integration = await add_user_integration_service(user_id, request.integration_id)
        log.set(outcome="success")
        return AddUserIntegrationResponse(
            message="Integration added to workspace",
            integration_id=user_integration.integration_id,
            connection_status=user_integration.status,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        log.error(f"Error adding integration: {e}")
        raise HTTPException(status_code=500, detail="Failed to add integration")


@router.delete("/{integration_id}", response_model=IntegrationSuccessResponse)
async def remove_integration_from_workspace(
    integration_id: str,
    user_id: str = Depends(get_user_id),
) -> IntegrationSuccessResponse:
    """Remove an integration from the current user's workspace."""
    try:
        log.set(
            operation="remove_integration_from_workspace",
            integration_id=integration_id,
            user={"id": user_id},
            integration={"id": integration_id},
        )
        removed = await remove_user_integration(user_id, integration_id)
        if not removed:
            raise HTTPException(status_code=404, detail="Integration not found in workspace")
        log.set(outcome="success")
        return IntegrationSuccessResponse(
            message="Integration removed from workspace",
            integration_id=integration_id,
        )
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Error removing integration: {e}")
        raise HTTPException(status_code=500, detail="Failed to remove integration")


@router.get(
    "/{integration_id}/instructions",
    responses={500: {"description": "Failed to fetch integration instructions"}},
)
async def get_integration_instructions(
    integration_id: str,
    user_id: Annotated[str, Depends(get_user_id)],
) -> IntegrationInstructionsResponse:
    """Return the current user's custom instructions for an integration.

    Responds with empty content (not 404) when none are set, so the editor can
    always render against a stable shape.
    """
    try:
        log.set(
            operation="get_integration_instructions",
            user={"id": user_id},
            integration={"id": integration_id},
        )
        record = await get_instructions_record(user_id, integration_id)
        log.set(outcome="success", has_instructions=record is not None)
        if not record:
            return IntegrationInstructionsResponse(
                integration_id=integration_id,
                content="",
                updated_by=InstructionsEditor.USER,
                updated_at=None,
            )
        return IntegrationInstructionsResponse(
            integration_id=record.integration_id,
            content=record.content,
            updated_by=record.updated_by,
            updated_at=record.updated_at,
        )
    except Exception as e:
        log.error(f"Error fetching integration instructions: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch integration instructions")


@router.put(
    "/{integration_id}/instructions",
    responses={
        400: {"description": "Invalid integration_id"},
        404: {"description": "Integration not found in workspace"},
        500: {"description": "Failed to update integration instructions"},
    },
)
async def update_integration_instructions(
    integration_id: str,
    request: UpdateIntegrationInstructionsRequest,
    user_id: Annotated[str, Depends(get_user_id)],
) -> IntegrationInstructionsResponse:
    """Create or replace the current user's custom instructions for an integration."""
    try:
        log.set(
            operation="update_integration_instructions",
            user={"id": user_id},
            integration={"id": integration_id},
        )
        ensure_safe_path_id(integration_id, label="integration_id")
        if not await check_user_has_integration(user_id, integration_id):
            raise HTTPException(status_code=404, detail="Integration not found in workspace")
        record = await upsert_instructions(
            user_id=user_id,
            integration_id=integration_id,
            content=request.content,
            updated_by=InstructionsEditor.USER,
        )
        log.set(outcome="success")
        return IntegrationInstructionsResponse(
            integration_id=record.integration_id,
            content=record.content,
            updated_by=record.updated_by,
            updated_at=record.updated_at,
        )
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        log.error(f"Error updating integration instructions: {e}")
        raise HTTPException(status_code=500, detail="Failed to update integration instructions")
