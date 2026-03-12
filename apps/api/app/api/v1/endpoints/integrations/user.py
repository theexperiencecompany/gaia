"""User workspace integration routes."""

from app.api.v1.dependencies.oauth_dependencies import get_user_id
from shared.py.wide_events import log
from app.models.integration_models import (
    UserIntegrationsListResponse as UserIntegrationsListResponseModel,
)
from app.schemas.integrations.requests import AddUserIntegrationRequest
from app.schemas.integrations.responses import (
    AddUserIntegrationResponse,
    IntegrationSuccessResponse,
    UserIntegrationsListResponse,
)
from app.services.integrations.user_integrations import (
    get_user_integrations,
    remove_user_integration,
)
from app.services.integrations.user_integrations import (
    add_user_integration as add_user_integration_service,
)
from fastapi import APIRouter, Depends, HTTPException

router = APIRouter()


@router.get("", response_model=UserIntegrationsListResponse)
async def list_user_integrations(
    user_id: str = Depends(get_user_id),
) -> UserIntegrationsListResponseModel:
    try:
        log.set(operation="list_user_integrations", user={"id": user_id})
        result = await get_user_integrations(user_id)
        log.set(
            result_count=len(result.integrations)
            if hasattr(result, "integrations")
            else 0
        )
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
    try:
        log.set(
            operation="add_integration_to_workspace",
            integration_id=request.integration_id,
            user={"id": user_id},
        )
        user_integration = await add_user_integration_service(
            user_id, request.integration_id
        )
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
    try:
        log.set(
            operation="remove_integration_from_workspace",
            integration_id=integration_id,
            user={"id": user_id},
            integration={"id": integration_id},
        )
        removed = await remove_user_integration(user_id, integration_id)
        if not removed:
            raise HTTPException(
                status_code=404, detail="Integration not found in workspace"
            )
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
