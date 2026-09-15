"""WorkOS session auth middleware + get_current_user dependency."""

from collections.abc import Awaitable, Callable
from typing import Any, cast

from fastapi import Request, Response
from posthog import identify_context, new_context
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp
from workos import AsyncWorkOSClient

from app.api.v1.middleware.agent_auth import verify_agent_token
from app.config.settings import settings
from app.constants.auth import DEV_USER_HEADER, DEV_USER_MISSING_HINT
from app.constants.error_codes import NOT_AUTHENTICATED
from app.constants.log_tags import LogTag
from app.core.lazy_loader import providers
from app.core.request_context import set_authenticated_user
from app.db.repositories.users import user_repository
from app.models.user_models import AuthenticatedUser, user_to_legacy_dict
from app.schemas.errors import ErrorEnvelope, error_response
from app.utils.auth_utils import (
    authenticate_workos_session,
    build_user_context,
    resolve_dev_bypass_user,
)
from shared.py.wide_events import log


def get_current_user(request: Request) -> dict[str, Any] | None:
    """Return the authenticated user dict on request.state, or None."""
    return cast("dict[str, Any] | None", getattr(request.state, "user", None))


class PostHogRequestContextMiddleware(BaseHTTPMiddleware):
    """Bind PostHog identity to the authenticated request context.

    WorkOS authentication runs before this middleware and supplies the stable
    Mongo user id. Captures and exception autocapture in route handlers then
    inherit that identity without each call site having to repeat it.
    """

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        user = getattr(request.state, "user", None)
        user_id = user.get("user_id") if user else None
        if not user_id or not providers.is_available("posthog"):
            return await call_next(request)

        if providers.get("posthog") is None:
            return await call_next(request)

        # capture_exceptions=False is load-bearing: autocapture uses the
        # unconfigured module-level posthog client, which raises and REPLACES
        # the real exception; unhandled_exception_handler already captures it.
        with new_context(capture_exceptions=False):  # pragma: no mutate — None is falsy too
            identify_context(str(user_id))
            return await call_next(request)


