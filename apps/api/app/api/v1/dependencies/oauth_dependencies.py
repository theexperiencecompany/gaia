from datetime import datetime

from fastapi import Depends, Header, HTTPException, Request, WebSocket, status
from fastapi.exceptions import WebSocketException

from app.config.settings import settings
from app.constants.auth import DEV_USER_MISSING_HINT
from app.constants.error_codes import NOT_AUTHENTICATED
from app.constants.log_tags import LogTag
from app.db.repositories.users import user_repository
from app.models.user_models import AuthenticatedUser, UserUpdate
from app.utils.auth_utils import (
    authenticate_workos_session,
    build_user_context,
    resolve_dev_bypass_user,
)
from app.utils.timezone import Timezone, TimezoneSource, resolve_home_timezone
from shared.py.wide_events import log, spawn_logged_task


async def _backfill_user_timezone(user_id: str, tz: str) -> None:
    """Fire-and-forget write-through of the browser-reported timezone."""
    try:
        await user_repository.update(user_id, UserUpdate(timezone=tz))
        log.info(
            f"{LogTag.OAUTH} Backfilled user.timezone from x-timezone header",
            user_id=user_id,
            timezone=tz,
        )
    except Exception as e:
        log.warning(
            f"{LogTag.OAUTH} Failed to backfill user.timezone",
            user_id=user_id,
            timezone=tz,
            error_type=type(e).__name__,
            error=str(e),
        )


# NOSONAR justification: FastAPI dispatches a `def` dependency to a threadpool and
# an `async def` one on the event loop. This reads request.state and nothing else,
# so `async def` is deliberately the cheaper of the two — and it runs on every
# authenticated request. Dropping `async` would add a threadpool hop per request.
async def get_current_user(request: Request) -> AuthenticatedUser:  # NOSONAR python:S7503
    """Return the authenticated user from request state (set by WorkOSAuthMiddleware).

    Raises:
        HTTPException: On authentication failure.
    """
    if not hasattr(request.state, "authenticated") or not request.state.authenticated:
        log.info(f"{LogTag.OAUTH} No authenticated user found in request state")
        raise HTTPException(
            status_code=401,
            detail={
                "code": NOT_AUTHENTICATED,
                "message": "Authentication required",
            },
        )
    # request.state is Starlette's untyped bag; the auth middlewares only ever
    # put an AuthenticatedUser there when authenticated=True, and this is the
    # one place that fact is checked rather than assumed.
    user = request.state.user
    if not isinstance(user, AuthenticatedUser):
        log.error(f"{LogTag.OAUTH} User marked as authenticated but no user data found")
        raise HTTPException(
            status_code=401,
            detail={
                "code": NOT_AUTHENTICATED,
                "message": "User data missing",
            },
        )

    log.set(
        auth={
            "user_id": user.user_id,
            "email": user.email,
            "method": user.auth_provider or "workos",
            "is_agent_token": user.impersonated,
        }
    )
    return user


# NOSONAR justification: same as get_current_user above — a FastAPI dependency that
# only unwraps one field stays on the event loop rather than paying a threadpool hop.
async def get_user_id(  # NOSONAR python:S7503
    user: AuthenticatedUser = Depends(get_current_user),
) -> str:
    """Extract user_id from authenticated user or raise 400."""
    if not user.user_id:
        raise HTTPException(status_code=400, detail="User ID not found")
    return user.user_id


def _ws_unauthenticated(reason: str) -> WebSocketException:
    """Reject the dial with a policy-violation close, so no unauthenticated socket opens."""
    log.set(disconnect_reason="auth_failure")
    return WebSocketException(code=status.WS_1008_POLICY_VIOLATION, reason=reason)


def _require_ws_user_id(user: AuthenticatedUser) -> AuthenticatedUser:
    """Guarantee the caller gets a user it can key on, or no socket at all."""
    if not user.user_id:
        log.warning(f"{LogTag.OAUTH} WebSocket user context carries no user_id")
        raise _ws_unauthenticated("authenticated user has no id")
    return user


