import asyncio
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from bson import ObjectId
from fastapi import Depends, Header, HTTPException, Request, WebSocket, status

from app.constants.error_codes import NOT_AUTHENTICATED
from app.db.mongodb.collections import users_collection
from shared.py.wide_events import log

_TIMEZONE_BACKFILL_TASKS: set[asyncio.Task[Any]] = set()


def _is_valid_iana_or_offset(tz: str) -> bool:
    """Cheap validation: accept IANA names or ±HH:MM offsets; reject garbage."""
    if not tz:
        return False
    if tz.startswith(("+", "-")) and len(tz) == 6 and tz[3] == ":":
        return True
    try:
        ZoneInfo(tz)
        return True
    except (ZoneInfoNotFoundError, ValueError):
        return False


async def _backfill_user_timezone(user_id: str, tz: str) -> None:
    """Fire-and-forget write-through of the browser-reported timezone."""
    try:
        await users_collection.update_one(
            {"_id": ObjectId(user_id)},
            {"$set": {"timezone": tz, "updated_at": datetime.now(UTC)}},
        )
        log.info(
            "Backfilled user.timezone from x-timezone header",
            user_id=user_id,
            timezone=tz,
        )
    except Exception as e:
        log.warning(f"Failed to backfill user.timezone for {user_id}: {e}")


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
        log.info("No authenticated user found in request state")
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": NOT_AUTHENTICATED,
                "message": "Authentication required",
            },
        )
    if not request.state.user:
        log.error("User marked as authenticated but no user data found")
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": NOT_AUTHENTICATED,
                "message": "User data missing",
            },
        )

    user = request.state.user
    log.set(
        auth={
            "user_id": user.get("user_id"),
            "email": user.get("email"),
            "method": user.get("auth_provider", "workos"),
            "is_agent_token": bool(user.get("is_agent_token", False)),
        }
    )
    return user


async def get_user_id(user: dict = Depends(get_current_user)) -> str:
    """Extract user_id from authenticated user or raise 400."""
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="User ID not found")
    return str(user_id)


async def get_current_user_ws(websocket: WebSocket):
    """
    Authenticate a user from a WebSocket connection using cookies.
    This is a special version of get_current_user for WebSocket connections.

    For mobile clients that cannot send cookies, the token is passed via the
    Sec-WebSocket-Protocol header (subprotocol) for security. This prevents
    token exposure in server logs and referrers.

    Protocol format: "Bearer, <token>" (client sends ['Bearer', token])

    Args:
        websocket: The WebSocket connection with cookies

    Returns:
        User data dictionary with authentication info

    Raises:
        WebSocketException: Connection will be closed on auth failure
    """
    from app.utils.auth_utils import authenticate_workos_session

    # Extract the session cookie from WebSocket
    wos_session = websocket.cookies.get("wos_session")

    # Fallback: check Sec-WebSocket-Protocol header for mobile clients
    # Client sends: new WebSocket(url, ['Bearer', token])
    # Server receives: "Bearer, <token>" in sec-websocket-protocol header
    if not wos_session:
        protocol_header = websocket.headers.get("sec-websocket-protocol", "")
        if protocol_header.startswith("Bearer, "):
            wos_session = protocol_header[8:]  # Extract token after "Bearer, "

    if not wos_session:
        log.info("No session cookie or protocol token in WebSocket request")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return {}

    # Use shared authentication logic
    user_info, _ = await authenticate_workos_session(session_token=wos_session)

    if not user_info:
        log.warning("WebSocket authentication failed")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return {}

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

    log.debug(f"User timezone: {user_tz}, Current time: {now}")
    return x_timezone, now


async def get_user_timezone_from_preferences(
    user: dict = Depends(get_current_user),
    x_timezone: str = Header(
        default="", alias="x-timezone", description="Browser timezone fallback"
    ),
) -> str:
    """
    Resolve the user's timezone with three-tier priority:

      1. `user.timezone` stored in Mongo (set during onboarding)
      2. `x-timezone` request header (browser-reported IANA zone)
      3. UTC (last resort)

    Emits the wide-event field `timezone_source` so every request makes
    it visible which branch was used. When we fall through to the header,
    fire-and-forget a backfill so the Mongo doc is populated for next time.
    """
    user_id = user.get("user_id")

    try:
        stored_tz = (user.get("timezone") or "").strip()
        if stored_tz:
            log.set(timezone_source="user_profile", user_timezone=stored_tz)
            return stored_tz

        header_tz = (x_timezone or "").strip()
        if header_tz and header_tz.upper() != "UTC" and _is_valid_iana_or_offset(header_tz):
            log.set(timezone_source="x_timezone_header", user_timezone=header_tz)
            log.warning(
                "user.timezone missing; using x-timezone header fallback",
                user_id=user_id,
                header_timezone=header_tz,
            )
            if user_id:
                task = asyncio.create_task(_backfill_user_timezone(user_id, header_tz))
                _TIMEZONE_BACKFILL_TASKS.add(task)
                task.add_done_callback(_TIMEZONE_BACKFILL_TASKS.discard)
            return header_tz

        log.set(timezone_source="fallback_utc", user_timezone="UTC")
        log.warning(
            "user.timezone missing and no valid x-timezone header; falling back to UTC",
            user_id=user_id,
            header_value=header_tz or None,
        )
        return "UTC"

    except Exception as e:
        log.warning(f"Error resolving user timezone: {e}", user_id=user_id)
        log.set(timezone_source="fallback_utc", user_timezone="UTC")
        return "UTC"
