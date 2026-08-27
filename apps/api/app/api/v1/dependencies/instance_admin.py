"""Instance-admin authorization for the self-host-only ``/setup`` surface.

The self-host deployment has exactly one principal that matters: the
administrator who owns THE row in ``auth_credentials`` (signup closes after
the first account via an atomic single-slot claim — see
``LocalCredentialsRepository.try_create``). Owning a local credential is
therefore equivalent to being the instance admin.

Routes are additionally unmounted outside selfhost (see ``routes.py``); the
``ENV`` check here is a fail-closed second layer so that any future wiring
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

    Two gates, both fail-closed:

    - ``settings.ENV == "selfhost"`` and ``settings.AUTH_MODE == "local"`` —
      under hosted auth these endpoints are unmounted; anything reaching them
      elsewhere is refused defensively. The hybrid ``ENV=selfhost`` +
      ``AUTH_MODE=workos`` (explicit override) is also denied so the admin
      surface is only reachable under the canonical self-host auth stack.
    - the caller must own the single local credential row. No row for the
      caller — including the pre-first-signup instance — means no admin.

    Returns the authenticated user so handlers keep their ``user`` parameter.
    """
    if not settings.is_selfhost or settings.AUTH_MODE != "local":
        raise HTTPException(status_code=403, detail=_NOT_INSTANCE_ADMIN)
    credential = await local_credentials_repository.get_by_user_id(user["user_id"])
    if credential is None:
        raise HTTPException(status_code=403, detail=_NOT_INSTANCE_ADMIN)
    return user
