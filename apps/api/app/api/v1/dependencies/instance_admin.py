"""Instance-admin authorization for the self-host-only setup surface.

The self-host deployment has one principal that matters: the administrator who
owns the single row in auth_credentials, since signup closes after the first
account via an atomic single-slot claim. Owning a local credential is therefore
equivalent to being the instance admin. Routes are additionally unmounted
outside selfhost; the ENV check here is a fail-closed second layer so a wiring
mistake surfaces as 403 instead of silently exposing credential management.
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

    Both gates fail closed: the instance must run the canonical self-host auth
    stack (selfhost ENV with local AUTH_MODE), and the caller must own the
    single local credential row. Returns the user so handlers keep their user
    parameter.
    """
    if not settings.is_selfhost or settings.AUTH_MODE != "local":
        raise HTTPException(status_code=403, detail=_NOT_INSTANCE_ADMIN)
    credential = await local_credentials_repository.get_by_user_id(user.user_id)
    if credential is None:
        raise HTTPException(status_code=403, detail=_NOT_INSTANCE_ADMIN)
    return user
