from typing import Any, Dict, Optional, Tuple

from app.config.loggers import auth_logger
from app.config.settings import settings
from app.db.mongodb.collections import users_collection
from workos import AsyncWorkOSClient

# T is the return type of the wrapped function


async def authenticate_workos_session(
    session_token: str, workos_client: Optional[AsyncWorkOSClient] = None
) -> Tuple[Dict[str, Any], Optional[str]]:
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
                    auth_logger.warning(
                        f"Authentication failed even after refresh with reason: {refresh_result.reason}"  # type: ignore[reportOptionalMemberAccess]
                    )
                    return {}, None

                # Get user information via dictionary access for flexibility
                if hasattr(refresh_result, "__dict__"):
                    refresh_dict = refresh_result.__dict__
                    workos_user = refresh_dict.get("user")
                    new_session = refresh_dict.get("sealed_session")
                    if not workos_user:
                        auth_logger.error(
                            "Refresh successful but no user data in refresh result"
                        )
                        return {}, new_session
                else:
                    auth_logger.error("Refresh result doesn't have expected structure")
                    return {}, None

            except Exception as e:
                auth_logger.error(f"Session refresh error: {e}")
                return {}, None

        # Make sure we have a valid user before continuing
        if not workos_user:
            auth_logger.error("Invalid user data from WorkOS")
            return {}, new_session

        # Retrieve user from database
        try:
            user_email = workos_user.email
            user_data = await users_collection.find_one({"email": user_email})

            if not user_data:
                # User doesn't exist in our database
                auth_logger.warning(
                    f"User {user_email} authenticated but not found in database"
                )
                return {}, new_session

            # Prepare user info for return
            user_info = {
                "user_id": str(user_data.get("_id")),
                "auth_provider": "workos",
                **user_data,
            }

            user_info.pop("_id", None)
            return user_info, new_session

        except Exception as e:
            auth_logger.error(f"Error processing user data: {e}")
            return {}, new_session

    except Exception as e:
        auth_logger.error(f"Error in authenticate_workos_session: {e}")
        return {}, None
