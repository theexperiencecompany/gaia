"""WorkOS session auth middleware + get_current_user dependency."""

from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from posthog import identify_context, new_context
from pydantic import TypeAdapter, ValidationError
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp
from workos import AsyncWorkOSClient

from app.api.v1.middleware.agent_auth import verify_agent_token
from app.api.v1.middleware.client_type import (
    BACKGROUND_REQUEST_ORIGIN,
    REQUEST_ORIGIN_HEADER,
    request_client_source,
)
from app.config.settings import settings
from app.config.workos import get_async_workos_client
from app.constants.analytics import POSTHOG_PROVIDER_KEY, POSTHOG_SESSION_HEADER
from app.constants.auth import DEV_USER_HEADER, DEV_USER_MISSING_HINT
from app.constants.error_codes import NOT_AUTHENTICATED
from app.constants.log_tags import LogTag
from app.core.lazy_loader import providers
from app.core.request_context import set_authenticated_user
from app.db.repositories.users import user_repository
from app.models.chat_models import ConversationSource
from app.models.user_models import AuthenticatedUser
from app.schemas.errors import ErrorEnvelope, error_response
from app.utils.auth_utils import (
    authenticate_workos_session,
    build_user_context,
    resolve_dev_bypass_user,
    session_cookie_secure,
)
from app.utils.local_auth_utils import (
    LOCAL_SESSION_COOKIE,
    LocalSessionFailure,
    authenticate_local_session,
)
from shared.py.analytics.catalog.attribution import Actor, Attribution, EntrySurface, Trigger
from shared.py.analytics.catalog.properties import Identifier
from shared.py.analytics.context import AnalyticsContext, analytics_context, worker_context
from shared.py.wide_events import log


def get_current_user(request: Request) -> AuthenticatedUser | None:
    """Return the authenticated user on request.state, or None."""
    user = getattr(request.state, "user", None)
    return user if isinstance(user, AuthenticatedUser) else None


#: Routes a third party calls on its own schedule, not a user's request.
WEBHOOK_PATH_PREFIXES = ("/api/v1/payments/webhooks/", "/api/v1/webhook/")


def request_analytics_context(request: Request) -> AnalyticsContext:
    """Attribute a request: a webhook is the worker's, a client's automatic request is system work.

    Anything else is its caller's own action. The surface is the client that
    sent it: a bot (its API key), the voice worker (the agent token only voice
    sessions mint) or the web or desktop app.
    """
    if request.url.path.startswith(WEBHOOK_PATH_PREFIXES):
        return worker_context(Trigger.WEBHOOK)
    user = get_current_user(request)
    if getattr(request.state, "bot_api_key_valid", False):
        surface = EntrySurface.BOT
    elif user is not None and user.impersonated:
        surface = EntrySurface.VOICE
    elif request_client_source(request) is ConversationSource.DESKTOP:
        surface = EntrySurface.DESKTOP
    else:
        surface = EntrySurface.WEB
    automatic = request.headers.get(REQUEST_ORIGIN_HEADER) == BACKGROUND_REQUEST_ORIGIN
    attribution = (
        Attribution(actor=Actor.AGENT, trigger=Trigger.SYSTEM, surface=surface)
        if automatic
        else Attribution(actor=Actor.USER, trigger=Trigger.INTERACTIVE, surface=surface)
    )
    return AnalyticsContext(
        attribution=attribution, posthog_session_id=_posthog_session_id(request)
    )


def _posthog_session_id(request: Request) -> str | None:
    """Read the browser's PostHog session id; a malformed one joins no session."""
    session_id = request.headers.get(POSTHOG_SESSION_HEADER)
    if session_id is None:
        return None
    try:
        return _SESSION_ID.validate_python(session_id)
    except ValidationError:
        log.warning("posthog_session_header_rejected", length=len(session_id))
        return None


_SESSION_ID: TypeAdapter[str] = TypeAdapter(Identifier)


