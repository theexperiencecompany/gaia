"""Instance setup for Composio: which auth config each integration connects through.

Admin-only, mounted with the rest of /setup where the deployment stores runtime
credentials. The Composio API key itself is saved through PUT /setup/providers/composio.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.v1.dependencies.instance_admin import require_instance_admin
from app.api.v1.middleware.rate_limiter import limiter
from app.models.user_models import AuthenticatedUser
from app.schemas.integrations.composio_setup import (
    ComposioSetupResponse,
    SaveComposioAuthConfigsRequest,
)
from app.services.analytics_service import capture
from app.services.composio.auth_config_resolver import save_auth_configs
from app.services.composio.auth_config_setup import composio_setup_overview
from shared.py.analytics import UserId
from shared.py.analytics.catalog.integrations import IntegrationInstanceSetupSaved
from shared.py.wide_events import log

router = APIRouter(tags=["Setup"])


@router.get("/composio")
async def get_composio_setup(
    user: Annotated[AuthenticatedUser, Depends(require_instance_admin)],
) -> ComposioSetupResponse:
    """Each Composio integration's auth config in effect, plus matches found in the Composio project."""
    log.set(user={"id": user.user_id}, operation="get_composio_setup")
    overview = await composio_setup_overview()
    log.set(outcome="success")
    return overview


@router.put("/composio/auth-configs")
@limiter.limit("20/minute")
async def put_composio_auth_configs(
    request: Request,  # noqa: ARG001 -- slowapi's @limiter.limit requires request in the handler signature
    body: SaveComposioAuthConfigsRequest,
    user: Annotated[AuthenticatedUser, Depends(require_instance_admin)],
) -> ComposioSetupResponse:
    """Replace the instance's stored auth config ids and return the updated view."""
    log.set(
        user={"id": user.user_id},
        operation="put_composio_auth_configs",
        composio_setup={"saved": len(body.auth_configs)},
    )
    try:
        await save_auth_configs(body.auth_configs)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    log.audit(
        "composio auth configs saved",
        actor=user.user_id,
        integrations=sorted(body.auth_configs),
    )
    overview = await composio_setup_overview()
    set_up_count = sum(1 for row in overview.integrations if row.auth_config_id is not None)
    capture(
        UserId(user.user_id),
        IntegrationInstanceSetupSaved(
            stored_count=len(body.auth_configs),
            set_up_count=set_up_count,
            total_count=len(overview.integrations),
        ),
    )
    log.set(outcome="success")
    return overview
