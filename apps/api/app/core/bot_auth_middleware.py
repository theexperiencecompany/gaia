"""
Bot Authentication Middleware.

Handles authentication for bot platforms (Discord, Slack, Telegram).
Supports two authentication methods:
1. JWT Bearer token (fast path, cached) - issued after initial API key auth
2. API key + platform headers (initial auth) - looks up user by platform ID

This middleware sets request.state.user and request.state.authenticated,
allowing bot requests to use the same endpoints as normal web auth.
"""

from collections.abc import Awaitable, Callable
import secrets

from fastapi import Request, Response
from jose import JWTError
from pydantic import BaseModel, ConfigDict
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.config.settings import settings
from app.constants.cache import TEN_MINUTES_TTL
from app.constants.log_tags import LogTag
from app.db.redis import get_cache, set_cache
from app.models.user_models import AuthenticatedUser
from app.services.bot_token_service import verify_bot_session_token
from app.utils.auth_utils import resolve_bot_user
from app.utils.log_identifiers import hash_platform_user_id
from shared.py.wide_events import log

_BEARER_PREFIX = "Bearer "


class BotSessionClaims(BaseModel):
    """The identity claims ``verify_bot_session_token`` decodes from a bot JWT.

    Each is optional: a token missing any of them authenticates nobody.
    """

    model_config = ConfigDict(extra="ignore")

    user_id: str | None = None
    platform: str | None = None
    platform_user_id: str | None = None


class BotAuthMiddleware(BaseHTTPMiddleware):
    """
    Middleware for handling bot platform authentication.

    Authentication flow:
    1. Try JWT Bearer token (fast, cached user lookup)
    2. Fall back to X-Bot-API-Key + platform headers (DB lookup)

    On success, sets request.state.user and request.state.authenticated.
    """

    def __init__(
        self,
        app: ASGIApp,
        exclude_paths: list[str] | None = None,
    ) -> None:
        super().__init__(app)
        self.exclude_paths = exclude_paths or [
            "/docs",
            "/redoc",
            "/openapi.json",
            "/health",
        ]

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if any(request.url.path.startswith(path) for path in self.exclude_paths):
            return await call_next(request)

        # Skip if already authenticated by WorkOS middleware
        if getattr(request.state, "authenticated", False):
            return await call_next(request)

        authenticated = await self._authenticate_bearer(request)
        await self._authenticate_api_key(request, authenticated=authenticated)
        return await call_next(request)

    async def _authenticate_bearer(self, request: Request) -> bool:
        """Try the JWT Bearer token (fast path); True when it authenticated the request."""
        auth_header = request.headers.get("Authorization")
        if not (auth_header and auth_header.startswith(_BEARER_PREFIX)):
            return False
        token = auth_header.removeprefix(_BEARER_PREFIX)
        try:
            user_info = await self._authenticate_jwt(token)
        except JWTError as e:
            log.debug(
                f"{LogTag.API} Bot JWT rejected, trying API key",
                error=str(e),
                error_type=type(e).__name__,
            )
            return False
        except Exception as e:
            # Not a token problem — Redis/Mongo lookups can fail here. Still
            # falls through to API key auth, but never silently.
            log.warning(
                f"{LogTag.API} Bot JWT authentication errored, trying API key",
                error=str(e),
                error_type=type(e).__name__,
            )
            return False
        if not user_info:
            return False
        request.state.user = user_info
        request.state.authenticated = True
        return True

    async def _authenticate_api_key(self, request: Request, *, authenticated: bool) -> None:
        """Verify X-Bot-API-Key and, when the JWT did not already, authenticate by platform id.

        Verified independently of the JWT outcome: the key authorises the bot
        route, the JWT identifies the user. Gating it on JWT failure left
        successful fast-path requests with bot_api_key_valid unset, causing 401s.
        """
        api_key = request.headers.get("X-Bot-API-Key")
        platform = request.headers.get("X-Bot-Platform")
        platform_user_id = request.headers.get("X-Bot-Platform-User-Id")

        if api_key and platform:
            # Every bot request's event says which platform account made it,
            # including the ones refused below (never the raw id).
            log.set(platform=platform)
            if platform_user_id:
                log.set(user_hash=hash_platform_user_id(platform_user_id))

        if not (api_key and self._verify_api_key(api_key)):
            return
        # Valid key without a user is still a valid bot request — endpoints
        # like /bot/chat handle the unlinked case themselves.
        request.state.bot_api_key_valid = True
        request.state.bot_platform = platform
        request.state.bot_platform_user_id = platform_user_id

        if not authenticated and platform and platform_user_id:
            user_info = await self._authenticate_platform(platform, platform_user_id)
            if user_info:
                request.state.user = user_info
                request.state.authenticated = True

    def _verify_api_key(self, api_key: str) -> bool:
        bot_api_key = getattr(settings, "GAIA_BOT_API_KEY", None)
        if not bot_api_key:
            # No bot key configured — every bot request is silently rejected,
            # the same "Authentication required" dead-end hit when the API boots
            # without GAIA_BOT_API_KEY set. Fail loud instead.
            log.warning(
                f"{LogTag.API} Bot API key rejected: GAIA_BOT_API_KEY is not configured",
                bot_auth_reason="server_key_unset",
            )
            return False
        # Timing-safe comparison to avoid leaking the key via response-time diffs.
        if not secrets.compare_digest(api_key.encode(), bot_api_key.encode()):
            log.warning(
                f"{LogTag.API} Bot API key rejected: X-Bot-API-Key does not match",
                bot_auth_reason="key_mismatch",
            )
            return False
        return True

    async def _authenticate_platform(
        self, platform: str, platform_user_id: str
    ) -> AuthenticatedUser | None:
        """Authenticate via platform ID lookup with caching."""
        cache_key = f"bot_user:{platform}:{platform_user_id}"
        cached_user_info = await get_cache(cache_key, model=AuthenticatedUser)

        if cached_user_info is not None and cached_user_info.user_id:
            return cached_user_info

        user_info = await resolve_bot_user(platform, platform_user_id)

        if user_info is None:
            return None

        await set_cache(cache_key, user_info, ttl=TEN_MINUTES_TTL, model=AuthenticatedUser)
        return user_info

    async def _authenticate_jwt(self, token: str) -> AuthenticatedUser | None:
        """Authenticate via JWT session token with caching."""
        try:
            claims = BotSessionClaims.model_validate(verify_bot_session_token(token))
            user_id = claims.user_id
            platform = claims.platform
            platform_user_id = claims.platform_user_id

            if not user_id or not platform or not platform_user_id:
                return None

            cache_key = f"bot_user:{platform}:{platform_user_id}"
            cached_user_info = await get_cache(cache_key, model=AuthenticatedUser)

            if cached_user_info is not None and cached_user_info.user_id == user_id:
                return cached_user_info

            user_info = await resolve_bot_user(platform, platform_user_id)

            if user_info is None or user_info.user_id != user_id:
                return None

            await set_cache(cache_key, user_info, ttl=TEN_MINUTES_TTL, model=AuthenticatedUser)
            return user_info

        except JWTError:
            raise
