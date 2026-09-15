from collections.abc import Mapping
from typing import Any, cast

from starlette.datastructures import Headers
from workos import AsyncWorkOSClient

from app.config.settings import settings
from app.constants.auth import DEV_USER_HEADER
from app.constants.log_tags import LogTag
from app.db.repositories.users import user_repository
from app.models.user_models import AuthenticatedUser, UserDocument, user_to_legacy_dict
from shared.py.wide_events import log


async def resolve_dev_bypass_user(
    headers: Headers, cookies: Mapping[str, str] | None = None
) -> tuple[str, UserDocument | None]:
    """Resolve the dev-bypass target to its Mongo user; the single definition of bypass semantics for both HTTP and WS.

    Precedence: X-Dev-User header (per-request impersonation) > dev_bypass_user cookie (per-browser-profile override) > DEV_AUTH_BYPASS_EMAIL default. Callers own their own failure handling (401 vs WS close).
    """
    target_email: str = (
        headers.get(DEV_USER_HEADER)
        or (cookies or {}).get("dev_bypass_user")
        or settings.DEV_AUTH_BYPASS_EMAIL
        or ""
    )
    return target_email, await user_repository.get_by_email(target_email)


def build_user_context(
    user_data: dict[str, Any], *, auth_provider: str, **extra: bool
) -> AuthenticatedUser:
    """Build the canonical request.state.user dict from a Mongo user doc; every auth path must go through this one function.

    The full doc is spread so downstream consumers (the agent's dynamic context: timezone, onboarding, custom instructions) always see the same fields — hand-picking a subset previously made voice mode and the bots silently drop the user's system instructions. _id becomes a string user_id; extra carries path-specific flags (e.g. impersonated=True).
    """
    context = {
        "auth_provider": auth_provider,
        **user_data,
        "user_id": str(user_data.get("_id")),
        **extra,
    }
    context.pop("_id", None)
    # Correct by construction: assembled right above from an already-validated
    # UserDocument plus the auth-path flags. cast(), not isinstance() (item 12) —
    # the spread of `user_data` is what mypy can't follow, not the shape itself.
    return cast(AuthenticatedUser, context)


async def authenticate_workos_session(
    session_token: str, workos_client: AsyncWorkOSClient | None = None
) -> tuple[AuthenticatedUser, str | None]:
    """Authenticate a WorkOS session and refresh it if needed; shared between HTTP middleware and WebSocket connections.

    Never raises: returns (user_info, new_session_token) with user_info as an empty dict on any failure.
    """
    # Initialize WorkOS client if not provided
    workos = workos_client or AsyncWorkOSClient(
        api_key=settings.WORKOS_API_KEY,
        client_id=settings.WORKOS_CLIENT_ID,
    )

    try:
        # Load and authenticate the WorkOS session
        session = await workos.user_management.load_sealed_session(
            sealed_session=session_token,
            cookie_password=settings.WORKOS_COOKIE_PASSWORD,
        )

        auth_response = session.authenticate()
        new_session = None
        workos_user = None

        # Handle authentication result
        if auth_response.authenticated:
            # Authentication successful
            workos_user = auth_response.user
        else:
            # Try to refresh the session
            try:
                refresh_result = await session.refresh(
                    cookie_password=settings.WORKOS_COOKIE_PASSWORD
                )

                if not refresh_result.authenticated:
                    # Authentication failed, even after refresh
                    log.warning(
                        f"{LogTag.AGENT} Authentication failed even after refresh with reason",
                        reason=refresh_result.reason,
                    )
                    return {}, None

                # Get user information via dictionary access for flexibility
                if hasattr(refresh_result, "__dict__"):
                    refresh_dict = refresh_result.__dict__
                    workos_user = refresh_dict.get("user")
                    new_session = refresh_dict.get("sealed_session")
                    if not workos_user:
                        log.error(
                            f"{LogTag.AGENT} Refresh successful but no user data in refresh result"
                        )
                        return {}, new_session
                else:
                    log.error(f"{LogTag.AGENT} Refresh result doesn't have expected structure")
                    return {}, None

            except Exception as e:
                log.error(
                    f"{LogTag.AGENT} Session refresh error",
                    error=str(e),
                    error_type=type(e).__name__,
                )
                return {}, None

        # Make sure we have a valid user before continuing
        if not workos_user:
            log.error(f"{LogTag.AGENT} Invalid user data from WorkOS")
            return {}, new_session

        # Retrieve user from database
        try:
            user_email = workos_user.email
            log.set(auth_provider="workos", user_email=user_email)
            user_doc = await user_repository.get_by_email(user_email)

            if user_doc is None:
                # User doesn't exist in our database
                log.warning(
                    f"{LogTag.AGENT} User authenticated but not found in database",
                    user_email=user_email,
                )
                return {}, new_session

            # Prepare user info for return
            user_info = build_user_context(user_to_legacy_dict(user_doc), auth_provider="workos")
            return user_info, new_session

        except Exception as e:
            log.error(
                f"{LogTag.AGENT} Error processing user data",
                error=str(e),
                error_type=type(e).__name__,
            )
            return {}, new_session

    except Exception as e:
        log.error(
            f"{LogTag.AGENT} Error in authenticate_workos_session",
            error=str(e),
            error_type=type(e).__name__,
        )
        return {}, None
