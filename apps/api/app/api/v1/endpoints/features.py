"""User-facing feature flags: list the ones a user may toggle, and store their choice."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.models.user_models import AuthenticatedUser
from app.schemas.feature_flags import (
    UpdateUserFeatureFlagRequest,
    UserFeatureFlagListResponse,
    UserFeatureFlagResponse,
)
from app.services.feature_flags import list_user_flags, set_user_flag
from shared.py.wide_events import log

router = APIRouter()


@router.get("")
async def list_features(
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> UserFeatureFlagListResponse:
    """The flags the caller may toggle, each with the value in effect for them."""
    log.set(user={"id": user.user_id}, feature={"operation": "list"})
    result = await list_user_flags(user.user_id)
    log.set_ns("feature", count=len(result.features))
    return result


@router.patch("/{flag}")
async def update_feature(
    flag: str,
    body: UpdateUserFeatureFlagRequest,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> UserFeatureFlagResponse:
    """Turn one user-facing flag on or off for the caller; unknown and internal flags are 404."""
    log.set(
        user={"id": user.user_id},
        feature={"operation": "toggle", "flag": flag, "enabled": body.enabled},
    )
    result = await set_user_flag(user.user_id, flag, body.enabled)
    log.set_ns("feature", stored=result.enabled)
    return result