class PostHogRequestContextMiddleware(BaseHTTPMiddleware):
    """Bind the request's analytics context and PostHog identity around every capture in it.

    Runs inside WorkOS and bot authentication, so the user is the stable Mongo
    id whichever way the request authenticated, and the context knows which
    client the request came from.
    """

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        with analytics_context(request_analytics_context(request)):
            user = get_current_user(request)
            user_id = user.user_id if user else None
            # An unconfigured provider resolves to None (SILENT strategy), so this one
            # check covers both a missing token and an unbuilt client.
            if not user_id or providers.get(POSTHOG_PROVIDER_KEY) is None:
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
        # Only AUTH_MODE="workos" has a WorkOS client: local (self-host) mode
        # runs with no WorkOS credentials configured, so constructing the
        # client there would either raise or carry a useless None-keyed client.
        self.workos: AsyncWorkOSClient | None = (
            workos_client
            if workos_client is not None
            else (None if settings.deployment.local_auth else get_async_workos_client())
        )
        self.exclude_paths = exclude_paths or [
            "/docs",
            "/redoc",
            "/openapi.json",
            "/oauth/login",
            "/oauth/workos/callback",
            "/oauth/google/callback",
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
            # Code mode's sandbox callbacks — the E2B script has no session; both
            # routes authenticate via the run's HMAC token (execute_token.py).
            "/api/v1/sandbox/execute",
            "/api/v1/sandbox/tool-schema",
            # Single-purpose file-share downloads: fetched server-side by
            # Composio with no session; the unguessable token authenticates the
            # grant. Trailing slash avoids matching the rest of /api/v1/files.
            "/api/v1/files/s/",
            # Dev identity router (dev only): excluded so the mint endpoint is
            # reachable before any user exists, or the bypass 401s the request
            # that bootstraps it. Trailing slash avoids matching "/api/v1/device".
            "/api/v1/dev/",
        ]
        # Local-mode-only public surfaces: signup and login must be reachable
        # before any session exists, and the setup status probe and provider
        # catalog are read pre-auth. In workos mode these stay authenticated.
        if settings.deployment.local_auth:
            self.exclude_paths += [
                "/api/v1/auth/signup",
                "/api/v1/auth/login",
                "/api/v1/setup/status",
                "/api/v1/setup/catalog",
            ]
        # Exact-match exclusions — ``startswith`` on these would make
        # ``/api/v1/setup/status/evil`` bypass auth. Only the literal path is
        # public; any suffix must be authenticated.
        _exact_candidates: set[str] = {
            "/api/v1/auth/signup",
            "/api/v1/auth/login",
            "/api/v1/setup/status",
            "/api/v1/setup/catalog",
        }
        self._exclude_exact: set[str] = _exact_candidates.intersection(self.exclude_paths)
        # Everything else in exclude_paths is an intentional prefix (docs covers
        # docs/... too). Matching uses path == p or startswith(p + "/") so
        # /docs does not match /docsfoo.
        self._exclude_prefix: list[str] = [
            p for p in self.exclude_paths if p not in self._exclude_exact
        ]
        # Routes that also accept an "Authorization: Bearer <agent JWT>" in
        # addition to a WorkOS session cookie.
        self.agent_only_paths = ["/api/v1/chat-stream"]
        self.user_cache_expiry = 3600
        self.dev_bypass_email = (
            settings.DEV_AUTH_BYPASS_EMAIL if settings.deployment.dev_tools else None
        )
        if self.dev_bypass_email:
            log.warning(
                f"{LogTag.API} DEV AUTH BYPASS ACTIVE — every request is "
                f"authenticated as the bypass user (development only)",
                dev_bypass_email=self.dev_bypass_email,
            )

    def _is_excluded(self, path: str) -> bool:
        """Whether path is excluded from authentication."""
        if path in self._exclude_exact:
            return True
        return any(path == p or path.startswith(p.rstrip("/") + "/") for p in self._exclude_prefix)

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Authenticate, then invoke the next handler. Refresh cookies on the way out."""
        if self._is_excluded(request.url.path):
            self._publish_user(request)
            return await call_next(request)

        if self.dev_bypass_email:
            return await self._dispatch_dev_bypass(request, call_next)

        # Self-host mode: authenticate via the local session JWT instead of
        # WorkOS. Everything below (agent-token fallback, cookie refresh) is
        # WorkOS-specific and skipped entirely.
        if settings.deployment.local_auth:
            return await self._dispatch_local_session(request, call_next)

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

        await self._authenticate_agent_token(request, auth_provider="workos")

        self._publish_user(request)
        response = await call_next(request)

        if hasattr(request.state, "new_session") and request.state.new_session:
            response.set_cookie(
                key="wos_session",
                value=request.state.new_session,
                httponly=True,
                secure=session_cookie_secure(request),
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
        if user_info is None:
            # Can't log.set() here — this runs outside LoggingMiddleware's context, so
            # wide event fields would be wiped by log.reset(). Stash the reason instead
            # so the route layer can log it inside the right context.
            request.state.auth_failure = "invalid_or_expired_session"
            return
        request.state.user = user_info
        request.state.authenticated = True
        if new_session:
            request.state.new_session = new_session

    async def _authenticate_agent_token(self, request: Request, *, auth_provider: str) -> None:
        """Resolve an agent bearer token onto request.state, if it carries one.

        One implementation serves both dispatch branches: voice and desktop
        clients present an AGENT_SECRET-signed JWT instead of a browser cookie,
        but only on the agent-only paths. auth_provider names which session
        system the request would otherwise have used.
        """
        if request.state.authenticated or request.url.path not in self.agent_only_paths:
            return
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return
        agent_info = verify_agent_token(auth_header.split(" ", 1)[1])
        if not agent_info:
            return
        try:
            user_data = await user_repository.get(agent_info.user_id)
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
            user_data, auth_provider=auth_provider, impersonated=True
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

        target_email, user_data = await resolve_dev_bypass_user(request)
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

        request.state.user = build_user_context(user_data, auth_provider="workos", dev_bypass=True)
        request.state.authenticated = True
        self._publish_user(request)
        return await call_next(request)

    async def _dispatch_local_session(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Authenticate a local (self-host) session JWT and pass through.

        An absent, invalid, or expired session leaves request.state.user as None
        and the request flows on; route handlers enforce auth via get_current_user.
        Read from the gaia_session cookie with the WorkOS path's Bearer fallback;
        no refresh step, as tokens carry a fixed 30-day expiry.
        """
        request.state.user = None
        request.state.authenticated = False
        request.state.new_session = None

        token: str | None = request.cookies.get(LOCAL_SESSION_COOKIE)
        if not token:
            auth_header = request.headers.get("Authorization")
            if auth_header and auth_header.startswith("Bearer "):
                token = auth_header.split(" ", 1)[1]

        if token:
            session = await authenticate_local_session(token)
            if isinstance(session, LocalSessionFailure):
                request.state.auth_failure = session
            else:
                request.state.user = session
                request.state.authenticated = True

        await self._authenticate_agent_token(request, auth_provider="email")

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
        set_authenticated_user(get_current_user(request))

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
        if user_info is None:
            return None, new_session
        # Fire-and-forget: touch_last_active is debounced and never raises, so a
        # failed last-active write can no longer turn a valid session into a
        # failed authentication (the previous try/except returned None here).
        await user_repository.touch_last_active(user_info.email or "")
        return user_info, new_session
