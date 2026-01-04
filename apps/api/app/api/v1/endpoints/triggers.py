"""
Triggers API endpoints for workflow automation.

Provides endpoints for fetching available trigger schemas
that can be used in workflow configuration.
"""

from typing import Any, Dict, List

from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.services.workflow.trigger_service import TriggerService
from fastapi import APIRouter, Depends

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
