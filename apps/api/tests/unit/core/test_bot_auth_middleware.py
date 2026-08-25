"""Tests for BotAuthMiddleware — bot platform authentication.

Covers: JWT bearer auth (valid, invalid, missing fields), API key + platform
headers auth (cached, uncached, missing user), excluded paths, already-
authenticated requests, and edge cases around missing settings.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI, Request, Response
from httpx import ASGITransport, AsyncClient
from jose import JWTError
import pytest
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from app.core.bot_auth_middleware import BotAuthMiddleware

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FAKE_USER_DATA: dict[str, Any] = {
    "_id": "user_abc123",
    "email": "bot@example.com",
    "name": "Bot User",
    "picture": "https://example.com/pic.png",
}

FAKE_JWT_PAYLOAD: dict[str, Any] = {
    "user_id": "user_abc123",
    "platform": "discord",
    "platform_user_id": "disc_999",
}


def _build_app(
    exclude_paths: list[str] | None = None,
) -> FastAPI:
    """Create a minimal FastAPI app with BotAuthMiddleware installed."""
    app = FastAPI()
    app.add_middleware(BotAuthMiddleware, exclude_paths=exclude_paths)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/test")
    async def api_test(request: Request) -> dict[str, Any]:
        return {
            "authenticated": getattr(request.state, "authenticated", False),
            "user": getattr(request.state, "user", None),
            "bot_api_key_valid": getattr(request.state, "bot_api_key_valid", False),
            "bot_platform": getattr(request.state, "bot_platform", None),
            "bot_platform_user_id": getattr(request.state, "bot_platform_user_id", None),
        }

    return app


# ---------------------------------------------------------------------------
# Excluded paths
# ---------------------------------------------------------------------------


class TestExcludedPaths:
    @pytest.fixture
    def app(self) -> FastAPI:
        return _build_app()

    async def test_health_endpoint_bypasses_middleware(self, app: FastAPI) -> None:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="https://test") as client:
            resp = await client.get("/health")
        assert resp.status_code == 200

    async def test_docs_excluded_by_default(self) -> None:
        app = _build_app()
        # /docs should be excluded
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="https://test") as client:
            resp = await client.get("/docs")
        # FastAPI returns 404 for /docs when no OpenAPI UI is set up, but the
        # middleware should NOT block it — we just check it's not a 500/403
        assert resp.status_code in (200, 404)

    async def test_custom_exclude_paths(self) -> None:
        app = _build_app(exclude_paths=["/custom-path"])

        @app.get("/custom-path")
        async def custom() -> dict[str, str]:
            return {"ok": "true"}

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="https://test") as client:
            resp = await client.get("/custom-path")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Already authenticated (WorkOS middleware sets request.state.authenticated)
# ---------------------------------------------------------------------------


class TestAlreadyAuthenticated:
    async def test_skips_when_already_authenticated(self) -> None:
        """If another middleware already set authenticated=True, BotAuth is a no-op."""
        app = FastAPI()

        # A middleware that sets authenticated before BotAuthMiddleware runs
        class PreAuthMiddleware(BaseHTTPMiddleware):
            async def dispatch(
                self, request: Request, call_next: RequestResponseEndpoint
            ) -> Response:
                request.state.authenticated = True
                request.state.user = {"user_id": "pre_auth_user"}
                return await call_next(request)

        # Order matters: last added runs first (outermost)
        app.add_middleware(BotAuthMiddleware)
        app.add_middleware(PreAuthMiddleware)

        @app.get("/api/test")
        async def endpoint(request: Request) -> dict[str, Any]:
            return {
                "authenticated": request.state.authenticated,
                "user_id": request.state.user.get("user_id"),
            }

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="https://test") as client:
            resp = await client.get("/api/test")

        assert resp.status_code == 200
        data = resp.json()
        assert data["authenticated"] is True
        assert data["user_id"] == "pre_auth_user"

    @patch("app.core.bot_auth_middleware.get_cache", new_callable=AsyncMock)
    @patch("app.core.bot_auth_middleware.set_cache", new_callable=AsyncMock)
    @patch(
        "app.core.bot_auth_middleware.PlatformLinkService.get_user_by_platform_id",
        new_callable=AsyncMock,
    )
    @patch("app.core.bot_auth_middleware.verify_bot_session_token")
    async def test_already_authenticated_request_is_never_re_resolved(
        self,
        mock_verify: MagicMock,
        mock_platform: AsyncMock,
        mock_set_cache: AsyncMock,
        mock_get_cache: AsyncMock,
    ) -> None:
        """The short circuit must actually skip re-authentication, not just
        happen to leave the same answer in place.

        A valid ``Authorization`` header for a DIFFERENT user rides along on
        this request. If the ``if getattr(request.state, "authenticated",
        False):`` guard is bypassed (wrong object, wrong attribute name, or
        wrong default), the middleware runs its own JWT verification and
        clobbers the pre-authenticated identity with this one.
        """
        mock_verify.return_value = FAKE_JWT_PAYLOAD  # resolves to "user_abc123"
        mock_get_cache.return_value = None
        mock_platform.return_value = FAKE_USER_DATA

        app = FastAPI()

        class PreAuthMiddleware(BaseHTTPMiddleware):
            async def dispatch(
                self, request: Request, call_next: RequestResponseEndpoint
            ) -> Response:
                request.state.authenticated = True
                request.state.user = {"user_id": "pre_auth_user"}
                return await call_next(request)

        app.add_middleware(BotAuthMiddleware)
        app.add_middleware(PreAuthMiddleware)

        @app.get("/api/test")
        async def endpoint(request: Request) -> dict[str, Any]:
            return {
                "authenticated": request.state.authenticated,
                "user_id": request.state.user.get("user_id"),
            }

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="https://test") as client:
            resp = await client.get(
                "/api/test",
                headers={"Authorization": "Bearer someone-elses-valid-jwt"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["user_id"] == "pre_auth_user"
        mock_verify.assert_not_called()


# ---------------------------------------------------------------------------
# JWT Bearer token authentication
# ---------------------------------------------------------------------------


class TestJWTAuth:
    @pytest.fixture
    def app(self) -> FastAPI:
        return _build_app()

    @patch("app.core.bot_auth_middleware.get_cache", new_callable=AsyncMock)
    @patch("app.core.bot_auth_middleware.set_cache", new_callable=AsyncMock)
    @patch(
        "app.core.bot_auth_middleware.PlatformLinkService.get_user_by_platform_id",
        new_callable=AsyncMock,
    )
    @patch("app.core.bot_auth_middleware.verify_bot_session_token")
    async def test_exactly_the_bearer_prefix_is_stripped_from_the_token(
        self,
        mock_verify: MagicMock,
        mock_platform: AsyncMock,
        mock_set_cache: AsyncMock,
        mock_get_cache: AsyncMock,
        app: FastAPI,
    ) -> None:
        """``"Bearer "`` is 7 characters — the verifier must receive the token
        with none of its own characters eaten."""
        mock_verify.return_value = FAKE_JWT_PAYLOAD
        mock_get_cache.return_value = None
        mock_platform.return_value = FAKE_USER_DATA

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="https://test") as client:
            resp = await client.get(
                "/api/test",
                headers={"Authorization": "Bearer abcdef123456"},
            )

        assert resp.status_code == 200
        mock_verify.assert_called_once_with("abcdef123456")

    @patch("app.core.bot_auth_middleware.get_cache", new_callable=AsyncMock)
    @patch("app.core.bot_auth_middleware.set_cache", new_callable=AsyncMock)
    @patch(
        "app.core.bot_auth_middleware.PlatformLinkService.get_user_by_platform_id",
        new_callable=AsyncMock,
    )
    @patch("app.core.bot_auth_middleware.verify_bot_session_token")
    async def test_valid_jwt_authenticates_user(
        self,
        mock_verify: MagicMock,
        mock_platform: AsyncMock,
        mock_set_cache: AsyncMock,
        mock_get_cache: AsyncMock,
        app: FastAPI,
    ) -> None:
        mock_verify.return_value = FAKE_JWT_PAYLOAD
        mock_get_cache.return_value = None  # No cached user
        mock_platform.return_value = FAKE_USER_DATA

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="https://test") as client:
            resp = await client.get(
                "/api/test",
                headers={"Authorization": "Bearer valid-jwt-token"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["authenticated"] is True
        assert data["user"]["user_id"] == "user_abc123"
        assert data["user"]["auth_provider"] == "bot:discord"
        assert data["user"]["bot_authenticated"] is True

    @patch("app.core.bot_auth_middleware.get_cache", new_callable=AsyncMock)
    @patch("app.core.bot_auth_middleware.set_cache", new_callable=AsyncMock)
    @patch("app.core.bot_auth_middleware.verify_bot_session_token")
    async def test_valid_jwt_uses_cached_user(
        self,
        mock_verify: MagicMock,
        mock_set_cache: AsyncMock,
        mock_get_cache: AsyncMock,
        app: FastAPI,
    ) -> None:
        cached_user = {
            "user_id": "user_abc123",
            "email": "bot@example.com",
            "name": "Bot User",
            "picture": None,
            "auth_provider": "bot:discord",
            "bot_authenticated": True,
        }
        mock_verify.return_value = FAKE_JWT_PAYLOAD
        mock_get_cache.return_value = cached_user

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="https://test") as client:
            resp = await client.get(
                "/api/test",
                headers={"Authorization": "Bearer cached-jwt"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["authenticated"] is True
        assert data["user"]["user_id"] == "user_abc123"
        # set_cache should not be called when cache hit
        mock_set_cache.assert_not_awaited()

    @patch("app.core.bot_auth_middleware.verify_bot_session_token")
    async def test_jwt_error_falls_through(
        self,
        mock_verify: MagicMock,
        app: FastAPI,
    ) -> None:
        """JWTError should be caught; request proceeds unauthenticated."""
        mock_verify.side_effect = JWTError("expired")

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="https://test") as client:
            resp = await client.get(
                "/api/test",
                headers={"Authorization": "Bearer bad-jwt"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["authenticated"] is False

    @patch("app.core.bot_auth_middleware.get_cache", new_callable=AsyncMock)
    @patch("app.core.bot_auth_middleware.verify_bot_session_token")
    async def test_jwt_missing_user_id_returns_none(
        self,
        mock_verify: MagicMock,
        mock_get_cache: AsyncMock,
        app: FastAPI,
    ) -> None:
        """Token payload missing required fields should not authenticate."""
        mock_verify.return_value = {
            "user_id": None,
            "platform": "discord",
            "platform_user_id": "disc_999",
        }

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="https://test") as client:
            resp = await client.get(
                "/api/test",
                headers={"Authorization": "Bearer incomplete-jwt"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["authenticated"] is False

    @patch("app.core.bot_auth_middleware.get_cache", new_callable=AsyncMock)
    @patch("app.core.bot_auth_middleware.set_cache", new_callable=AsyncMock)
    @patch(
        "app.core.bot_auth_middleware.PlatformLinkService.get_user_by_platform_id",
        new_callable=AsyncMock,
    )
    @patch("app.core.bot_auth_middleware.verify_bot_session_token")
    async def test_jwt_user_id_mismatch_returns_none(
        self,
        mock_verify: MagicMock,
        mock_platform: AsyncMock,
        mock_set_cache: AsyncMock,
        mock_get_cache: AsyncMock,
        app: FastAPI,
    ) -> None:
        """If JWT user_id doesn't match DB user _id, authentication fails."""
        mock_verify.return_value = {
            "user_id": "different_user_id",
            "platform": "discord",
            "platform_user_id": "disc_999",
        }
        mock_get_cache.return_value = None
        mock_platform.return_value = FAKE_USER_DATA  # _id = "user_abc123"

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="https://test") as client:
            resp = await client.get(
                "/api/test",
                headers={"Authorization": "Bearer mismatch-jwt"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["authenticated"] is False

    @patch("app.core.bot_auth_middleware.get_cache", new_callable=AsyncMock)
    @patch(
        "app.core.bot_auth_middleware.PlatformLinkService.get_user_by_platform_id",
        new_callable=AsyncMock,
    )
    @patch("app.core.bot_auth_middleware.verify_bot_session_token")
    async def test_jwt_platform_user_not_found(
        self,
        mock_verify: MagicMock,
        mock_platform: AsyncMock,
        mock_get_cache: AsyncMock,
        app: FastAPI,
    ) -> None:
        mock_verify.return_value = FAKE_JWT_PAYLOAD
        mock_get_cache.return_value = None
        mock_platform.return_value = None  # User not linked

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="https://test") as client:
            resp = await client.get(
                "/api/test",
                headers={"Authorization": "Bearer unlinked-jwt"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["authenticated"] is False


# ---------------------------------------------------------------------------
# API Key + platform headers authentication
# ---------------------------------------------------------------------------


class TestAPIKeyAuth:
    @pytest.fixture
    def app(self) -> FastAPI:
        return _build_app()

    @patch("app.core.bot_auth_middleware.get_cache", new_callable=AsyncMock)
    @patch("app.core.bot_auth_middleware.set_cache", new_callable=AsyncMock)
    @patch(
        "app.core.bot_auth_middleware.PlatformLinkService.get_user_by_platform_id",
        new_callable=AsyncMock,
    )
    @patch("app.core.bot_auth_middleware.settings")
    async def test_valid_api_key_with_platform_headers(
        self,
        mock_settings: MagicMock,
        mock_platform: AsyncMock,
        mock_set_cache: AsyncMock,
        mock_get_cache: AsyncMock,
        app: FastAPI,
    ) -> None:
        mock_settings.GAIA_BOT_API_KEY = "secret-bot-key"  # pragma: allowlist secret
        mock_get_cache.return_value = None
        mock_platform.return_value = FAKE_USER_DATA

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="https://test") as client:
            resp = await client.get(
                "/api/test",
                headers={
                    "X-Bot-API-Key": "secret-bot-key",
                    "X-Bot-Platform": "telegram",
                    "X-Bot-Platform-User-Id": "tg_123",
                },
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["authenticated"] is True
        assert data["user"]["auth_provider"] == "bot:telegram"
        assert data["bot_api_key_valid"] is True
        assert data["bot_platform"] == "telegram"
        assert data["bot_platform_user_id"] == "tg_123"

    @patch("app.core.bot_auth_middleware.get_cache", new_callable=AsyncMock)
    @patch("app.core.bot_auth_middleware.set_cache", new_callable=AsyncMock)
    @patch(
        "app.core.bot_auth_middleware.PlatformLinkService.get_user_by_platform_id",
        new_callable=AsyncMock,
    )
    @patch("app.core.bot_auth_middleware.settings")
    async def test_the_request_resolves_the_platform_user_it_names(
        self,
        mock_settings: MagicMock,
        mock_platform: AsyncMock,
        mock_set_cache: AsyncMock,
        mock_get_cache: AsyncMock,
        app: FastAPI,
    ) -> None:
        """Two linked users on one platform must not resolve to each other.

        Every other test here hands the lookup a single canned user, so the id
        the middleware passed down was never checked — and authenticating one
        person's request as another is the worst failure this file has.
        """
        mock_settings.GAIA_BOT_API_KEY = "secret-bot-key"  # pragma: allowlist secret
        mock_get_cache.return_value = None
        linked = {
            "tg_123": {**FAKE_USER_DATA, "_id": "user_one", "email": "one@example.com"},
            "tg_456": {**FAKE_USER_DATA, "_id": "user_two", "email": "two@example.com"},
        }
        mock_platform.side_effect = lambda _platform, platform_user_id: linked.get(platform_user_id)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="https://test") as client:
            resp = await client.get(
                "/api/test",
                headers={
                    "X-Bot-API-Key": "secret-bot-key",
                    "X-Bot-Platform": "telegram",
                    "X-Bot-Platform-User-Id": "tg_456",
                },
            )

        assert resp.json()["user"]["user_id"] == "user_two"

    @patch("app.core.bot_auth_middleware.get_cache", new_callable=AsyncMock)
    @patch("app.core.bot_auth_middleware.settings")
    async def test_valid_api_key_with_cached_platform_user(
        self,
        mock_settings: MagicMock,
        mock_get_cache: AsyncMock,
        app: FastAPI,
    ) -> None:
        mock_settings.GAIA_BOT_API_KEY = "secret-bot-key"  # pragma: allowlist secret
        cached_user = {
            "user_id": "user_abc123",
            "email": "bot@example.com",
            "name": "Bot User",
            "picture": None,
            "auth_provider": "bot:slack",
            "bot_authenticated": True,
        }
        mock_get_cache.return_value = cached_user

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="https://test") as client:
            resp = await client.get(
                "/api/test",
                headers={
                    "X-Bot-API-Key": "secret-bot-key",
                    "X-Bot-Platform": "slack",
                    "X-Bot-Platform-User-Id": "slack_456",
                },
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["authenticated"] is True

    @patch("app.core.bot_auth_middleware.settings")
    async def test_invalid_api_key_rejected(
        self,
        mock_settings: MagicMock,
        app: FastAPI,
    ) -> None:
        mock_settings.GAIA_BOT_API_KEY = "correct-key"  # pragma: allowlist secret

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="https://test") as client:
            resp = await client.get(
                "/api/test",
                headers={
                    "X-Bot-API-Key": "wrong-key",
                    "X-Bot-Platform": "discord",
                    "X-Bot-Platform-User-Id": "disc_1",
                },
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["authenticated"] is False
        assert data["bot_api_key_valid"] is False

    @patch("app.core.bot_auth_middleware.settings")
    async def test_api_key_not_configured(
        self,
        mock_settings: MagicMock,
        app: FastAPI,
    ) -> None:
        """When GAIA_BOT_API_KEY is not set, all API key auth should fail."""
        mock_settings.GAIA_BOT_API_KEY = None

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="https://test") as client:
            resp = await client.get(
                "/api/test",
                headers={
                    "X-Bot-API-Key": "any-key",
                    "X-Bot-Platform": "discord",
                    "X-Bot-Platform-User-Id": "disc_1",
                },
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["authenticated"] is False

    @patch("app.core.bot_auth_middleware.get_cache", new_callable=AsyncMock)
    @patch(
        "app.core.bot_auth_middleware.PlatformLinkService.get_user_by_platform_id",
        new_callable=AsyncMock,
    )
    @patch("app.core.bot_auth_middleware.settings")
    async def test_valid_api_key_without_platform_headers(
        self,
        mock_settings: MagicMock,
        mock_platform: AsyncMock,
        mock_get_cache: AsyncMock,
        app: FastAPI,
    ) -> None:
        """Valid API key but no platform/user_id headers: bot_api_key_valid=True but not authenticated."""
        mock_settings.GAIA_BOT_API_KEY = "secret-bot-key"  # pragma: allowlist secret

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="https://test") as client:
            resp = await client.get(
                "/api/test",
                headers={"X-Bot-API-Key": "secret-bot-key"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["authenticated"] is False
        assert data["bot_api_key_valid"] is True
        mock_platform.assert_not_awaited()

    @patch("app.core.bot_auth_middleware.get_cache", new_callable=AsyncMock)
    @patch(
        "app.core.bot_auth_middleware.PlatformLinkService.get_user_by_platform_id",
        new_callable=AsyncMock,
    )
    @patch("app.core.bot_auth_middleware.settings")
    async def test_valid_api_key_unlinked_platform_user(
        self,
        mock_settings: MagicMock,
        mock_platform: AsyncMock,
        mock_get_cache: AsyncMock,
        app: FastAPI,
    ) -> None:
        """Valid API key + platform headers, but user not linked in DB."""
        mock_settings.GAIA_BOT_API_KEY = "secret-bot-key"  # pragma: allowlist secret
        mock_get_cache.return_value = None
        mock_platform.return_value = None

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="https://test") as client:
            resp = await client.get(
                "/api/test",
                headers={
                    "X-Bot-API-Key": "secret-bot-key",
                    "X-Bot-Platform": "discord",
                    "X-Bot-Platform-User-Id": "unknown_disc_user",
                },
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["authenticated"] is False
        assert data["bot_api_key_valid"] is True
        assert data["bot_platform"] == "discord"
        assert data["bot_platform_user_id"] == "unknown_disc_user"


# ---------------------------------------------------------------------------
# No auth headers at all
# ---------------------------------------------------------------------------


class TestNoAuthHeaders:
    async def test_request_without_any_auth(self) -> None:
        app = _build_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="https://test") as client:
            resp = await client.get("/api/test")

        assert resp.status_code == 200
        data = resp.json()
        assert data["authenticated"] is False
        assert data["bot_api_key_valid"] is False


# ---------------------------------------------------------------------------
# JWT takes precedence over API key
# ---------------------------------------------------------------------------


class TestAuthPrecedence:
    @patch("app.core.bot_auth_middleware.get_cache", new_callable=AsyncMock)
    @patch("app.core.bot_auth_middleware.set_cache", new_callable=AsyncMock)
    @patch(
        "app.core.bot_auth_middleware.PlatformLinkService.get_user_by_platform_id",
        new_callable=AsyncMock,
    )
    @patch("app.core.bot_auth_middleware.verify_bot_session_token")
    @patch("app.core.bot_auth_middleware.settings")
    async def test_jwt_used_when_both_jwt_and_api_key_present(
        self,
        mock_settings: MagicMock,
        mock_verify: MagicMock,
        mock_platform: AsyncMock,
        mock_set_cache: AsyncMock,
        mock_get_cache: AsyncMock,
    ) -> None:
        """When both Bearer token and API key are present, JWT should win."""
        mock_settings.GAIA_BOT_API_KEY = "secret-bot-key"  # pragma: allowlist secret
        mock_verify.return_value = FAKE_JWT_PAYLOAD
        mock_get_cache.return_value = None
        mock_platform.return_value = FAKE_USER_DATA

        app = _build_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="https://test") as client:
            resp = await client.get(
                "/api/test",
                headers={
                    "Authorization": "Bearer jwt-token",
                    "X-Bot-API-Key": "secret-bot-key",
                    "X-Bot-Platform": "slack",
                    "X-Bot-Platform-User-Id": "slack_1",
                },
            )

        data = resp.json()
        assert data["authenticated"] is True
        # JWT authenticates via discord (from FAKE_JWT_PAYLOAD), not slack
        assert data["user"]["auth_provider"] == "bot:discord"

    @pytest.mark.regression
    @patch("app.core.bot_auth_middleware.get_cache", new_callable=AsyncMock)
    @patch("app.core.bot_auth_middleware.set_cache", new_callable=AsyncMock)
    @patch(
        "app.core.bot_auth_middleware.PlatformLinkService.get_user_by_platform_id",
        new_callable=AsyncMock,
    )
    @patch("app.core.bot_auth_middleware.verify_bot_session_token")
    @patch("app.core.bot_auth_middleware.settings")
    async def test_jwt_fast_path_still_marks_the_bot_api_key_valid(
        self,
        mock_settings: MagicMock,
        mock_verify: MagicMock,
        mock_platform: AsyncMock,
        mock_set_cache: AsyncMock,
        mock_get_cache: AsyncMock,
    ) -> None:
        """A valid JWT must not hide a valid API key.

        The key authorises the bot ROUTE (``require_bot_api_key``); the JWT only
        identifies the user. Verifying the key only when the JWT failed left
        every fast-path request with ``bot_api_key_valid`` unset, so ``/bot/*``
        answered 401 and the bot threw its session token away and retried —
        a wasted round trip on almost every turn.
        """
        mock_settings.GAIA_BOT_API_KEY = "secret-bot-key"  # pragma: allowlist secret
        mock_verify.return_value = FAKE_JWT_PAYLOAD
        mock_get_cache.return_value = None
        mock_platform.return_value = FAKE_USER_DATA

        app = _build_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="https://test") as client:
            resp = await client.get(
                "/api/test",
                headers={
                    "Authorization": "Bearer jwt-token",
                    "X-Bot-API-Key": "secret-bot-key",
                    "X-Bot-Platform": "discord",
                    "X-Bot-Platform-User-Id": "disc_999",
                },
            )

        data = resp.json()
        assert data["authenticated"] is True
        assert data["bot_api_key_valid"] is True
        assert data["bot_platform"] == "discord"
        assert data["bot_platform_user_id"] == "disc_999"

    @patch("app.core.bot_auth_middleware.verify_bot_session_token")
    @patch("app.core.bot_auth_middleware.settings")
    async def test_jwt_fast_path_leaves_an_invalid_key_invalid(
        self,
        mock_settings: MagicMock,
        mock_verify: MagicMock,
    ) -> None:
        """The key is verified, not assumed — a wrong key stays rejected even
        when the JWT authenticated the user."""
        mock_settings.GAIA_BOT_API_KEY = "secret-bot-key"  # pragma: allowlist secret
        mock_verify.return_value = FAKE_JWT_PAYLOAD

        app = _build_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="https://test") as client:
            resp = await client.get(
                "/api/test",
                headers={
                    "Authorization": "Bearer jwt-token",
                    "X-Bot-API-Key": "wrong-key",
                },
            )

        assert resp.json()["bot_api_key_valid"] is False


# ---------------------------------------------------------------------------
# _verify_api_key edge: missing GAIA_BOT_API_KEY attribute
# ---------------------------------------------------------------------------


class TestVerifyApiKeyEdge:
    async def test_missing_attribute_on_settings(self) -> None:
        """When settings object has no GAIA_BOT_API_KEY attribute at all."""
        app = _build_app()

        with patch(
            "app.core.bot_auth_middleware.settings",
            new=MagicMock(spec=[]),
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="https://test") as client:
                resp = await client.get(
                    "/api/test",
                    headers={"X-Bot-API-Key": "any-key"},
                )

        assert resp.status_code == 200
        data = resp.json()
        assert data["authenticated"] is False
