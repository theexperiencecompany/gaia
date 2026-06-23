from typing import Any

from workos import AsyncWorkOSClient

from app.config.settings import settings
from app.constants.log_tags import LogTag
from app.db.mongodb.collections import users_collection
from shared.py.wide_events import log

# T is the return type of the wrapped function


def build_user_context(
    user_data: dict[str, Any], *, auth_provider: str, **extra: Any
) -> dict[str, Any]:
    """Build the canonical ``request.state.user`` dict from a Mongo user doc.

    Every auth path (WorkOS session, agent token, bots) MUST construct the user
    context through this one function. The full doc is spread so downstream
    consumers — chiefly the agent's dynamic context, which reads ``timezone`` and
    ``onboarding`` (custom instructions, preferences, writing style) — always see
    the same fields. Hand-picking a subset is what caused voice mode and the bots
    to silently drop the user's system instructions; defining the shape here once
    means a new auth path physically can't reintroduce that drift.

    ``_id`` is replaced by a string ``user_id``. ``extra`` carries path-specific
    flags (e.g. ``impersonated=True``, ``bot_authenticated=True``).
    """
    context = {
        "auth_provider": auth_provider,
        **user_data,
        "user_id": str(user_data.get("_id")),
        **extra,
    }
    context.pop("_id", None)
    return context


async def authenticate_workos_session(
    session_token: str, workos_client: AsyncWorkOSClient | None = None
) -> tuple[dict[str, Any], str | None]:
    """
    Authenticate a WorkOS session and refresh if needed.
    This is a shared utility function used by both HTTP middleware and WebSocket connections.

    Args:
        session_token: WorkOS sealed session token from cookie
        workos_client: Optional WorkOS client instance to use

    Returns:
        tuple: (user_info, new_session_token) - user_info will be empty dict if auth fails

    Note:
        This function does not raise exceptions - it returns empty dict on failure
        along with None for the session token.
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
            workos_user = auth_response.user  # type: ignore[reportOptionalMemberAccess]
        else:
            # Try to refresh the session
            try:
                refresh_result = await session.refresh(
                    cookie_password=settings.WORKOS_COOKIE_PASSWORD
                )

                if not refresh_result.authenticated:
                    # Authentication failed, even after refresh
                    log.warning(
                        f"{LogTag.AGENT} Authentication failed even after refresh with reason: {refresh_result.reason}"  # type: ignore[reportOptionalMemberAccess]
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
                log.error(f"{LogTag.AGENT} Session refresh error: {e}")
                return {}, None

        # Make sure we have a valid user before continuing
        if not workos_user:
            log.error(f"{LogTag.AGENT} Invalid user data from WorkOS")
            return {}, new_session

        # Retrieve user from database
        try:
            user_email = workos_user.email
            log.set(auth_provider="workos", user_email=user_email)
            user_data = await users_collection.find_one({"email": user_email})

            if not user_data:
                # User doesn't exist in our database
                log.warning(
                    f"{LogTag.AGENT} User {user_email} authenticated but not found in database"
                )
                return {}, new_session

            # Prepare user info for return
            user_info = build_user_context(user_data, auth_provider="workos")
            return user_info, new_session

        except Exception as e:
            log.error(f"{LogTag.AGENT} Error processing user data: {e}")
            return {}, new_session

    except Exception as e:
        log.error(f"{LogTag.AGENT} Error in authenticate_workos_session: {e}")
        return {}, None
