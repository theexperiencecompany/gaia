"""Integration config, status, and connection routes."""

from fastapi import APIRouter, Depends, HTTPException

from app.api.v1.dependencies.oauth_dependencies import get_current_user, get_user_id
from app.config.oauth_config import OAUTH_INTEGRATIONS
from app.schemas.integrations.requests import ConnectIntegrationRequest
from app.schemas.integrations.responses import (
    ConnectIntegrationResponse,
    IntegrationsConfigResponse,
    IntegrationsStatusResponse,
    IntegrationStatusItem,
    IntegrationSuccessResponse,
)
from app.services.integrations.integration_connection_service import (
    build_integrations_config,
    disconnect_integration,
    resolve_and_connect_integration,
)
from app.services.oauth.oauth_service import get_all_integrations_status
from shared.py.wide_events import log

router = APIRouter()


@router.get("/config", response_model=IntegrationsConfigResponse)
async def get_integrations_config() -> IntegrationsConfigResponse:
    log.set(operation="get_integrations_config")
    result = build_integrations_config()
    log.set(outcome="success")
    return result


@router.get("/status", response_model=IntegrationsStatusResponse)
async def get_integrations_status(
    user_id: str = Depends(get_user_id),
) -> IntegrationsStatusResponse:
    try:
        log.set(operation="get_integrations_status", user={"id": user_id})
        status_map = await get_all_integrations_status(user_id)
        log.set(result_count=len(status_map))
        log.set(outcome="success")
        return IntegrationsStatusResponse(
            integrations=[
                IntegrationStatusItem(integration_id=iid, connected=connected)
                for iid, connected in status_map.items()
            ]
        )
    except Exception as e:
        log.error(f"Error checking integration status: {e}")
        return IntegrationsStatusResponse(
            integrations=[
                IntegrationStatusItem(integration_id=i.id, connected=False)
                for i in OAUTH_INTEGRATIONS
                if i.managed_by != "internal"
            ]
        )


@router.delete("/{integration_id}", response_model=IntegrationSuccessResponse)
async def disconnect_integration_endpoint(
    integration_id: str,
    user_id: str = Depends(get_user_id),
) -> IntegrationSuccessResponse:
    try:
        log.set(
            operation="disconnect_integration",
            integration_id=integration_id,
            user={"id": user_id},
            integration={"id": integration_id},
        )
        result = await disconnect_integration(user_id, integration_id)
        log.set(outcome="success")
        return result
    except ValueError as e:
        error_message = str(e)
        # Only return 404 if the integration itself doesn't exist
        if "not found" in error_message.lower() and "account" not in error_message.lower():
            raise HTTPException(status_code=404, detail=error_message)
        # For "no active connected account" or other cases, return 400
        raise HTTPException(status_code=400, detail=error_message)
    except Exception as e:
        log.error(f"Error disconnecting {integration_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to disconnect integration")


@router.post("/connect/{integration_id}", response_model=ConnectIntegrationResponse)
async def connect_integration_endpoint(
    integration_id: str,
    request: ConnectIntegrationRequest,
    user: dict = Depends(get_current_user),
) -> ConnectIntegrationResponse:
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="User ID not found")

    log.set(
        operation="connect_integration",
        integration_id=integration_id,
        user={"id": user_id},
        integration={"id": integration_id},
    )
    result = await resolve_and_connect_integration(
        user_id=str(user_id),
        integration_id=integration_id,
        user_email=user.get("email", ""),
        redirect_path=request.redirect_path,
        bearer_token=request.bearer_token,
    )
    if result is None:
        raise HTTPException(status_code=404, detail=f"Integration {integration_id} not found")
    log.set(outcome=result.status)
    return result