class WorkOSAuthMiddleware(BaseHTTPMiddleware):
    """Authenticate WorkOS session cookies; populate request.state.user.

    Handles cookie refresh and an agent-token fallback for the chat-stream
    endpoint. Unauthenticated requests still pass through — route handlers
    are responsible for enforcing auth via :func:get_current_user.
    """

    def __init__(
        self,
        app: ASGIApp,
        workos_client: AsyncWorkOSClient | None = None,
        exclude_paths: list[str] | None = None,
    ) -> None:
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
            # Public desktop release lookup for the marketing download page.
            # Scoped to /releases so the authed /desktop/tool-result bridge stays
            # protected.
            "/api/v1/desktop/releases",
            # Login-free connect link — self-authenticates via a single-use,
            # server-bound connect code (see connect_link_service).
            "/api/v1/integrations/connect-link",
            # Device bridge: the daemon isn't logged in, so these self-authenticate
            # (pairing code / refresh credential / device JWT). /device/pair/approve
            # needs a session, so subroutes are listed explicitly, not by prefix.
            "/api/v1/device/pair/start",
            "/api/v1/device/pair/poll",
            "/api/v1/device/token",
            "/api/v1/device/servers",
            # One-click email unsubscribe — opened from mail clients with no
            # session; the HMAC-signed token authenticates the user itself.
            "/api/v1/notifications/unsubscribe",
            # Single-purpose file-share downloads: fetched server-side by
            # Composio with no session; the unguessable token authenticates the
            # grant. Trailing slash avoids matching the rest of /api/v1/files.
            "/api/v1/files/s/",
            # Dev identity router (dev only): excluded so the mint endpoint is
            # reachable before any user exists, or the bypass 401s the request
            # that bootstraps it. Trailing slash avoids matching "/api/v1/device".
            "/api/v1/dev/",
        ]
        # Routes that also accept an "Authorization: Bearer <agent JWT>" in
        # addition to a WorkOS session cookie.
        self.agent_only_paths = ["/api/v1/chat-stream"]
        self.agent_only_path_prefixes: tuple[str, ...] = ()
        self.user_cache_expiry = 3600
        self.dev_bypass_email = (
            settings.DEV_AUTH_BYPASS_EMAIL if settings.ENV == "development" else None
        )
        if self.dev_bypass_email:
            log.warning(
                f"{LogTag.API} DEV AUTH BYPASS ACTIVE — every request is "
                f"authenticated as the bypass user (development only)",
                dev_bypass_email=self.dev_bypass_email,
            )

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Authenticate, then invoke the next handler. Refresh cookies on the way out."""
        if any(request.url.path.startswith(path) for path in self.exclude_paths):
            self._publish_user(request)
            return await call_next(request)

        if self.dev_bypass_email:
            return await self._dispatch_dev_bypass(request, call_next)

        wos_session = request.cookies.get("wos_session")
        if not wos_session:
            auth_header = request.headers.get("Authorization")
            if auth_header and auth_header.startswith("Bearer "):
                wos_session = auth_header.split(" ", 1)[1]

        request.state.user = None
        request.state.authenticated = False
        request.state.new_session = None

        if wos_session:
            await self._authenticate_wos_session(request, wos_session)

        accepts_agent_token = request.url.path in self.agent_only_paths or any(
            request.url.path.startswith(p) for p in self.agent_only_path_prefixes
        )
        if not request.state.authenticated and accepts_agent_token:
            await self._authenticate_agent_token(request)

        self._publish_user(request)
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

    async def _authenticate_wos_session(self, request: Request, wos_session: str) -> None:
        """Resolve a WorkOS session cookie/bearer onto request.state."""
        try:
            user_info, new_session = await self._authenticate_session(wos_session)
        except Exception as e:
            log.error(
                f"{LogTag.API} auth_middleware_error",
                auth_failure=type(e).__name__,
                path=request.url.path,
                method=request.method,
                session_present=True,
                error=str(e),
            )
            # Don't block request on auth failures - routes can handle this
            return
        if not user_info:
            # Can't log.set() here — this runs outside LoggingMiddleware's context, so
            # wide event fields would be wiped by log.reset(). Stash the reason instead
            # so the route layer can log it inside the right context.
            request.state.auth_failure = "invalid_or_expired_session"
            return
        request.state.user = user_info
        request.state.authenticated = True
        if new_session:
            request.state.new_session = new_session

    async def _authenticate_agent_token(self, request: Request) -> None:
        """Resolve an agent bearer token onto request.state, if it carries one."""
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return
        agent_info = verify_agent_token(auth_header.split(" ", 1)[1])
        if not agent_info:
            return
        try:
            user_data = await user_repository.get(str(agent_info["user_id"]))
        except Exception as e:
            log.error(
                f"{LogTag.API} Invalid user_id in agent token",
                error_type=type(e).__name__,
                error=str(e),
            )
            return
        if user_data is None:
            return
        # Same shape as the WorkOS session path: the shared builder spreads the full doc so
        # the agent token carries timezone + onboarding. Hand-picking fields here dropped
        # them, so voice mode lost the user's system instructions.
        request.state.user = build_user_context(
            user_to_legacy_dict(user_data), auth_provider="workos", impersonated=True
        )
        request.state.authenticated = True

    async def _dispatch_dev_bypass(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Authenticate the request as a dev user, skipping WorkOS.

        Only reachable when DEV_AUTH_BYPASS_EMAIL is set (dev only). Target
        user resolved in order: X-Dev-User header, dev_bypass_user cookie,
        then DEV_AUTH_BYPASS_EMAIL. An email with no Mongo user 401s loud,
        naming the fix (mint via the dev router) rather than a generic error.
        """
        request.state.user = None
        request.state.authenticated = False
        request.state.new_session = None

        target_email, user_data = await resolve_dev_bypass_user(request.headers, request.cookies)
        if user_data is None:
            log.error(
                f"{LogTag.API} Dev bypass target has no Mongo user",
                target_email=target_email,
                dev_impersonated=bool(request.headers.get(DEV_USER_HEADER)),
            )
            return error_response(
                401,
                ErrorEnvelope(
                    message=f"No GAIA user exists for {target_email!r} — {DEV_USER_MISSING_HINT}",
                    code=NOT_AUTHENTICATED,
                ),
            )

        request.state.user = build_user_context(
            user_to_legacy_dict(user_data), auth_provider="workos", dev_bypass=True
        )
        request.state.authenticated = True
        self._publish_user(request)
        return await call_next(request)

    @staticmethod
    def _publish_user(request: Request) -> None:
        """Mirror request.state.user into the request ContextVar.

        Read back from request.state rather than taking the value as an
        argument, so this can never drift from what the handler sees. Must run
        before call_next — that is where the downstream task is created, and
        the task inherits the context as it stands at that moment.
        """
        set_authenticated_user(getattr(request.state, "user", None))

    async def _authenticate_session(
        self, wos_session: str
    ) -> tuple[AuthenticatedUser | None, str | None]:
        """Authenticate a WorkOS sealed session and bump last_active_at.

        Returns (user_info, new_session) where new_session is the
        refreshed token when WorkOS rotates the cookie. Either field may be
        None on failure; raises if WorkOS itself errors.
        """
        user_info, new_session = await authenticate_workos_session(
            session_token=wos_session, workos_client=self.workos
        )
        if not user_info:
            return None, new_session
        # Fire-and-forget: touch_last_active is debounced and never raises, so a
        # failed last-active write can no longer turn a valid session into a
        # failed authentication (the previous try/except returned None here).
        await user_repository.touch_last_active(user_info["email"])
        return user_info, new_session
