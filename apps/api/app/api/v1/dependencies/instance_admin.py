"""Instance-admin authorization for the setup and members surfaces.

Administering a self-host instance means holding the admin role, which the
first account to sign up receives. The routes are only mounted for local auth;
the local-auth check here is a fail-closed second layer so a wiring mistake
surfaces as 403 instead of exposing instance management.
"""

from typing import Annotated

from fastapi import Depends, HTTPException

from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.config.settings import settings
from app.constants.auth import InstanceRole
from app.models.user_models import AuthenticatedUser

_NOT_INSTANCE_ADMIN = "not_instance_admin"


async def require_instance_admin(
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> AuthenticatedUser:
    """403 unless the caller is a local-auth account holding the admin role."""
    if not settings.deployment.local_auth or user.role is not InstanceRole.ADMIN:
        raise HTTPException(status_code=403, detail=_NOT_INSTANCE_ADMIN)
    return user