async def get_current_user_ws(websocket: WebSocket) -> AuthenticatedUser:
    """Authenticate a WebSocket connection from its cookie or Bearer subprotocol.

    Mobile clients cannot send cookies, so the token also rides the
    Sec-WebSocket-Protocol header as "Bearer, <token>". Every auth failure
    raises WebSocketException instead of returning an empty user.
    """
    # WebSockets skip WorkOSAuthMiddleware (HTTP only), so the dev bypass —
    # including X-Dev-User impersonation — is mirrored here. get_settings()
    # hard-fails if this is set in production.
    if settings.ENV == "development" and settings.DEV_AUTH_BYPASS_EMAIL:
        target_email, user_data = await resolve_dev_bypass_user(websocket)
        if user_data is not None:
            return _require_ws_user_id(
                build_user_context(user_data, auth_provider="workos", dev_bypass=True)
            )
        log.error(
            f"{LogTag.OAUTH} Dev bypass target has no Mongo user",
            target_email=target_email,
            fix=DEV_USER_MISSING_HINT,
        )
        raise _ws_unauthenticated("dev bypass target has no Mongo user")

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
        raise _ws_unauthenticated("no session cookie or protocol token")

    # Use shared authentication logic
    user_info, _ = await authenticate_workos_session(session_token=wos_session)

    if user_info is None:
        log.warning(f"{LogTag.OAUTH} WebSocket authentication failed")
        raise _ws_unauthenticated("session token rejected")

    return _require_ws_user_id(user_info)


GET_USER_TZ_TYPE = tuple[str, datetime]


def get_user_timezone(
    x_timezone: str = Header(
        default="UTC", alias="x-timezone", description="User's timezone identifier"
    ),
) -> GET_USER_TZ_TYPE:
    """Return the current time in the request's x-timezone header zone (defaults to UTC).

    Offset-aware and never raises on a malformed header (falls back to UTC).
    """
    tz = Timezone.parse(x_timezone)
    now = tz.now()
    log.debug(f"{LogTag.OAUTH} Resolved user timezone", timezone=tz.value, now=str(now))
    return tz.value, now


async def get_user_timezone_from_preferences(
    user: AuthenticatedUser = Depends(get_current_user),
    x_timezone: str = Header(
        default="", alias="x-timezone", description="Browser timezone fallback"
    ),
) -> str:
    """Resolve the user's home timezone, healing a stale/junk stored "UTC".

    A real non-UTC stored timezone wins; otherwise a valid x-timezone header
    heals it (so header-less background paths converge on the real zone);
    UTC is the last resort. Emits timezone_source on the wide event.
    """
    user_id = user.user_id

    try:
        resolved = resolve_home_timezone(user.timezone, x_timezone)
        log.set(timezone_source=resolved.source.value, user_timezone=resolved.timezone.value)

        if resolved.source is TimezoneSource.X_TIMEZONE_HEADER:
            log.warning(
                f"{LogTag.OAUTH} Healing user.timezone from x-timezone header",
                user_id=user_id,
                stored_timezone=(user.timezone or "").strip() or None,
                header_timezone=resolved.timezone.value,
            )
        elif resolved.source is TimezoneSource.FALLBACK_UTC and not (user.timezone or "").strip():
            log.warning(
                f"{LogTag.OAUTH} user.timezone missing and no valid x-timezone header; falling back to UTC",
                user_id=user_id,
                header_value=(x_timezone or "").strip() or None,
            )

        if resolved.should_heal and user_id:
            spawn_logged_task(
                "timezone_backfill",
                _backfill_user_timezone(user_id, resolved.timezone.value),
                user={"id": user_id},
                timezone=resolved.timezone.value,
            )

        return resolved.timezone.value

    except Exception as e:
        log.warning(
            f"{LogTag.OAUTH} Error resolving user timezone",
            user_id=user_id,
            error_type=type(e).__name__,
            error=str(e),
        )
        log.set(timezone_source=TimezoneSource.FALLBACK_UTC.value, user_timezone="UTC")
        return "UTC"
