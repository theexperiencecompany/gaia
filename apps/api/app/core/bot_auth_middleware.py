"""
Bot Authentication Middleware

Handles authentication for bot platforms (Discord, Slack, Telegram).
Supports two authentication methods:
1. JWT Bearer token (fast path, cached) - issued after initial API key auth
2. API key + platform headers (initial auth) - looks up user by platform ID

This middleware sets request.state.user and request.state.authenticated,
allowing bot requests to use the same endpoints as normal web auth.
"""

from collections.abc import Awaitable, Callable
import secrets
from typing import cast

from fastapi import Request, Response
from jose import JWTError
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.config.settings import settings
from app.constants.cache import TEN_MINUTES_TTL
from app.constants.log_tags import LogTag
from app.db.redis import get_cache, set_cache
from app.models.user_models import AuthenticatedUser
from app.services.bot_token_service import verify_bot_session_token
from app.services.platform_link_service import PlatformLinkService
from app.utils.auth_utils import build_user_context
from shared.py.wide_events import log


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

        authenticated = False

        # 1. Try JWT Bearer token (fast path)
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:]
            try:
                user_info = await self._authenticate_jwt(token)
                if user_info:
                    request.state.user = user_info
                    request.state.authenticated = True
                    authenticated = True
            except JWTError as e:
                log.debug(
                    f"{LogTag.API} Bot JWT rejected, trying API key",
                    error=str(e),
                    error_type=type(e).__name__,
                )
            except Exception as e:
                # Not a token problem — Redis/Mongo lookups can fail here. Still
                # falls through to API key auth, but never silently.
                log.warning(
                    f"{LogTag.API} Bot JWT authentication errored, trying API key",
                    error=str(e),
                    error_type=type(e).__name__,
                )

        # 2. The API key is verified INDEPENDENTLY of the JWT outcome. The two
        # answer different questions: the key authorises the bot ROUTE
        # (require_bot_api_key), the JWT identifies the USER. Verifying the key
        # only when the JWT had failed left every successful fast-path request
        # with bot_api_key_valid unset, so /bot/* answered 401, the bot threw
        # its cached session token away and retried with the key — a wasted
        # round trip on nearly every turn.
        api_key = request.headers.get("X-Bot-API-Key")
        platform = request.headers.get("X-Bot-Platform")
        platform_user_id = request.headers.get("X-Bot-Platform-User-Id")

        if api_key and self._verify_api_key(api_key):
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

        response = await call_next(request)
        return response

    def _verify_api_key(self, api_key: str) -> bool:
        bot_api_key = getattr(settings, "GAIA_BOT_API_KEY", None)
        if not bot_api_key:
            # The API has no bot key configured at all — every bot request is
            # silently rejected today. That is exactly the "Authentication
            # required" dead-end the harness hits when the API was booted
            # before GAIA_BOT_API_KEY was set. Fail loud instead.
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
        cached_user_info = await get_cache(cache_key)

        if cached_user_info and cached_user_info.get("user_id"):
            return cast(AuthenticatedUser, cached_user_info)

        user_data = await PlatformLinkService.get_user_by_platform_id(platform, platform_user_id)

        if not user_data:
            return None

        user_info = build_user_context(
            user_data, auth_provider=f"bot:{platform}", bot_authenticated=True
        )

        await set_cache(cache_key, user_info, ttl=TEN_MINUTES_TTL)
        return user_info

    async def _authenticate_jwt(self, token: str) -> AuthenticatedUser | None:
        """Authenticate via JWT session token with caching."""
        try:
            payload = verify_bot_session_token(token)

            user_id = payload.get("user_id")
            platform = payload.get("platform")
            platform_user_id = payload.get("platform_user_id")

            if not user_id or not platform or not platform_user_id:
                return None

            cache_key = f"bot_user:{platform}:{platform_user_id}"
            cached_user_info = await get_cache(cache_key)

            if cached_user_info and cached_user_info.get("user_id") == user_id:
                return cast(AuthenticatedUser, cached_user_info)

            user_data = await PlatformLinkService.get_user_by_platform_id(
                platform, platform_user_id
            )

            if not user_data:
                return None

            if str(user_data.get("_id")) != user_id:
                return None

            user_info = build_user_context(
                user_data, auth_provider=f"bot:{platform}", bot_authenticated=True
            )

            await set_cache(cache_key, user_info, ttl=TEN_MINUTES_TTL)
            return user_info

        except JWTError:
            raise
