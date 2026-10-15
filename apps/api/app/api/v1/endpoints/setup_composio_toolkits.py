"""Instance setup: browse Composio's toolkit catalog and enable toolkits with one click.

Admin-only, mounted under /setup where the deployment lets its admin enable
toolkits (settings.deployment.instance_toolkits).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from app.api.v1.dependencies.instance_admin import require_instance_admin
from app.api.v1.middleware.rate_limiter import limiter
from app.constants.integrations import COMPOSIO_CATALOG_MAX_PAGE_SIZE
from app.models.user_models import AuthenticatedUser
from app.schemas.integrations.composio_setup import (
    ComposioCatalogResponse,
    ComposioToolkitDetailResponse,
    EnableComposioToolkitRequest,
    EnableComposioToolkitResponse,
)
from app.services.analytics_service import capture
from app.services.composio.toolkit_catalog import catalog_page
from app.services.composio.toolkit_enablement import (
    disable_toolkit,
    enable_toolkit,
    toolkit_detail,
)
from shared.py.analytics import UserId
from shared.py.analytics.catalog.integrations import (
    IntegrationToolkitDisabled,
    IntegrationToolkitEnabled,
)
from shared.py.wide_events import log

router = APIRouter(tags=["Setup"])


@router.get("/composio/toolkits")
async def list_composio_toolkits(
    user: Annotated[AuthenticatedUser, Depends(require_instance_admin)],
    q: Annotated[str, Query(max_length=100, description="Search text")] = "",
    category: Annotated[str | None, Query(max_length=100)] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=COMPOSIO_CATALOG_MAX_PAGE_SIZE)] = 50,
) -> ComposioCatalogResponse:
    """Search Composio's toolkit catalog; each entry says whether it is built in, enabled or available."""
    log.set(
        user={"id": user.user_id},
        operation="list_composio_toolkits",
        composio_catalog={"query_length": len(q), "category": category, "offset": offset},
    )
    page = await catalog_page(q, category, offset, limit)
    log.set(outcome="success")
    return page


@router.get("/composio/toolkits/{slug}")
async def get_composio_toolkit(
    slug: str,
    user: Annotated[AuthenticatedUser, Depends(require_instance_admin)],
) -> ComposioToolkitDetailResponse:
    """Return how enabling the toolkit authenticates and the values it needs, if any."""
    log.set(user={"id": user.user_id}, operation="get_composio_toolkit", toolkit=slug)
    detail = await toolkit_detail(slug.lower())
    log.set(outcome="success", composio_toolkit={"fields": len(detail.fields)})
    return detail


@router.post("/composio/toolkits/{slug}", status_code=201)
@limiter.limit("20/minute")
async def enable_composio_toolkit(
    request: Request,  # noqa: ARG001 -- slowapi's @limiter.limit requires request in the handler signature
    slug: str,
    body: EnableComposioToolkitRequest,
    user: Annotated[AuthenticatedUser, Depends(require_instance_admin)],
) -> EnableComposioToolkitResponse:
    """Create the toolkit's auth config in the instance's Composio project and make it connectable."""
    log.set(user={"id": user.user_id}, operation="enable_composio_toolkit", toolkit=slug)
    result = await enable_toolkit(slug.lower(), body.credentials)
    log.audit(
        "composio toolkit enabled",
        actor=user.user_id,
        toolkit=slug,
        integration_id=result.integration_id,
    )
    capture(
        UserId(user.user_id),
        IntegrationToolkitEnabled(
            toolkit=slug.lower(),
            origin=result.origin,
            composio_managed=result.composio_managed,
        ),
    )
    log.set(outcome="success", integration={"id": result.integration_id})
    return result


@router.delete("/composio/toolkits/{slug}", status_code=204)
async def disable_composio_toolkit(
    slug: str,
    user: Annotated[AuthenticatedUser, Depends(require_instance_admin)],
) -> None:
    """Remove a toolkit the admin enabled; built-in integrations are cleared from the auth config list instead."""
    log.set(user={"id": user.user_id}, operation="disable_composio_toolkit", toolkit=slug)
    await disable_toolkit(slug.lower())
    log.audit("composio toolkit disabled", actor=user.user_id, toolkit=slug)
    capture(UserId(user.user_id), IntegrationToolkitDisabled(toolkit=slug.lower()))
    log.set(outcome="success")
