"""
Bot Authentication Middleware

Handles authentication for bot platforms (Discord, Slack, Telegram).
Supports two authentication methods:
1. JWT Bearer token (fast path, cached) - issued after initial API key auth
2. API key + platform headers (initial auth) - looks up user by platform ID

This middleware sets request.state.user and request.state.authenticated,
allowing bot requests to use the same endpoints as normal web auth.
"""

from typing import Any, Awaitable, Callable, Dict, Optional

from app.config.settings import settings
from app.constants.cache import TEN_MINUTES_TTL
from app.db.redis import get_cache, set_cache
from app.services.bot_token_service import verify_bot_session_token
from app.services.platform_link_service import PlatformLinkService
from fastapi import Request, Response
from jose import JWTError
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp


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
        exclude_paths: Optional[list[str]] = None,
    ):
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
            except (JWTError, Exception):
                # JWT failed - will try API key below
                pass

        # 2. Fall back to API key + platform headers
        if not authenticated:
            api_key = request.headers.get("X-Bot-API-Key")
            platform = request.headers.get("X-Bot-Platform")
            platform_user_id = request.headers.get("X-Bot-Platform-User-Id")

            if api_key and self._verify_api_key(api_key):
                if platform and platform_user_id:
                    user_info = await self._authenticate_platform(
                        platform, platform_user_id
                    )
                    if user_info:
                        request.state.user = user_info
                        request.state.authenticated = True
                        authenticated = True

                # Mark as bot-api-key-authenticated even without user
                # (for endpoints like /bot/chat that handle unlinked users)
                request.state.bot_api_key_valid = True
                request.state.bot_platform = platform
                request.state.bot_platform_user_id = platform_user_id

        response = await call_next(request)
        return response

    def _verify_api_key(self, api_key: str) -> bool:
        bot_api_key = getattr(settings, "GAIA_BOT_API_KEY", None)
        if not bot_api_key:
            return False
        return api_key == bot_api_key

    async def _authenticate_platform(
        self, platform: str, platform_user_id: str
    ) -> Optional[Dict[str, Any]]:
        """Authenticate via platform ID lookup with caching."""
        cache_key = f"bot_user:{platform}:{platform_user_id}"
        cached_user_info = await get_cache(cache_key)

        if cached_user_info and cached_user_info.get("user_id"):
            return cached_user_info

        user_data = await PlatformLinkService.get_user_by_platform_id(
            platform, platform_user_id
        )

        if not user_data:
            return None

        user_info = {
            "user_id": str(user_data.get("_id")),
            "email": user_data.get("email"),
            "name": user_data.get("name"),
            "picture": user_data.get("picture"),
            "auth_provider": f"bot:{platform}",
            "bot_authenticated": True,
        }

        await set_cache(cache_key, user_info, ttl=TEN_MINUTES_TTL)
        return user_info

    async def _authenticate_jwt(self, token: str) -> Optional[Dict[str, Any]]:
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
                return cached_user_info

            user_data = await PlatformLinkService.get_user_by_platform_id(
                platform, platform_user_id
            )

            if not user_data:
                return None

            if str(user_data.get("_id")) != user_id:
                return None

            user_info = {
                "user_id": str(user_data.get("_id")),
                "email": user_data.get("email"),
                "name": user_data.get("name"),
                "picture": user_data.get("picture"),
                "auth_provider": f"bot:{platform}",
                "bot_authenticated": True,
            }

            await set_cache(cache_key, user_info, ttl=TEN_MINUTES_TTL)
            return user_info

        except JWTError:
            raise
