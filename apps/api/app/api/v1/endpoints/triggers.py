"""
Triggers API endpoints for workflow automation.

Provides endpoints for fetching available trigger schemas
that can be used in workflow configuration.
"""

from typing import Any, Dict, List, Union

from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.services.triggers import get_handler_by_name
from app.services.workflow.trigger_service import TriggerService
from fastapi import APIRouter, Depends, HTTPException, Request

router = APIRouter(prefix="/triggers")


@router.get("/schema", response_model=List[Dict[str, Any]])
async def get_trigger_schemas(
    _: dict = Depends(get_current_user),
) -> List[Dict[str, Any]]:
    """
    Get all available workflow trigger schemas.

    Returns a list of trigger configurations that can be used when creating
    or editing workflows, including their config schemas for dynamic UI generation.
    """
    return await TriggerService.get_all_workflow_triggers()


@router.get("/options")
async def get_trigger_options(
    request: Request,
    integration_id: str,
    trigger_slug: str,
    field_name: str = "",
    parent_values: str = "",
    current_user: dict = Depends(get_current_user),
) -> Dict[str, List[Union[Dict[str, str], Dict[str, Any]]]]:
    """
    Get dynamic options for a trigger configuration field.
    Passes any additional query parameters to the handler.

    Args:
        request: FastAPI request object (to extract additional query params)
        integration_id: The integration ID (e.g., 'slack', 'trello')
        trigger_slug: The trigger slug (e.g., 'slack_new_message')
        field_name: The config field name (e.g., 'channel_id'), optional
        parent_values: Comma-separated parent IDs for cascading options (e.g., 'workspace1,workspace2')

    Returns:
        {"options": [{"value": "...", "label": "..."} | {"group": "...", "options": [...]}]}
    """
    handler = get_handler_by_name(trigger_slug)
    if not handler:
        raise HTTPException(status_code=404, detail="Handler not found for trigger")

    # Parse parent values
    parent_ids = (
        [v.strip() for v in parent_values.split(",") if v.strip()]
        if parent_values
        else None
    )

    # Extract additional query parameters (e.g., page, search)
    # Exclude the standard parameters we already handle
    standard_params = {
        "integration_id",
        "trigger_slug",
        "field_name",
        "parent_values",
    }
    kwargs = {
        key: value
        for key, value in request.query_params.items()
        if key not in standard_params
    }

    # Fetch options from handler, passing all kwargs
    options = await handler.get_config_options(
        trigger_slug,
        field_name,
        current_user["user_id"],
        integration_id,
        parent_ids,
        **kwargs,
    )

    return {"options": options}
