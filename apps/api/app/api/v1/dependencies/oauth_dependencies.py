import asyncio
from datetime import UTC, datetime
from typing import Any

from bson import ObjectId
from fastapi import Depends, Header, HTTPException, Request, WebSocket, status

from app.constants.error_codes import NOT_AUTHENTICATED
from app.constants.log_tags import LogTag
from app.db.mongodb.collections import users_collection
from app.utils.timezone import Timezone, TimezoneSource, resolve_home_timezone
from shared.py.wide_events import log

_TIMEZONE_BACKFILL_TASKS: set[asyncio.Task[Any]] = set()


async def _backfill_user_timezone(user_id: str, tz: str) -> None:
    """Fire-and-forget write-through of the browser-reported timezone."""
    try:
        await users_collection.update_one(
            {"_id": ObjectId(user_id)},
            {"$set": {"timezone": tz, "updated_at": datetime.now(UTC)}},
        )
        log.info(
            f"{LogTag.OAUTH} Backfilled user.timezone from x-timezone header",
            user_id=user_id,
            timezone=tz,
        )
    except Exception as e:
        log.warning(f"{LogTag.OAUTH} Failed to backfill user.timezone for {user_id}: {e}")


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
        log.info(f"{LogTag.OAUTH} No authenticated user found in request state")
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": NOT_AUTHENTICATED,
                "message": "Authentication required",
            },
        )
    if not request.state.user:
        log.error(f"{LogTag.OAUTH} User marked as authenticated but no user data found")
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
        log.info(f"{LogTag.OAUTH} No session cookie or protocol token in WebSocket request")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return {}

    # Use shared authentication logic
    user_info, _ = await authenticate_workos_session(session_token=wos_session)

    if not user_info:
        log.warning(f"{LogTag.OAUTH} WebSocket authentication failed")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return {}

    return user_info


GET_USER_TZ_TYPE = tuple[str, datetime]


def get_user_timezone(
    x_timezone: str = Header(
        default="UTC", alias="x-timezone", description="User's timezone identifier"
    ),
) -> GET_USER_TZ_TYPE:
    """Current time in the request's ``x-timezone`` header zone (defaults to UTC).

    Returns ``(canonical_timezone, now)``. Offset-aware and never raises on a
    malformed header (falls back to UTC) via ``Timezone.parse``.
    """
    tz = Timezone.parse(x_timezone)
    now = tz.now()
    log.debug(f"{LogTag.OAUTH} User timezone: {tz.value}, Current time: {now}")
    return tz.value, now


async def get_user_timezone_from_preferences(
    user: dict = Depends(get_current_user),
    x_timezone: str = Header(
        default="", alias="x-timezone", description="Browser timezone fallback"
    ),
) -> str:
    """
    Resolve the user's home timezone, healing a stale/junk stored "UTC".

      1. A real (non-UTC) `user.timezone` stored in Mongo is authoritative.
      2. Otherwise — stored value is empty OR a low-confidence "UTC" (often a
         junk default that then sticks forever and silently runs everything in
         UTC) — a valid non-UTC `x-timezone` header wins and is backfilled,
         healing the stored value so header-less background paths (scheduled
         workflows, notifications) converge to the user's real zone.
      3. UTC as last resort, or a genuine stored "UTC" when there is no better
         signal.

    Emits the wide-event field `timezone_source` so every request makes it
    visible which branch was used.
    """
    user_id = user.get("user_id")

    try:
        resolved = resolve_home_timezone(user.get("timezone"), x_timezone)
        log.set(timezone_source=resolved.source.value, user_timezone=resolved.timezone.value)

        if resolved.source is TimezoneSource.X_TIMEZONE_HEADER:
            log.warning(
                f"{LogTag.OAUTH} Healing user.timezone from x-timezone header",
                user_id=user_id,
                stored_timezone=(user.get("timezone") or "").strip() or None,
                header_timezone=resolved.timezone.value,
            )
        elif (
            resolved.source is TimezoneSource.FALLBACK_UTC
            and not (user.get("timezone") or "").strip()
        ):
            log.warning(
                f"{LogTag.OAUTH} user.timezone missing and no valid x-timezone header; falling back to UTC",
                user_id=user_id,
                header_value=(x_timezone or "").strip() or None,
            )

        if resolved.should_heal and user_id:
            task = asyncio.create_task(_backfill_user_timezone(user_id, resolved.timezone.value))
            _TIMEZONE_BACKFILL_TASKS.add(task)
            task.add_done_callback(_TIMEZONE_BACKFILL_TASKS.discard)

        return resolved.timezone.value

    except Exception as e:
        log.warning(f"{LogTag.OAUTH} Error resolving user timezone: {e}", user_id=user_id)
        log.set(timezone_source=TimezoneSource.FALLBACK_UTC.value, user_timezone="UTC")
        return "UTC"
