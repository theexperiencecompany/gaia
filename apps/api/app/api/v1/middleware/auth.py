"""WorkOS session auth middleware + ``get_current_user`` dependency."""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from bson import ObjectId
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp
from workos import AsyncWorkOSClient

from app.api.v1.middleware.agent_auth import verify_agent_token
from app.config.settings import settings
from app.db.mongodb.collections import users_collection
from app.utils.auth_utils import authenticate_workos_session
from shared.py.wide_events import log


def get_current_user(request: Request) -> dict[str, Any] | None:
    """Return the authenticated user dict on ``request.state``, or ``None``."""
    return getattr(request.state, "user", None)


class WorkOSAuthMiddleware(BaseHTTPMiddleware):
    """Authenticate WorkOS session cookies; populate ``request.state.user``.

    Handles cookie refresh and an agent-token fallback for the chat-stream
    endpoint. Unauthenticated requests still pass through — route handlers
    are responsible for enforcing auth via :func:`get_current_user`.
    """

    def __init__(
        self,
        app: ASGIApp,
        workos_client: AsyncWorkOSClient | None = None,
        exclude_paths: list[str] | None = None,
    ):
        super().__init__(app)
        self.workos = workos_client or AsyncWorkOSClient(
            api_key=settings.WORKOS_API_KEY,
            client_id=settings.WORKOS_CLIENT_ID,
        )
        self.exclude_paths = exclude_paths or [
            "/docs",
            "/redoc",
            "/openapi.json",
            "/oauth/login",
            "/oauth/workos/callback",
            "/oauth/google/callback",
            "/user/logout",
            "/health",
            "/api/v1/bot",
            "/api/v1/webhook",
            "/metrics",
        ]
        # Routes that also accept an "Authorization: Bearer <agent JWT>" in
        # addition to a WorkOS session cookie. No prefix-scoped routes are
        # currently configured — the legacy `/api/v1/dev/*` smoke-test prefix
        # was removed when those routes were deleted.
        self.agent_only_paths = ["/api/v1/chat-stream"]
        self.agent_only_path_prefixes: tuple[str, ...] = ()
        self.user_cache_expiry = 3600

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Authenticate, then invoke the next handler. Refresh cookies on the way out."""
        if any(request.url.path.startswith(path) for path in self.exclude_paths):
            return await call_next(request)

        wos_session = request.cookies.get("wos_session")
        if not wos_session:
            auth_header = request.headers.get("Authorization")
            if auth_header and auth_header.startswith("Bearer "):
                wos_session = auth_header.split(" ", 1)[1]

        request.state.user = None
        request.state.authenticated = False
        request.state.new_session = None

        if wos_session:
            try:
                user_info, new_session = await self._authenticate_session(wos_session)
                if user_info:
                    request.state.user = user_info
                    request.state.authenticated = True
                    if new_session:
                        request.state.new_session = new_session
                else:
                    # Session was present but rejected. We can't call
                    # ``log.set()`` here — WorkOSAuthMiddleware runs outside
                    # LoggingMiddleware's context (Starlette copies context at
                    # call_next), so any wide event fields would be wiped by
                    # ``log.reset()``. Stash the reason on request.state so the
                    # route layer can log it inside the right context.
                    request.state.auth_failure = "invalid_or_expired_session"

            except Exception as e:
                log.error(
                    "auth_middleware_error",
                    auth_failure=type(e).__name__,
                    path=request.url.path,
                    method=request.method,
                    session_present=bool(wos_session),
                    error=str(e),
                )
                # Don't block request on auth failures - routes can handle this

        accepts_agent_token = request.url.path in self.agent_only_paths or any(
            request.url.path.startswith(p) for p in self.agent_only_path_prefixes
        )
        if not request.state.authenticated and accepts_agent_token:
            auth_header = request.headers.get("Authorization")
            agent_info = None
            if auth_header and auth_header.startswith("Bearer "):
                token = auth_header.split(" ", 1)[1]
                agent_info = verify_agent_token(token)
            if agent_info:
                user_id = agent_info["user_id"]
                if not isinstance(user_id, ObjectId):
                    try:
                        user_id = ObjectId(user_id)
                    except Exception as e:
                        log.error(f"Invalid user_id format: {user_id} - {e}")
                        user_data = None
                    else:
                        user_data = await users_collection.find_one({"_id": user_id})
                else:
                    user_data = await users_collection.find_one({"_id": user_id})
                if user_data:
                    request.state.user = {
                        "user_id": str(user_data.get("_id")),
                        "email": user_data.get("email"),
                        "name": user_data.get("name"),
                        "picture": user_data.get("picture"),
                        "auth_provider": "workos",
                        "impersonated": True,
                    }
                    request.state.authenticated = True

        response = await call_next(request)

        if hasattr(request.state, "new_session") and request.state.new_session:
            response.set_cookie(
                key="wos_session",
                value=request.state.new_session,
                httponly=True,
                secure=settings.ENV == "production",
                samesite="lax",
                max_age=60 * 60 * 24 * 7,
            )

        return response

    async def _authenticate_session(
        self, wos_session: str
    ) -> tuple[dict[str, Any] | None, str | None]:
        """Authenticate a WorkOS sealed session and bump ``last_active_at``.

        Returns ``(user_info, new_session)`` where ``new_session`` is the
        refreshed token when WorkOS rotates the cookie. Either field may be
        ``None`` on failure; raises if WorkOS itself errors.
        """
        user_info, new_session = await authenticate_workos_session(
            session_token=wos_session, workos_client=self.workos
        )
        if not user_info:
            return None, new_session
        try:
            await users_collection.update_one(
                {"email": user_info["email"]},
                {"$set": {"last_active_at": datetime.now(UTC)}},
            )
            return user_info, new_session
        except Exception as e:
            log.error(f"Error in middleware additional processing: {e}")
            return None, new_session
