"""
Triggers API endpoints for workflow automation.

Provides endpoints for fetching available trigger schemas
that can be used in workflow configuration.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.models.trigger_config import (
    TriggerOptionsParams,
    TriggerOptionsQuery,
    TriggerOptionsResponse,
    WorkflowTriggerResponse,
)
from app.models.user_models import AuthenticatedUser
from app.services.triggers import get_handler_by_name
from app.services.workflow.trigger_service import TriggerService
from shared.py.wide_events import log

router = APIRouter(prefix="/triggers")


@router.get("/schema")
async def get_trigger_schemas(
    _: AuthenticatedUser = Depends(get_current_user),
) -> list[WorkflowTriggerResponse]:
    """
    Get all available workflow trigger schemas.

    Returns a list of trigger configurations that can be used when creating
    or editing workflows, including their config schemas for dynamic UI generation.
    """
    log.set(operation="list_trigger_schemas")
    triggers = await TriggerService.get_all_workflow_triggers()
    log.set(result_count=len(triggers))
    log.set(outcome="success")
    return triggers


@router.get("/options")
async def get_trigger_options(
    params: Annotated[TriggerOptionsParams, Query()],
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> TriggerOptionsResponse:
    """Dynamic options for a trigger configuration field; handlers that do not
    page or search ignore ``page`` and ``search``."""
    log.set(
        operation="get_trigger_options",
        trigger_type=params.trigger_slug,
        integration_name=params.integration_id,
    )
    handler = get_handler_by_name(params.trigger_slug)
    if not handler:
        raise HTTPException(status_code=404, detail="Handler not found for trigger")

    options = await handler.get_config_options(
        TriggerOptionsQuery(
            trigger_name=params.trigger_slug,
            field_name=params.field_name,
            user_id=current_user["user_id"],
            integration_id=params.integration_id,
            parent_ids=params.parent_ids,
            page=params.page,
            search=params.search,
        )
    )

    log.set(result_count=len(options))
    log.set(outcome="success")
    return TriggerOptionsResponse(options=list(options))
