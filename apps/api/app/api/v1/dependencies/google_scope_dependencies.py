"""Unified FastAPI dependencies validating Google OAuth and Composio integrations.

Supports Google OAuth (managed_by="self": calendar, drive, docs) and Composio
(managed_by="composio": gmail, sheets, notion, twitter, linkedin, …).
"""

from collections.abc import Callable, Coroutine

from fastapi import Depends, HTTPException, status
import httpx

from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.config.oauth_config import get_integration_by_id, get_short_name_mapping
from app.constants.error_codes import INTEGRATION_NOT_CONNECTED
from app.constants.log_tags import LogTag
from app.models.user_models import AuthenticatedUser
from app.services.oauth.oauth_service import check_integration_status
from shared.py.wide_events import log

http_async_client = httpx.AsyncClient(timeout=10.0)


def require_integration(
    integration_short_name: str,
) -> Callable[..., Coroutine[None, None, AuthenticatedUser]]:
    """Create a dependency checking Google OAuth or Composio integration access.

    Raises:
        ValueError: Unknown integration name.
    """
    short_name_mapping = get_short_name_mapping()

    if integration_short_name not in short_name_mapping:
        raise ValueError(
            f"Unknown integration: {integration_short_name}. Available: {list(short_name_mapping.keys())}"
        )

    integration_id = short_name_mapping[integration_short_name]
    integration_config = get_integration_by_id(integration_id)

    if not integration_config:
        raise ValueError(f"Integration config not found for: {integration_id}")

    async def wrapper(user: AuthenticatedUser = Depends(get_current_user)) -> AuthenticatedUser:
        user_id = user.user_id
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User ID not found",
            )

        try:
            # Use unified integration status checker
            is_connected = await check_integration_status(integration_id, user_id)

            if not is_connected:
                detail = {
                    "type": "integration",
                    "code": INTEGRATION_NOT_CONNECTED,
                    "toolkit": integration_short_name,
                    "message": f"Missing connection: {integration_config.name}. Please connect integrations in settings.",
                }
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=detail,
                )

            return user

        except HTTPException:
            raise
        except Exception as e:
            log.error(
                f"{LogTag.API} Error checking integration",
                integration=integration_short_name,
                error_type=type(e).__name__,
                error=str(e),
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to verify integration permissions",
            ) from e

    return wrapper


def require_integration_user_id(
    integration_short_name: str,
) -> Callable[..., Coroutine[None, None, str]]:
    """require_integration for handlers that need only the authenticated user id.

    Same checks, same failure modes — it just unwraps the one field instead of
    handing back the whole auth-context dict for each handler to dig into.
    """
    integration_dependency = require_integration(integration_short_name)

    # NOSONAR justification: the factory's return type commits this to a coroutine
    # (Callable[..., Coroutine[None, None, str]]), and as a FastAPI dependency `async def`
    # keeps it on the event loop instead of a threadpool. Dropping `async` would change
    # both the declared contract and where every request runs it.
    async def wrapper(  # NOSONAR python:S7503
        user: AuthenticatedUser = Depends(integration_dependency),
    ) -> str:
        # require_integration has already rejected a missing/empty user_id with a 401.
        return user.user_id

    return wrapper
