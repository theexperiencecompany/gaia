"""Custom MCP integration routes."""

from app.api.v1.dependencies.oauth_dependencies import get_user_id
from shared.py.wide_events import log
from app.models.integration_models import (
    CreateCustomIntegrationRequest as RequestModel,
)
from app.models.integration_models import (
    UpdateCustomIntegrationRequest as UpdateCustomIntegrationRequestModel,
)
from app.schemas.integrations.requests import (
    CreateCustomIntegrationRequest,
    UpdateCustomIntegrationRequest,
)
from app.schemas.integrations.responses import (
    CreateCustomIntegrationResponse,
    CustomIntegrationConnectionResult,
    IntegrationSuccessResponse,
    PublishIntegrationResponse,
    UnpublishIntegrationResponse,
)
from app.services.integrations.custom_crud import (
    create_and_connect_custom_integration,
    delete_custom_integration,
    update_custom_integration,
)
from app.services.integrations.publish_service import (
    PublishError,
    publish_custom_integration,
    unpublish_custom_integration,
)
from app.services.mcp.mcp_client import get_mcp_client
from fastapi import APIRouter, Depends, HTTPException

router = APIRouter()


@router.post("", response_model=CreateCustomIntegrationResponse)
async def create_custom_mcp_integration(
    request: CreateCustomIntegrationRequest,
    user_id: str = Depends(get_user_id),
) -> CreateCustomIntegrationResponse:
    try:
        log.set(operation="create_custom_integration", integration_name=request.name, user={"id": user_id})
        mcp_client = await get_mcp_client(user_id=user_id)
        integration, conn_result = await create_and_connect_custom_integration(
            user_id,
            RequestModel(
                name=request.name,
                description=request.description,
                category=request.category,
                server_url=request.server_url,
                requires_auth=request.requires_auth,
                auth_type=request.auth_type,
                is_public=request.is_public,
                bearer_token=request.bearer_token,
            ),
            mcp_client,
        )

        log.set(integration_id=integration.integration_id)
        log.set(outcome="success")
        return CreateCustomIntegrationResponse(
            message="Custom integration created",
            integration_id=integration.integration_id,
            name=integration.name,
            connection=CustomIntegrationConnectionResult(
                status=conn_result["status"],
                tools_count=conn_result.get("tools_count"),
                oauth_url=conn_result.get("oauth_url"),
                error=conn_result.get("error"),
            ),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        log.error(f"Error creating custom integration: {e}")
        raise HTTPException(status_code=500, detail="Failed to create integration")


@router.patch("/{integration_id}", response_model=IntegrationSuccessResponse)
async def update_custom_mcp_integration(
    integration_id: str,
    request: UpdateCustomIntegrationRequest,
    user_id: str = Depends(get_user_id),
) -> IntegrationSuccessResponse:
    try:
        log.set(operation="update_custom_integration", integration_id=integration_id, user={"id": user_id}, integration={"id": integration_id})
        updated = await update_custom_integration(
            user_id,
            integration_id,
            UpdateCustomIntegrationRequestModel(
                name=request.name,
                description=request.description,
                server_url=request.server_url,
                requires_auth=request.requires_auth,
                auth_type=request.auth_type,
                is_public=request.is_public,
            ),
        )
        if not updated:
            raise HTTPException(
                status_code=404, detail="Integration not found or you are not the owner"
            )
        log.set(integration_name=updated.name)
        log.set(outcome="success")
        return IntegrationSuccessResponse(
            message="Integration updated",
            integration_id=updated.integration_id,
        )
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Error updating integration {integration_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to update integration")


@router.delete("/{integration_id}", response_model=IntegrationSuccessResponse)
async def delete_custom_mcp_integration(
    integration_id: str,
    user_id: str = Depends(get_user_id),
) -> IntegrationSuccessResponse:
    try:
        log.set(operation="delete_custom_integration", integration_id=integration_id, user={"id": user_id}, integration={"id": integration_id})
        deleted = await delete_custom_integration(user_id, integration_id)
        if not deleted:
            raise HTTPException(
                status_code=404, detail="Integration not found or you are not the owner"
            )
        log.set(outcome="success")
        return IntegrationSuccessResponse(
            message="Integration deleted",
            integration_id=integration_id,
        )
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Error deleting integration {integration_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete integration")


@router.post("/{integration_id}/publish", response_model=PublishIntegrationResponse)
async def publish_integration(
    integration_id: str,
    user_id: str = Depends(get_user_id),
) -> PublishIntegrationResponse:
    try:
        log.set(operation="publish_integration", integration_id=integration_id, user={"id": user_id}, integration={"id": integration_id})
        result = await publish_custom_integration(integration_id, user_id)
        log.set(outcome="success")
        return PublishIntegrationResponse(
            message="Integration published successfully",
            integration_id=result["integration_id"],
            public_url=result["public_url"],
        )
    except PublishError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    except Exception as e:
        log.error(f"Error publishing integration {integration_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to publish integration")


@router.post("/{integration_id}/unpublish", response_model=UnpublishIntegrationResponse)
async def unpublish_integration(
    integration_id: str,
    user_id: str = Depends(get_user_id),
) -> UnpublishIntegrationResponse:
    try:
        log.set(operation="unpublish_integration", integration_id=integration_id, user={"id": user_id}, integration={"id": integration_id})
        result = await unpublish_custom_integration(integration_id, user_id)
        log.set(outcome="success")
        return UnpublishIntegrationResponse(
            message="Integration unpublished successfully",
            integration_id=result["integration_id"],
        )
    except PublishError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    except Exception as e:
        log.error(f"Error unpublishing integration {integration_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to unpublish integration")
