"""User workspace integration routes."""

from fastapi import APIRouter, Depends, HTTPException

from app.api.v1.dependencies.oauth_dependencies import get_user_id
from app.constants.log_tags import LogTag
from app.db.repositories.user_integrations import user_integration_repository
from app.schemas.integrations.requests import AddUserIntegrationRequest
from app.schemas.integrations.responses import (
    AddUserIntegrationResponse,
    IntegrationSuccessResponse,
)
from app.services.analytics_service import capture
from app.services.integrations.integration_connection_service import remove_from_workspace
from app.services.integrations.user_integrations import (
    add_user_integration as add_user_integration_service,
)
from shared.py.analytics import UserId
from shared.py.analytics.catalog.integrations import (
    IntegrationConnected,
    IntegrationDisconnected,
)
from shared.py.wide_events import log

router = APIRouter()


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
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        log.error(
            f"{LogTag.INTEGRATION} Error adding integration",
            integration_id=request.integration_id,
            user_id=user_id,
            error_type=type(e).__name__,
            error=str(e),
        )
        raise HTTPException(status_code=500, detail="Failed to add integration") from e
    # No-auth integrations land directly in `connected` (the service stamps the
    # status); OAuth/bearer-managed ones capture IntegrationConnected at their callback.
    if user_integration.status == "connected":
        capture(
            UserId(user_id),
            IntegrationConnected(
                integration_id=user_integration.integration_id, source="workspace"
            ),
        )
    return AddUserIntegrationResponse(
        message="Integration added to workspace",
        integration_id=user_integration.integration_id,
        connection_status=user_integration.status,
    )


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
        # Removing a connected integration is attributed the same as an
        # explicit disconnect. Analytics-only read: a failed status lookup
        # must never block the removal itself.
        try:
            was_connected = await user_integration_repository.is_connected(user_id, integration_id)
        except Exception as e:
            log.warning(
                f"{LogTag.INTEGRATION} Failed to read connection status before removal",
                integration_id=integration_id,
                user_id=user_id,
                error_type=type(e).__name__,
                error=str(e),
            )
            # None and False are equally falsy here, so a None-mutation of
            # this fallback is behaviorally unreachable. pragma: no mutate
            was_connected = False  # pragma: no mutate
        removed = await remove_from_workspace(user_id, integration_id)
        if not removed:
            raise HTTPException(status_code=404, detail="Integration not found in workspace")
        if was_connected:
            capture(UserId(user_id), IntegrationDisconnected(integration_id=integration_id))
        log.set(outcome="success")
        return IntegrationSuccessResponse(
            message="Integration removed from workspace",
            integration_id=integration_id,
        )
    except HTTPException:
        raise
    except Exception as e:
        log.error(
            f"{LogTag.INTEGRATION} Error removing integration",
            integration_id=integration_id,
            user_id=user_id,
            error_type=type(e).__name__,
            error=str(e),
        )
        raise HTTPException(status_code=500, detail="Failed to remove integration") from e
