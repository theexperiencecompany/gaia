"""User workspace integration routes."""

from app.api.v1.dependencies.oauth_dependencies import get_user_id
from app.config.loggers import auth_logger as logger
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
        return await get_user_integrations(user_id)
    except Exception as e:
        logger.error(f"Error fetching user integrations: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch user integrations")


@router.post("", response_model=AddUserIntegrationResponse)
async def add_integration_to_workspace(
    request: AddUserIntegrationRequest,
    user_id: str = Depends(get_user_id),
) -> AddUserIntegrationResponse:
    try:
        user_integration = await add_user_integration_service(
            user_id, request.integration_id
        )
        return AddUserIntegrationResponse(
            message="Integration added to workspace",
            integration_id=user_integration.integration_id,
            connection_status=user_integration.status,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error adding integration: {e}")
        raise HTTPException(status_code=500, detail="Failed to add integration")


@router.delete("/{integration_id}", response_model=IntegrationSuccessResponse)
async def remove_integration_from_workspace(
    integration_id: str,
    user_id: str = Depends(get_user_id),
) -> IntegrationSuccessResponse:
    try:
        removed = await remove_user_integration(user_id, integration_id)
        if not removed:
            raise HTTPException(
                status_code=404, detail="Integration not found in workspace"
            )
        return IntegrationSuccessResponse(
            message="Integration removed from workspace",
            integration_id=integration_id,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error removing integration: {e}")
        raise HTTPException(status_code=500, detail="Failed to remove integration")
