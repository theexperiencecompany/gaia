import time
from datetime import datetime
from zoneinfo import ZoneInfo

from app.config.loggers import auth_logger as logger, get_current_event
from fastapi import Depends, Header, HTTPException, Request, WebSocket, status


async def get_current_user(request: Request):
    """
    Retrieves the current user from request state.
    Authentication is handled by the WorkOSAuthMiddleware.

    Args:
        request: FastAPI request object with authenticated user in state

    Returns:
        User data dictionary with authentication info

    Raises:
        HTTPException: On authentication failure
    """
    if not hasattr(request.state, "authenticated") or not request.state.authenticated:
        logger.info(
            "auth_failed_no_session",
            path=request.url.path,
            method=request.method,
        )
        raise HTTPException(
            status_code=401, detail="Unauthorized: Authentication required"
        )
    if not request.state.user:
        logger.error(
            "auth_failed_no_user_data",
            path=request.url.path,
            method=request.method,
        )
        raise HTTPException(status_code=401, detail="Unauthorized: User data missing")

    user = request.state.user
    user_id = user.get("user_id")

    # Enrich wide event with user context
    wide_event = get_current_event()
    if wide_event:
        wide_event.set_user_context(user=user)

    logger.debug(
        "auth_success",
        user_id=user_id,
        path=request.url.path,
        method=request.method,
    )

    return user


async def get_current_user_ws(websocket: WebSocket):
    """
    Authenticate a user from a WebSocket connection using cookies.
    This is a special version of get_current_user for WebSocket connections.

    Args:
        websocket: The WebSocket connection with cookies

    Returns:
        User data dictionary with authentication info

    Raises:
        WebSocketException: Connection will be closed on auth failure
    """
    from app.utils.auth_utils import authenticate_workos_session

    start_time = time.time()

    # Extract the session cookie from WebSocket
    wos_session = websocket.cookies.get("wos_session")

    if not wos_session:
        logger.info(
            "ws_auth_no_session",
            client_host=websocket.client.host if websocket.client else "unknown",
        )
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return {}

    # Use shared authentication logic
    user_info, _ = await authenticate_workos_session(session_token=wos_session)

    duration_ms = (time.time() - start_time) * 1000

    if not user_info:
        logger.warning(
            "ws_auth_failed",
            duration_ms=duration_ms,
            client_host=websocket.client.host if websocket.client else "unknown",
        )
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return {}

    logger.info(
        "ws_auth_success",
        user_id=user_info.get("user_id"),
        duration_ms=duration_ms,
    )

    return user_info


GET_USER_TZ_TYPE = tuple[str, datetime]


def get_user_timezone(
    x_timezone: str = Header(
        default="UTC", alias="x-timezone", description="User's timezone identifier"
    ),
) -> GET_USER_TZ_TYPE:
    """
    Get the current time in the user's timezone.
    Uses the x-timezone header to determine the user's timezone.

    Args:
        x_timezone (str): The timezone identifier from the request header.
    Returns:
        datetime: The current time in the user's timezone.
    """
    user_tz = ZoneInfo(x_timezone)
    now = datetime.now(user_tz)

    logger.debug(
        "timezone_resolved",
        timezone=x_timezone,
        current_time=now.isoformat(),
    )
    return x_timezone, now


async def get_user_timezone_from_preferences(
    user: dict = Depends(get_current_user),
) -> str:
    """
    Get the user's timezone from their stored preferences.
    Falls back to UTC if no timezone is set.

    Args:
        user: User data from get_current_user dependency

    Returns:
        User's timezone string (e.g., 'America/New_York', 'UTC')
    """
    try:
        # Only check the root level timezone field
        timezone = user.get("timezone")

        if timezone and timezone.strip():
            logger.debug(
                "user_timezone_from_preferences",
                user_id=user.get("user_id"),
                timezone=timezone,
            )
            return timezone.strip()

        # Fallback to UTC
        logger.debug(
            "user_timezone_fallback_utc",
            user_id=user.get("user_id"),
        )
        return "UTC"

    except Exception as e:
        logger.warning(
            "user_timezone_error",
            user_id=user.get("user_id"),
            error=str(e),
        )
        return "UTC"
