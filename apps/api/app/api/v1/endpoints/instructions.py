"""The user's standing instructions: "global" or one connected integration's id."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.v1.dependencies.oauth_dependencies import get_user_id
from app.models.user_instructions_models import (
    InstructionsEditor,
    InstructionsResponse,
    UpdateInstructionsRequest,
)
from app.schemas.errors import error_responses
from app.services.user_instructions_service import (
    get_instructions_record,
    validate_scope,
    write_instructions,
)
from shared.py.wide_events import log

router = APIRouter(prefix="/instructions")


@router.get(
    "/{scope}",
    responses=error_responses({400: "Invalid scope", 404: "Integration not connected"}),
)
async def get_instructions(
    scope: str,
    user_id: Annotated[str, Depends(get_user_id)],
) -> InstructionsResponse:
    """Return one scope's instructions with the revision a save must send back."""
    log.set(user={"id": user_id}, instructions={"operation": "get"})
    await validate_scope(user_id, scope)
    record = await get_instructions_record(user_id, scope)
    log.set_ns("instructions", revision=record.revision)
    return record


@router.put(
    "/{scope}",
    responses=error_responses(
        {
            400: "Invalid scope or content",
            404: "Integration not connected",
            409: "Changed elsewhere since base_revision",
        }
    ),
)
async def update_instructions(
    scope: str,
    request: UpdateInstructionsRequest,
    user_id: Annotated[str, Depends(get_user_id)],
) -> InstructionsResponse:
    """Replace one scope's instructions; 409 when base_revision is no longer current."""
    log.set(user={"id": user_id}, instructions={"operation": "update"})
    saved = await write_instructions(
        user_id,
        scope,
        request.content,
        updated_by=InstructionsEditor.USER,
        base_revision=request.base_revision,
    )
    log.set_ns("instructions", revision=saved.revision)
    return saved
