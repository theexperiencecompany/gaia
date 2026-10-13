"""Instance-admin authorization for the setup surface.

Administering the instance means holding a local credential: the first account
to sign up gets one, and signup closes after it today. Routes are unmounted
without runtime credentials; the local-auth check here is a fail-closed second
layer so a wiring mistake surfaces as 403 instead of exposing credential management.
"""

from typing import Annotated

from fastapi import Depends, HTTPException

from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.config.settings import settings
from app.db.repositories.local_credentials import local_credentials_repository
from app.models.user_models import AuthenticatedUser

_NOT_INSTANCE_ADMIN = "not_instance_admin"


async def require_instance_admin(
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> AuthenticatedUser:
    """403 unless the caller authenticates as this instance's administrator.

    Both gates fail closed: the instance must run local auth, and the caller
    must hold a local credential (the first account to sign up administers the
    instance). Returns the user so handlers keep their user parameter.
    """
    if not settings.deployment.local_auth:
        raise HTTPException(status_code=403, detail=_NOT_INSTANCE_ADMIN)
    credential = await local_credentials_repository.get_by_user_id(user.user_id)
    if credential is None:
        raise HTTPException(status_code=403, detail=_NOT_INSTANCE_ADMIN)
    return user
