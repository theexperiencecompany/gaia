"""Unit tests for the OAuth API endpoints.

Exercises every branch of the WorkOS login/callback flows and the Composio
callback through the ASGI test client. Only seams are mocked — the WorkOS
client, Redis, the user-store service, the Composio service, the OAuth state
service, and the wide-event logger — never the endpoints themselves, and
never the module's redirect helpers (``_store_mobile_redirect`` and
``_get_and_delete_mobile_redirect`` run for real against the mocked Redis).
Assertions pin exact redirect URLs, exact arguments to every seam, and the
audit/error log calls.
"""

from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import quote

from fastapi import BackgroundTasks, HTTPException
from httpx import AsyncClient

from app.config.settings import settings
from app.constants.auth import (
    DESKTOP_DEEP_LINK,
    MOBILE_DEEP_LINK,
    OAUTH_FLOW_DESKTOP,
    OAUTH_FLOW_MOBILE,
    OAUTH_FLOW_WEB,
    WOS_SESSION_COOKIE,
)
from app.constants.cache import MOBILE_REDIRECT_TTL
from app.constants.log_tags import LogTag

OAUTH_BASE = "/api/v1/oauth"
MODULE = "app.api.v1.endpoints.oauth"

# A sealed session carrying characters that only survive untouched when
# ``quote(..., safe='')`` is honored: + / ? = & are all escaped with an
# empty safe set, so any mutation of the ``safe`` argument changes the URL.
_TOKEN_WITH_SPECIAL_CHARS = "sealed+token/abc?x=1&y=2"


def _mock_auth_response(
    email: str = "test@example.com",
    first_name: str = "Test",
    last_name: str = "User",
    picture_url: str | None = None,
    sealed_session: str | None = "sealed_token_abc",
    access_token: str = "access_token_abc",
) -> MagicMock:
    """Build a fake WorkOS authenticate_with_code response."""
    user = MagicMock()
    user.email = email
    user.first_name = first_name
    user.last_name = last_name
    user.profile_picture_url = picture_url
    resp = MagicMock()
    resp.user = user
    resp.sealed_session = sealed_session
    resp.access_token = access_token
    return resp


# ---------------------------------------------------------------------------
# GET /oauth/client-metadata.json
# ---------------------------------------------------------------------------


class TestClientMetadata:
    """GET /api/v1/oauth/client-metadata.json"""

    async def test_client_metadata_document_shape(self, client: AsyncClient) -> None:
        with (
            patch(f"{MODULE}.get_api_base_url", return_value="https://api.test.com"),
            patch(f"{MODULE}.log") as mock_log,
        ):
            response = await client.get(f"{OAUTH_BASE}/client-metadata.json")

        assert response.status_code == 200
        assert response.json() == {
            "client_id": "https://api.test.com/api/v1/oauth/client-metadata.json",
            "client_name": "GAIA",
            "client_uri": "https://heygaia.com",
            "logo_uri": "https://api.test.com/static/logo.png",
            "redirect_uris": ["https://api.test.com/api/v1/mcp/oauth/callback"],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
        }
        mock_log.set.assert_called_once_with(oauth={"operation": "client_metadata"})


# ---------------------------------------------------------------------------
# GET /oauth/login/workos
# ---------------------------------------------------------------------------


class TestLoginWorkOS:
    """GET /api/v1/oauth/login/workos"""

    async def test_login_workos_redirects_to_workos(self, client: AsyncClient) -> None:
        with (
            patch(f"{MODULE}.workos") as mock_workos,
            patch(f"{MODULE}.redis_cache") as mock_redis,
            patch(f"{MODULE}.log") as mock_log,
        ):
            mock_workos.user_management.get_authorization_url.return_value = (
                "https://workos.example.com/auth?client_id=123"
            )
            mock_redis.client = AsyncMock()
            response = await client.get(f"{OAUTH_BASE}/login/workos", follow_redirects=False)

        assert response.status_code == 307
        assert response.headers["location"] == "https://workos.example.com/auth?client_id=123"
        state = mock_workos.user_management.get_authorization_url.call_args.kwargs["state"]
        assert len(state) == 43
        mock_workos.user_management.get_authorization_url.assert_called_once_with(
            provider="authkit",
            redirect_uri=settings.WORKOS_REDIRECT_URI,
            state=state,
        )
        mock_redis.client.setex.assert_not_awaited()
        mock_log.set.assert_called_once_with(
            oauth_flow_type=OAUTH_FLOW_WEB,
            oauth={"operation": "authorize", "provider": "authkit"},
        )

    async def test_login_workos_with_return_url_stores_it(self, client: AsyncClient) -> None:
        with (
            patch(f"{MODULE}.workos") as mock_workos,
            patch(f"{MODULE}.redis_cache") as mock_redis,
        ):
            mock_workos.user_management.get_authorization_url.return_value = (
                "https://workos.example.com/auth"
            )
            mock_redis.client = AsyncMock()
            response = await client.get(
                f"{OAUTH_BASE}/login/workos?return_url=/dashboard",
                follow_redirects=False,
            )

        assert response.status_code == 307
        assert response.headers["location"] == "https://workos.example.com/auth"
        state = mock_workos.user_management.get_authorization_url.call_args.kwargs["state"]
        assert len(state) == 43
        mock_redis.client.setex.assert_awaited_once_with(
            f"oauth_return_url:{state}", 600, "/dashboard"
        )


# ---------------------------------------------------------------------------
# GET /oauth/login/workos/mobile
# ---------------------------------------------------------------------------


class TestLoginWorkOSMobile:
    """GET /api/v1/oauth/login/workos/mobile"""

    async def test_login_mobile_uses_provided_redirect(self, client: AsyncClient) -> None:
        with (
            patch(f"{MODULE}.workos") as mock_workos,
            patch(f"{MODULE}.redis_cache") as mock_redis,
            patch(f"{MODULE}.log") as mock_log,
        ):
            mock_workos.user_management.get_authorization_url.return_value = (
                "https://workos.example.com/mobile"
            )
            mock_redis.client = AsyncMock()
            response = await client.get(
                f"{OAUTH_BASE}/login/workos/mobile",
                params={"redirect_uri": "gaiamobile://custom/cb"},
            )

        assert response.status_code == 200
        assert response.json() == {"url": "https://workos.example.com/mobile"}
        state = mock_workos.user_management.get_authorization_url.call_args.kwargs["state"]
        assert len(state) == 43
        mock_workos.user_management.get_authorization_url.assert_called_once_with(
            provider="authkit",
            redirect_uri=settings.WORKOS_MOBILE_REDIRECT_URI,
            state=state,
        )
        mock_redis.client.setex.assert_awaited_once_with(
            f"mobile_redirect:{state}", MOBILE_REDIRECT_TTL, "gaiamobile://custom/cb"
        )
        mock_log.set.assert_called_once_with(
            oauth_flow_type=OAUTH_FLOW_MOBILE,
            oauth={"operation": "authorize", "provider": "authkit"},
        )
        mock_log.info.assert_called_once_with(
            f"{LogTag.OAUTH} Mobile OAuth started",
            redirect_uri="gaiamobile://custom/cb",
            state_prefix=state[:8],
        )

    async def test_login_mobile_defaults_to_mobile_deep_link(self, client: AsyncClient) -> None:
        with (
            patch(f"{MODULE}.workos") as mock_workos,
            patch(f"{MODULE}.redis_cache") as mock_redis,
        ):
            mock_workos.user_management.get_authorization_url.return_value = (
                "https://workos.example.com/mobile"
            )
            mock_redis.client = AsyncMock()
            response = await client.get(f"{OAUTH_BASE}/login/workos/mobile")

        assert response.status_code == 200
        assert response.json() == {"url": "https://workos.example.com/mobile"}
        state = mock_workos.user_management.get_authorization_url.call_args.kwargs["state"]
        mock_redis.client.setex.assert_awaited_once_with(
            f"mobile_redirect:{state}", MOBILE_REDIRECT_TTL, MOBILE_DEEP_LINK
        )

    async def test_login_google_mobile_uses_google_provider(self, client: AsyncClient) -> None:
        with (
            patch(f"{MODULE}.workos") as mock_workos,
            patch(f"{MODULE}.redis_cache") as mock_redis,
            patch(f"{MODULE}.log") as mock_log,
        ):
            mock_workos.user_management.get_authorization_url.return_value = (
                "https://accounts.google.com/o/oauth2/auth"
            )
            mock_redis.client = AsyncMock()
            response = await client.get(f"{OAUTH_BASE}/login/google/mobile")

        assert response.status_code == 200
        assert response.json() == {"url": "https://accounts.google.com/o/oauth2/auth"}
        state = mock_workos.user_management.get_authorization_url.call_args.kwargs["state"]
        assert len(state) == 43
        mock_workos.user_management.get_authorization_url.assert_called_once_with(
            provider="GoogleOAuth",
            redirect_uri=settings.WORKOS_MOBILE_REDIRECT_URI,
            state=state,
        )
        mock_redis.client.setex.assert_awaited_once_with(
            f"mobile_redirect:{state}", MOBILE_REDIRECT_TTL, MOBILE_DEEP_LINK
        )
        mock_log.set.assert_called_once_with(
            oauth_flow_type=OAUTH_FLOW_MOBILE,
            oauth={"operation": "authorize", "provider": "GoogleOAuth"},
        )
        mock_log.info.assert_called_once_with(
            f"{LogTag.OAUTH} Mobile Google OAuth started",
            redirect_uri=MOBILE_DEEP_LINK,
            state_prefix=state[:8],
        )


# ---------------------------------------------------------------------------
# GET /oauth/workos/mobile/callback
# ---------------------------------------------------------------------------


class TestWorkOSMobileCallback:
    """GET /api/v1/oauth/workos/mobile/callback"""

    async def test_mobile_callback_success(self, client: AsyncClient) -> None:
        with (
            patch(f"{MODULE}.store_user_info", new_callable=AsyncMock) as mock_store,
            patch(f"{MODULE}.workos") as mock_workos,
            patch(f"{MODULE}.redis_cache") as mock_redis,
            patch(f"{MODULE}.log") as mock_log,
        ):
            mock_redis.client = AsyncMock()
            mock_redis.client.get.return_value = "gaiamobile://custom/cb"
            mock_workos.user_management.authenticate_with_code.return_value = _mock_auth_response(
                picture_url="http://pic.example/p.png",
                sealed_session=_TOKEN_WITH_SPECIAL_CHARS,
            )
            mock_store.return_value = ("user_123", False)
            response = await client.get(
                f"{OAUTH_BASE}/workos/mobile/callback",
                params={"code": "authcode", "state": "xyz"},
                follow_redirects=False,
            )

        assert response.status_code == 307
        assert response.headers["location"] == (
            f"gaiamobile://custom/cb?token={quote(_TOKEN_WITH_SPECIAL_CHARS, safe='')}"
        )
        mock_workos.user_management.authenticate_with_code.assert_called_once_with(
            code="authcode",
            session={"seal_session": True, "cookie_password": settings.WORKOS_COOKIE_PASSWORD},
        )
        mock_redis.client.get.assert_awaited_once_with("mobile_redirect:xyz")
        mock_redis.client.delete.assert_awaited_once_with("mobile_redirect:xyz")
        mock_store.assert_awaited_once_with(
            "Test User", "test@example.com", "http://pic.example/p.png"
        )
        mock_log.set.assert_any_call(
            oauth_flow_type=OAUTH_FLOW_MOBILE,
            oauth={"operation": "callback", "provider": "authkit"},
        )
        mock_log.set.assert_any_call(fields_extracted=["email", "name", "picture"])
        mock_log.set.assert_any_call(user_id="user_123", is_new_user=False)
        mock_log.info.assert_called_once_with(
            f"{LogTag.OAUTH} Mobile OAuth callback", redirect_uri="gaiamobile://custom/cb"
        )
        mock_log.audit.assert_called_once_with(
            "login succeeded",
            actor="user_123",
            flow="mobile",
            provider="authkit",
            is_new_user=False,
        )

    async def test_mobile_callback_falls_back_to_access_token(self, client: AsyncClient) -> None:
        with (
            patch(f"{MODULE}.store_user_info", new_callable=AsyncMock) as mock_store,
            patch(f"{MODULE}.workos") as mock_workos,
            patch(f"{MODULE}.redis_cache") as mock_redis,
        ):
            mock_redis.client = AsyncMock()
            mock_redis.client.get.return_value = "gaiamobile://custom/cb"
            mock_workos.user_management.authenticate_with_code.return_value = _mock_auth_response(
                sealed_session=None, access_token="acc+token/1"
            )
            mock_store.return_value = ("user_123", False)
            response = await client.get(
                f"{OAUTH_BASE}/workos/mobile/callback",
                params={"code": "authcode", "state": "xyz"},
                follow_redirects=False,
            )

        assert response.status_code == 307
        assert response.headers["location"] == (
            f"gaiamobile://custom/cb?token={quote('acc+token/1', safe='')}"
        )

    async def test_mobile_callback_defaults_redirect_when_nothing_stored(
        self, client: AsyncClient
    ) -> None:
        with (
            patch(f"{MODULE}.store_user_info", new_callable=AsyncMock) as mock_store,
            patch(f"{MODULE}.workos") as mock_workos,
            patch(f"{MODULE}.redis_cache") as mock_redis,
            patch(f"{MODULE}.log") as mock_log,
        ):
            mock_redis.client = AsyncMock()
            mock_redis.client.get.return_value = None
            mock_workos.user_management.authenticate_with_code.return_value = _mock_auth_response()
            mock_store.return_value = ("user_123", False)
            response = await client.get(
                f"{OAUTH_BASE}/workos/mobile/callback",
                params={"code": "authcode", "state": "xyz"},
                follow_redirects=False,
            )

        assert response.status_code == 307
        assert response.headers["location"] == (
            f"{MOBILE_DEEP_LINK}?token={quote('sealed_token_abc', safe='')}"
        )
        mock_redis.client.delete.assert_not_awaited()
        mock_log.warning.assert_called_once_with(
            f"{LogTag.OAUTH} No stored redirect URI for state, using default",
            redirect_uri=MOBILE_DEEP_LINK,
        )

    async def test_mobile_callback_empty_names_are_folded_to_empty(
        self, client: AsyncClient
    ) -> None:
        with (
            patch(f"{MODULE}.store_user_info", new_callable=AsyncMock) as mock_store,
            patch(f"{MODULE}.workos") as mock_workos,
            patch(f"{MODULE}.redis_cache") as mock_redis,
        ):
            mock_redis.client = AsyncMock()
            mock_redis.client.get.return_value = "gaiamobile://custom/cb"
            mock_workos.user_management.authenticate_with_code.return_value = _mock_auth_response(
                first_name="", last_name=""
            )
            mock_store.return_value = ("user_123", False)
            response = await client.get(
                f"{OAUTH_BASE}/workos/mobile/callback",
                params={"code": "authcode", "state": "xyz"},
                follow_redirects=False,
            )

        assert response.status_code == 307
        mock_store.assert_awaited_once_with("", "test@example.com", None)

    async def test_mobile_callback_without_state_skips_redis(self, client: AsyncClient) -> None:
        with (
            patch(f"{MODULE}.store_user_info", new_callable=AsyncMock) as mock_store,
            patch(f"{MODULE}.workos") as mock_workos,
            patch(f"{MODULE}.redis_cache") as mock_redis,
        ):
            mock_redis.client = AsyncMock()
            mock_workos.user_management.authenticate_with_code.return_value = _mock_auth_response()
            mock_store.return_value = ("user_123", False)
            response = await client.get(
                f"{OAUTH_BASE}/workos/mobile/callback",
                params={"code": "authcode"},
                follow_redirects=False,
            )

        assert response.status_code == 307
        assert response.headers["location"] == (
            f"{MOBILE_DEEP_LINK}?token={quote('sealed_token_abc', safe='')}"
        )
        mock_redis.client.get.assert_not_awaited()
        mock_redis.client.delete.assert_not_awaited()

    async def test_mobile_callback_no_code(self, client: AsyncClient) -> None:
        with (
            patch(f"{MODULE}.workos") as mock_workos,
            patch(f"{MODULE}.redis_cache") as mock_redis,
            patch(f"{MODULE}.log") as mock_log,
        ):
            mock_redis.client = AsyncMock()
            mock_redis.client.get.return_value = "gaiamobile://custom/cb"
            response = await client.get(
                f"{OAUTH_BASE}/workos/mobile/callback",
                params={"state": "xyz"},
                follow_redirects=False,
            )

        assert response.status_code == 307
        assert response.headers["location"] == "gaiamobile://custom/cb?error=missing_code"
        mock_workos.user_management.authenticate_with_code.assert_not_called()
        mock_redis.client.delete.assert_awaited_once_with("mobile_redirect:xyz")
        mock_log.error.assert_called_once_with(
            f"{LogTag.OAUTH} No authorization code received from WorkOS (mobile)",
            failure_reason="missing_code",
        )

    async def test_mobile_callback_http_error_redirects_with_detail(
        self, client: AsyncClient
    ) -> None:
        with (
            patch(f"{MODULE}.store_user_info", new_callable=AsyncMock) as mock_store,
            patch(f"{MODULE}.workos") as mock_workos,
            patch(f"{MODULE}.redis_cache") as mock_redis,
            patch(f"{MODULE}.log") as mock_log,
        ):
            mock_redis.client = AsyncMock()
            mock_redis.client.get.return_value = "gaiamobile://custom/cb"
            mock_workos.user_management.authenticate_with_code.return_value = _mock_auth_response()
            mock_store.side_effect = HTTPException(status_code=400, detail="Email is required")
            response = await client.get(
                f"{OAUTH_BASE}/workos/mobile/callback",
                params={"code": "authcode", "state": "xyz"},
                follow_redirects=False,
            )

        assert response.status_code == 307
        assert response.headers["location"] == "gaiamobile://custom/cb?error=Email%20is%20required"
        mock_log.error.assert_called_once_with(
            f"{LogTag.OAUTH} HTTP error during WorkOS mobile auth",
            error_type="HTTPException",
            error="Email is required",
            status_code=400,
        )

    async def test_mobile_callback_unexpected_error_redirects_to_workos(
        self, client: AsyncClient
    ) -> None:
        with (
            patch(f"{MODULE}.store_user_info", new_callable=AsyncMock),
            patch(f"{MODULE}.workos") as mock_workos,
            patch(f"{MODULE}.redis_cache") as mock_redis,
            patch(f"{MODULE}.log") as mock_log,
        ):
            mock_redis.client = AsyncMock()
            mock_redis.client.get.return_value = "gaiamobile://custom/cb"
            mock_workos.user_management.authenticate_with_code.side_effect = Exception("boom")
            response = await client.get(
                f"{OAUTH_BASE}/workos/mobile/callback",
                params={"code": "authcode", "state": "xyz"},
                follow_redirects=False,
            )

        assert response.status_code == 307
        assert response.headers["location"] == (
            f"{settings.WORKOS_MOBILE_REDIRECT_URI}?error=server_error"
        )
        mock_log.error.assert_called_once_with(
            f"{LogTag.OAUTH} Unexpected error during WorkOS mobile callback",
            error_type="Exception",
            error="boom",
        )


# ---------------------------------------------------------------------------
# GET /oauth/login/workos/desktop
# ---------------------------------------------------------------------------


class TestLoginWorkOSDesktop:
    """GET /api/v1/oauth/login/workos/desktop"""

    async def test_login_desktop_redirects_to_workos(self, client: AsyncClient) -> None:
        with (
            patch(f"{MODULE}.workos") as mock_workos,
            patch(f"{MODULE}.log") as mock_log,
        ):
            mock_workos.user_management.get_authorization_url.return_value = (
                "https://workos.example.com/desktop"
            )
            response = await client.get(
                f"{OAUTH_BASE}/login/workos/desktop", follow_redirects=False
            )

        assert response.status_code == 307
        assert response.headers["location"] == "https://workos.example.com/desktop"
        mock_workos.user_management.get_authorization_url.assert_called_once_with(
            provider="authkit",
            redirect_uri=settings.WORKOS_DESKTOP_REDIRECT_URI,
        )
        mock_log.set.assert_called_once_with(
            oauth_flow_type=OAUTH_FLOW_DESKTOP,
            oauth={"operation": "authorize", "provider": "authkit"},
        )


# ---------------------------------------------------------------------------
# GET /oauth/workos/desktop/callback
# ---------------------------------------------------------------------------


class TestWorkOSDesktopCallback:
    """GET /api/v1/oauth/workos/desktop/callback"""

    async def test_desktop_callback_success(self, client: AsyncClient) -> None:
        with (
            patch(f"{MODULE}.store_user_info", new_callable=AsyncMock) as mock_store,
            patch(f"{MODULE}.workos") as mock_workos,
            patch(f"{MODULE}.log") as mock_log,
        ):
            mock_workos.user_management.authenticate_with_code.return_value = _mock_auth_response(
                sealed_session=_TOKEN_WITH_SPECIAL_CHARS,
                picture_url="http://pic.example/p.png",
            )
            mock_store.return_value = ("user_123", False)
            response = await client.get(
                f"{OAUTH_BASE}/workos/desktop/callback",
                params={"code": "authcode"},
                follow_redirects=False,
            )

        assert response.status_code == 307
        assert response.headers["location"] == (
            f"{DESKTOP_DEEP_LINK}?token={quote(_TOKEN_WITH_SPECIAL_CHARS, safe='')}"
        )
        mock_workos.user_management.authenticate_with_code.assert_called_once_with(
            code="authcode",
            session={"seal_session": True, "cookie_password": settings.WORKOS_COOKIE_PASSWORD},
        )
        mock_store.assert_awaited_once_with(
            "Test User", "test@example.com", "http://pic.example/p.png"
        )
        mock_log.set.assert_any_call(
            oauth_flow_type=OAUTH_FLOW_DESKTOP,
            oauth={"operation": "callback", "provider": "authkit"},
        )
        mock_log.set.assert_any_call(fields_extracted=["email", "name", "picture"])
        mock_log.set.assert_any_call(user_id="user_123", is_new_user=False)
        mock_log.audit.assert_called_once_with(
            "login succeeded",
            actor="user_123",
            flow="desktop",
            provider="authkit",
            is_new_user=False,
        )

    async def test_desktop_callback_empty_names_are_folded_to_empty(
        self, client: AsyncClient
    ) -> None:
        with (
            patch(f"{MODULE}.store_user_info", new_callable=AsyncMock) as mock_store,
            patch(f"{MODULE}.workos") as mock_workos,
        ):
            mock_workos.user_management.authenticate_with_code.return_value = _mock_auth_response(
                first_name="", last_name=""
            )
            mock_store.return_value = ("user_123", False)
            response = await client.get(
                f"{OAUTH_BASE}/workos/desktop/callback",
                params={"code": "authcode"},
                follow_redirects=False,
            )

        assert response.status_code == 307
        mock_store.assert_awaited_once_with("", "test@example.com", None)

    async def test_desktop_callback_no_code(self, client: AsyncClient) -> None:
        with (
            patch(f"{MODULE}.workos") as mock_workos,
            patch(f"{MODULE}.log") as mock_log,
        ):
            response = await client.get(
                f"{OAUTH_BASE}/workos/desktop/callback", follow_redirects=False
            )

        assert response.status_code == 307
        assert response.headers["location"] == f"{DESKTOP_DEEP_LINK}?error=missing_code"
        mock_workos.user_management.authenticate_with_code.assert_not_called()
        mock_log.error.assert_called_once_with(
            f"{LogTag.OAUTH} No authorization code received from WorkOS (desktop)",
            failure_reason="missing_code",
        )

    async def test_desktop_callback_http_error_redirects_with_detail(
        self, client: AsyncClient
    ) -> None:
        with (
            patch(f"{MODULE}.store_user_info", new_callable=AsyncMock) as mock_store,
            patch(f"{MODULE}.workos") as mock_workos,
            patch(f"{MODULE}.log") as mock_log,
        ):
            mock_workos.user_management.authenticate_with_code.return_value = _mock_auth_response()
            mock_store.side_effect = HTTPException(status_code=400, detail="Email is required")
            response = await client.get(
                f"{OAUTH_BASE}/workos/desktop/callback",
                params={"code": "authcode"},
                follow_redirects=False,
            )

        assert response.status_code == 307
        assert response.headers["location"] == f"{DESKTOP_DEEP_LINK}?error=Email%20is%20required"
        mock_log.error.assert_called_once_with(
            f"{LogTag.OAUTH} HTTP error during WorkOS desktop auth",
            error_type="HTTPException",
            error="Email is required",
            status_code=400,
        )

    async def test_desktop_callback_unexpected_error(self, client: AsyncClient) -> None:
        with (
            patch(f"{MODULE}.store_user_info", new_callable=AsyncMock),
            patch(f"{MODULE}.workos") as mock_workos,
            patch(f"{MODULE}.log") as mock_log,
        ):
            mock_workos.user_management.authenticate_with_code.side_effect = Exception("boom")
            response = await client.get(
                f"{OAUTH_BASE}/workos/desktop/callback",
                params={"code": "authcode"},
                follow_redirects=False,
            )

        assert response.status_code == 307
        assert response.headers["location"] == f"{DESKTOP_DEEP_LINK}?error=server_error"
        mock_log.error.assert_called_once_with(
            f"{LogTag.OAUTH} Unexpected error during WorkOS desktop callback",
            error_type="Exception",
            error="boom",
        )


# ---------------------------------------------------------------------------
# GET /oauth/workos/callback
# ---------------------------------------------------------------------------


class TestWorkOSCallback:
    """GET /api/v1/oauth/workos/callback"""

    async def test_web_callback_success_sets_session_cookie(self, client: AsyncClient) -> None:
        with (
            patch(f"{MODULE}.store_user_info", new_callable=AsyncMock) as mock_store,
            patch(f"{MODULE}.workos") as mock_workos,
            patch(f"{MODULE}.redis_cache") as mock_redis,
            patch(f"{MODULE}.log") as mock_log,
        ):
            mock_redis.client = AsyncMock()
            mock_redis.client.get.return_value = None
            mock_workos.user_management.authenticate_with_code.return_value = _mock_auth_response(
                picture_url="http://pic.example/p.png",
                sealed_session=_TOKEN_WITH_SPECIAL_CHARS,
            )
            mock_store.return_value = ("user_123", False)
            response = await client.get(
                f"{OAUTH_BASE}/workos/callback",
                params={"code": "authcode", "state": "xyz"},
                follow_redirects=False,
            )

        assert response.status_code == 307
        assert response.headers["location"] == f"{settings.FRONTEND_URL}/redirect"
        set_cookie = response.headers["set-cookie"]
        assert set_cookie.startswith(f'{WOS_SESSION_COOKIE}="{_TOKEN_WITH_SPECIAL_CHARS}"')
        assert "HttpOnly" in set_cookie
        assert "SameSite=lax" in set_cookie
        assert ("Secure" in set_cookie) is (settings.ENV == "production")
        mock_workos.user_management.authenticate_with_code.assert_called_once_with(
            code="authcode",
            session={"seal_session": True, "cookie_password": settings.WORKOS_COOKIE_PASSWORD},
        )
        mock_redis.client.get.assert_awaited_once_with("oauth_return_url:xyz")
        mock_redis.client.delete.assert_not_awaited()
        mock_store.assert_awaited_once_with(
            "Test User", "test@example.com", "http://pic.example/p.png"
        )
        mock_log.set.assert_any_call(
            oauth_flow_type=OAUTH_FLOW_WEB,
            oauth={"operation": "callback", "provider": "authkit"},
        )
        mock_log.set.assert_any_call(fields_extracted=["email", "name", "picture"])
        mock_log.set.assert_any_call(user_id="user_123", is_new_user=False)
        mock_log.audit.assert_called_once_with(
            "login succeeded", actor="user_123", flow="web", provider="authkit", is_new_user=False
        )

    async def test_web_callback_empty_names_are_folded_to_empty(self, client: AsyncClient) -> None:
        with (
            patch(f"{MODULE}.store_user_info", new_callable=AsyncMock) as mock_store,
            patch(f"{MODULE}.workos") as mock_workos,
            patch(f"{MODULE}.redis_cache") as mock_redis,
        ):
            mock_redis.client = AsyncMock()
            mock_redis.client.get.return_value = None
            mock_workos.user_management.authenticate_with_code.return_value = _mock_auth_response(
                first_name="", last_name=""
            )
            mock_store.return_value = ("user_123", False)
            response = await client.get(
                f"{OAUTH_BASE}/workos/callback",
                params={"code": "authcode", "state": "xyz"},
                follow_redirects=False,
            )

        assert response.status_code == 307
        mock_store.assert_awaited_once_with("", "test@example.com", None)

    async def test_web_callback_cookie_is_secure_in_production(self, client: AsyncClient) -> None:
        with (
            patch(f"{MODULE}.store_user_info", new_callable=AsyncMock) as mock_store,
            patch(f"{MODULE}.workos") as mock_workos,
            patch(f"{MODULE}.redis_cache") as mock_redis,
            patch.object(settings, "ENV", "production"),
        ):
            mock_redis.client = AsyncMock()
            mock_redis.client.get.return_value = None
            mock_workos.user_management.authenticate_with_code.return_value = _mock_auth_response()
            mock_store.return_value = ("user_123", False)
            response = await client.get(
                f"{OAUTH_BASE}/workos/callback",
                params={"code": "authcode", "state": "xyz"},
                follow_redirects=False,
            )

        assert response.status_code == 307
        set_cookie = response.headers["set-cookie"]
        assert f"{WOS_SESSION_COOKIE}=sealed_token_abc" in set_cookie
        assert "Secure" in set_cookie
        assert "HttpOnly" in set_cookie
        assert "SameSite=lax" in set_cookie

    async def test_web_callback_with_safe_return_url(self, client: AsyncClient) -> None:
        with (
            patch(f"{MODULE}.store_user_info", new_callable=AsyncMock) as mock_store,
            patch(f"{MODULE}.workos") as mock_workos,
            patch(f"{MODULE}.redis_cache") as mock_redis,
        ):
            mock_redis.client = AsyncMock()
            mock_redis.client.get.return_value = "/settings"
            mock_workos.user_management.authenticate_with_code.return_value = _mock_auth_response()
            mock_store.return_value = ("user_123", False)
            response = await client.get(
                f"{OAUTH_BASE}/workos/callback",
                params={"code": "authcode", "state": "xyz"},
                follow_redirects=False,
            )

        assert response.status_code == 307
        assert response.headers["location"] == f"{settings.FRONTEND_URL}/settings"
        mock_redis.client.get.assert_awaited_once_with("oauth_return_url:xyz")
        mock_redis.client.delete.assert_awaited_once_with("oauth_return_url:xyz")
        assert f"{WOS_SESSION_COOKIE}=sealed_token_abc" in response.headers["set-cookie"]

    async def test_web_callback_unsafe_return_url_falls_back(self, client: AsyncClient) -> None:
        with (
            patch(f"{MODULE}.store_user_info", new_callable=AsyncMock) as mock_store,
            patch(f"{MODULE}.workos") as mock_workos,
            patch(f"{MODULE}.redis_cache") as mock_redis,
        ):
            mock_redis.client = AsyncMock()
            mock_redis.client.get.return_value = "https://evil.com/x"
            mock_workos.user_management.authenticate_with_code.return_value = _mock_auth_response()
            mock_store.return_value = ("user_123", False)
            response = await client.get(
                f"{OAUTH_BASE}/workos/callback",
                params={"code": "authcode", "state": "xyz"},
                follow_redirects=False,
            )

        assert response.status_code == 307
        assert response.headers["location"] == f"{settings.FRONTEND_URL}/redirect"
        mock_redis.client.delete.assert_awaited_once_with("oauth_return_url:xyz")

    async def test_web_callback_without_state_skips_redis(self, client: AsyncClient) -> None:
        with (
            patch(f"{MODULE}.store_user_info", new_callable=AsyncMock) as mock_store,
            patch(f"{MODULE}.workos") as mock_workos,
            patch(f"{MODULE}.redis_cache") as mock_redis,
        ):
            mock_redis.client = AsyncMock()
            mock_workos.user_management.authenticate_with_code.return_value = _mock_auth_response()
            mock_store.return_value = ("user_123", False)
            response = await client.get(
                f"{OAUTH_BASE}/workos/callback",
                params={"code": "authcode"},
                follow_redirects=False,
            )

        assert response.status_code == 307
        assert response.headers["location"] == f"{settings.FRONTEND_URL}/redirect"
        mock_redis.client.get.assert_not_awaited()

    async def test_web_callback_no_code(self, client: AsyncClient) -> None:
        with (
            patch(f"{MODULE}.workos") as mock_workos,
            patch(f"{MODULE}.redis_cache") as mock_redis,
            patch(f"{MODULE}.log") as mock_log,
        ):
            mock_redis.client = AsyncMock()
            mock_redis.client.get.return_value = None
            response = await client.get(
                f"{OAUTH_BASE}/workos/callback",
                params={"state": "xyz"},
                follow_redirects=False,
            )

        assert response.status_code == 307
        assert response.headers["location"] == f"{settings.FRONTEND_URL}/login?error=missing_code"
        mock_workos.user_management.authenticate_with_code.assert_not_called()
        mock_redis.client.get.assert_awaited_once_with("oauth_return_url:xyz")
        mock_redis.client.delete.assert_not_awaited()
        mock_log.error.assert_called_once_with(
            f"{LogTag.OAUTH} No authorization code received from WorkOS",
            failure_reason="missing_code",
        )

    async def test_web_callback_http_error_redirects_with_detail(self, client: AsyncClient) -> None:
        with (
            patch(f"{MODULE}.store_user_info", new_callable=AsyncMock) as mock_store,
            patch(f"{MODULE}.workos") as mock_workos,
            patch(f"{MODULE}.redis_cache") as mock_redis,
            patch(f"{MODULE}.log") as mock_log,
        ):
            mock_redis.client = AsyncMock()
            mock_redis.client.get.return_value = None
            mock_workos.user_management.authenticate_with_code.return_value = _mock_auth_response()
            mock_store.side_effect = HTTPException(status_code=400, detail="Email is required")
            response = await client.get(
                f"{OAUTH_BASE}/workos/callback",
                params={"code": "authcode", "state": "xyz"},
                follow_redirects=False,
            )

        assert response.status_code == 307
        assert response.headers["location"] == (
            f"{settings.FRONTEND_URL}/login?error=Email%20is%20required"
        )
        mock_log.error.assert_called_once_with(
            f"{LogTag.OAUTH} HTTP error during WorkOS",
            error_type="HTTPException",
            error="Email is required",
            status_code=400,
        )

    async def test_web_callback_unexpected_error(self, client: AsyncClient) -> None:
        with (
            patch(f"{MODULE}.store_user_info", new_callable=AsyncMock),
            patch(f"{MODULE}.workos") as mock_workos,
            patch(f"{MODULE}.redis_cache") as mock_redis,
            patch(f"{MODULE}.log") as mock_log,
        ):
            mock_redis.client = AsyncMock()
            mock_redis.client.get.return_value = None
            mock_workos.user_management.authenticate_with_code.side_effect = Exception("boom")
            response = await client.get(
                f"{OAUTH_BASE}/workos/callback",
                params={"code": "authcode", "state": "xyz"},
                follow_redirects=False,
            )

        assert response.status_code == 307
        assert response.headers["location"] == (f"{settings.FRONTEND_URL}/login?error=server_error")
        mock_log.error.assert_called_once_with(
            f"{LogTag.OAUTH} Unexpected error during WorkOS callback",
            error_type="Exception",
            error="boom",
        )

    async def test_web_callback_cookie_falls_back_to_access_token(
        self, client: AsyncClient
    ) -> None:
        with (
            patch(f"{MODULE}.store_user_info", new_callable=AsyncMock) as mock_store,
            patch(f"{MODULE}.workos") as mock_workos,
            patch(f"{MODULE}.redis_cache") as mock_redis,
        ):
            mock_redis.client = AsyncMock()
            mock_redis.client.get.return_value = None
            mock_workos.user_management.authenticate_with_code.return_value = _mock_auth_response(
                sealed_session=None, access_token="acc+token/1"
            )
            mock_store.return_value = ("user_123", False)
            response = await client.get(
                f"{OAUTH_BASE}/workos/callback",
                params={"code": "authcode", "state": "xyz"},
                follow_redirects=False,
            )

        assert response.status_code == 307
        assert response.headers["set-cookie"].startswith(f'{WOS_SESSION_COOKIE}="acc+token/1"')


# ---------------------------------------------------------------------------
# GET /oauth/composio/callback
# ---------------------------------------------------------------------------


class TestComposioCallback:
    """GET /api/v1/oauth/composio/callback"""

    @staticmethod
    def _make_account(user_id: str | None = "uid1") -> MagicMock:
        account = MagicMock()
        account.auth_config.id = "config1"
        account.user_id = user_id
        return account

    @staticmethod
    def _make_integration() -> MagicMock:
        integration = MagicMock()
        integration.id = "gmail"
        integration.provider = "google"
        return integration

    async def test_composio_callback_success(self, client: AsyncClient) -> None:
        with (
            patch(f"{MODULE}.handle_oauth_connection", new_callable=AsyncMock) as mock_handle,
            patch(f"{MODULE}.get_integration_by_config") as mock_config,
            patch(f"{MODULE}.get_composio_service") as mock_composio,
            patch(
                f"{MODULE}.validate_and_consume_oauth_state", new_callable=AsyncMock
            ) as mock_state,
            patch(f"{MODULE}.log") as mock_log,
        ):
            mock_state.return_value = {"redirect_path": "/integrations", "user_id": "uid1"}
            mock_composio.return_value.get_connected_account_by_id.return_value = (
                self._make_account()
            )
            integration = self._make_integration()
            mock_config.return_value = integration
            redirect_path = "/integrations"
            response = await client.get(
                f"{OAUTH_BASE}/composio/callback",
                params={"status": "success", "state": "tok", "connectedAccountId": "acc1"},
                follow_redirects=False,
            )

        assert response.status_code == 307
        assert response.headers["location"] == (
            f"{settings.FRONTEND_URL}/{redirect_path}?oauth_success=true&integration=gmail"
        )
        mock_state.assert_awaited_once_with("tok")
        mock_composio.return_value.get_connected_account_by_id.assert_called_once_with("acc1")
        mock_config.assert_called_once_with("config1")
        mock_handle.assert_awaited_once()
        handle_kwargs = mock_handle.await_args.kwargs
        assert handle_kwargs["user_id"] == "uid1"
        assert handle_kwargs["integration_config"] is integration
        assert isinstance(handle_kwargs["background_tasks"], BackgroundTasks)
        mock_log.set.assert_any_call(user={"id": "uid1"})
        mock_log.set_ns.assert_called_once_with("oauth", provider="google", integration_id="gmail")
        mock_log.info.assert_called_once_with(
            f"{LogTag.OAUTH} Composio connection successful",
            user_id="uid1",
            integration_id="gmail",
            connected_account_id="acc1",
        )
        mock_log.audit.assert_called_once_with(
            "integration connected", actor="uid1", resource="gmail", provider="google"
        )

    async def test_composio_callback_success_keeps_existing_query(
        self, client: AsyncClient
    ) -> None:
        with (
            patch(f"{MODULE}.handle_oauth_connection", new_callable=AsyncMock),
            patch(f"{MODULE}.get_integration_by_config") as mock_config,
            patch(f"{MODULE}.get_composio_service") as mock_composio,
            patch(
                f"{MODULE}.validate_and_consume_oauth_state", new_callable=AsyncMock
            ) as mock_state,
        ):
            mock_state.return_value = {
                "redirect_path": "/integrations?tab=active",
                "user_id": "uid1",
            }
            mock_composio.return_value.get_connected_account_by_id.return_value = (
                self._make_account()
            )
            mock_config.return_value = self._make_integration()
            redirect_path = "/integrations?tab=active"
            response = await client.get(
                f"{OAUTH_BASE}/composio/callback",
                params={"status": "success", "state": "tok", "connectedAccountId": "acc1"},
                follow_redirects=False,
            )

        assert response.status_code == 307
        assert response.headers["location"] == (
            f"{settings.FRONTEND_URL}/{redirect_path}&oauth_success=true&integration=gmail"
        )

    async def test_composio_callback_invalid_state(self, client: AsyncClient) -> None:
        with (
            patch(
                f"{MODULE}.validate_and_consume_oauth_state", new_callable=AsyncMock
            ) as mock_state,
            patch(f"{MODULE}.log") as mock_log,
        ):
            mock_state.return_value = None
            response = await client.get(
                f"{OAUTH_BASE}/composio/callback",
                params={"status": "success", "state": "1234567890"},
                follow_redirects=False,
            )

        assert response.status_code == 307
        assert response.headers["location"] == (
            f"{settings.FRONTEND_URL}/redirect?oauth_error=invalid_state"
        )
        mock_state.assert_awaited_once_with("1234567890")
        mock_log.error.assert_called_once_with(
            f"{LogTag.OAUTH} Invalid OAuth state token", state_prefix="12345678"
        )

    async def test_composio_callback_failed_status(self, client: AsyncClient) -> None:
        with (
            patch(f"{MODULE}.handle_oauth_connection", new_callable=AsyncMock) as mock_handle,
            patch(f"{MODULE}.get_integration_by_config"),
            patch(f"{MODULE}.get_composio_service"),
            patch(
                f"{MODULE}.validate_and_consume_oauth_state", new_callable=AsyncMock
            ) as mock_state,
            patch(f"{MODULE}.log") as mock_log,
        ):
            mock_state.return_value = {"redirect_path": "/integrations", "user_id": "uid1"}
            response = await client.get(
                f"{OAUTH_BASE}/composio/callback",
                params={"status": "failed", "state": "tok", "connectedAccountId": "acc1"},
                follow_redirects=False,
            )

        assert response.status_code == 307
        assert response.headers["location"] == (
            f"{settings.FRONTEND_URL}/integrations?oauth_error=failed"
        )
        mock_handle.assert_not_awaited()
        mock_log.warning.assert_called_once_with(
            f"{LogTag.OAUTH} Composio connection failed",
            status="failed",
            error=None,
            connected_account_id="acc1",
        )

    async def test_composio_callback_access_denied_is_cancelled(self, client: AsyncClient) -> None:
        with (
            patch(f"{MODULE}.handle_oauth_connection", new_callable=AsyncMock) as mock_handle,
            patch(f"{MODULE}.get_integration_by_config"),
            patch(f"{MODULE}.get_composio_service"),
            patch(
                f"{MODULE}.validate_and_consume_oauth_state", new_callable=AsyncMock
            ) as mock_state,
            patch(f"{MODULE}.log") as mock_log,
        ):
            mock_state.return_value = {"redirect_path": "/integrations", "user_id": "uid1"}
            response = await client.get(
                f"{OAUTH_BASE}/composio/callback",
                params={
                    "status": "failed",
                    "state": "tok",
                    "connectedAccountId": "acc1",
                    "error": "access_denied",
                },
                follow_redirects=False,
            )

        assert response.status_code == 307
        assert response.headers["location"] == (
            f"{settings.FRONTEND_URL}/integrations?oauth_error=cancelled"
        )
        mock_handle.assert_not_awaited()
        mock_log.warning.assert_called_once_with(
            f"{LogTag.OAUTH} Composio connection failed",
            status="failed",
            error="access_denied",
            connected_account_id="acc1",
        )

    async def test_composio_callback_missing_connected_account_id(
        self, client: AsyncClient
    ) -> None:
        with (
            patch(f"{MODULE}.get_composio_service") as mock_composio,
            patch(
                f"{MODULE}.validate_and_consume_oauth_state", new_callable=AsyncMock
            ) as mock_state,
            patch(f"{MODULE}.log") as mock_log,
        ):
            mock_state.return_value = {"redirect_path": "/integrations", "user_id": "uid1"}
            response = await client.get(
                f"{OAUTH_BASE}/composio/callback",
                params={"status": "success", "state": "tok"},
                follow_redirects=False,
            )

        assert response.status_code == 307
        assert response.headers["location"] == (
            f"{settings.FRONTEND_URL}/integrations?oauth_error=failed"
        )
        mock_composio.return_value.get_connected_account_by_id.assert_not_called()
        mock_log.error.assert_called_once_with(
            f"{LogTag.OAUTH} Connected account ID missing for successful connection",
            failure_reason="missing_connected_account_id",
            status="success",
        )

    async def test_composio_callback_account_not_found(self, client: AsyncClient) -> None:
        with (
            patch(f"{MODULE}.get_composio_service") as mock_composio,
            patch(
                f"{MODULE}.validate_and_consume_oauth_state", new_callable=AsyncMock
            ) as mock_state,
            patch(f"{MODULE}.log") as mock_log,
        ):
            mock_state.return_value = {"redirect_path": "/integrations", "user_id": "uid1"}
            mock_composio.return_value.get_connected_account_by_id.return_value = None
            response = await client.get(
                f"{OAUTH_BASE}/composio/callback",
                params={"status": "success", "state": "tok", "connectedAccountId": "acc1"},
                follow_redirects=False,
            )

        assert response.status_code == 307
        assert response.headers["location"] == (
            f"{settings.FRONTEND_URL}/redirect?oauth_error=failed"
        )
        mock_log.error.assert_called_once_with(
            f"{LogTag.OAUTH} Connected account not found", connected_account_id="acc1"
        )

    async def test_composio_callback_missing_user_id(self, client: AsyncClient) -> None:
        with (
            patch(f"{MODULE}.get_composio_service") as mock_composio,
            patch(
                f"{MODULE}.validate_and_consume_oauth_state", new_callable=AsyncMock
            ) as mock_state,
            patch(f"{MODULE}.log") as mock_log,
        ):
            mock_state.return_value = {"redirect_path": "/integrations", "user_id": "uid1"}
            mock_composio.return_value.get_connected_account_by_id.return_value = (
                self._make_account(user_id=None)
            )
            response = await client.get(
                f"{OAUTH_BASE}/composio/callback",
                params={"status": "success", "state": "tok", "connectedAccountId": "acc1"},
                follow_redirects=False,
            )

        assert response.status_code == 307
        assert response.headers["location"] == (
            f"{settings.FRONTEND_URL}/redirect?oauth_error=failed"
        )
        mock_log.error.assert_called_once_with(
            f"{LogTag.OAUTH} User ID missing for account", connected_account_id="acc1"
        )

    async def test_composio_callback_integration_not_found(self, client: AsyncClient) -> None:
        with (
            patch(f"{MODULE}.handle_oauth_connection", new_callable=AsyncMock) as mock_handle,
            patch(f"{MODULE}.get_integration_by_config") as mock_config,
            patch(f"{MODULE}.get_composio_service") as mock_composio,
            patch(
                f"{MODULE}.validate_and_consume_oauth_state", new_callable=AsyncMock
            ) as mock_state,
            patch(f"{MODULE}.log") as mock_log,
        ):
            mock_state.return_value = {"redirect_path": "/integrations", "user_id": "uid1"}
            mock_composio.return_value.get_connected_account_by_id.return_value = (
                self._make_account()
            )
            mock_config.return_value = None
            response = await client.get(
                f"{OAUTH_BASE}/composio/callback",
                params={"status": "success", "state": "tok", "connectedAccountId": "acc1"},
                follow_redirects=False,
            )

        assert response.status_code == 307
        assert response.headers["location"] == (
            f"{settings.FRONTEND_URL}/integrations?oauth_error=failed"
        )
        mock_handle.assert_not_awaited()
        mock_log.error.assert_called_once_with(
            f"{LogTag.OAUTH} Integration config not found",
            auth_config_id="config1",
            connected_account_id="acc1",
        )

    async def test_composio_callback_user_mismatch(self, client: AsyncClient) -> None:
        with (
            patch(f"{MODULE}.handle_oauth_connection", new_callable=AsyncMock) as mock_handle,
            patch(f"{MODULE}.get_integration_by_config") as mock_config,
            patch(f"{MODULE}.get_composio_service") as mock_composio,
            patch(
                f"{MODULE}.validate_and_consume_oauth_state", new_callable=AsyncMock
            ) as mock_state,
            patch(f"{MODULE}.log") as mock_log,
        ):
            mock_state.return_value = {"redirect_path": "/integrations", "user_id": "uid1"}
            mock_composio.return_value.get_connected_account_by_id.return_value = (
                self._make_account(user_id="other")
            )
            mock_config.return_value = self._make_integration()
            response = await client.get(
                f"{OAUTH_BASE}/composio/callback",
                params={"status": "success", "state": "tok", "connectedAccountId": "acc1"},
                follow_redirects=False,
            )

        assert response.status_code == 307
        assert response.headers["location"] == (
            f"{settings.FRONTEND_URL}/integrations?oauth_error=user_mismatch"
        )
        mock_handle.assert_not_awaited()
        mock_log.error.assert_called_once_with(
            f"{LogTag.OAUTH} User ID mismatch between state and account",
            state_user_id="uid1",
            account_user_id="other",
            connected_account_id="acc1",
        )

    async def test_composio_callback_unexpected_error(self, client: AsyncClient) -> None:
        with (
            patch(f"{MODULE}.get_composio_service") as mock_composio,
            patch(
                f"{MODULE}.validate_and_consume_oauth_state", new_callable=AsyncMock
            ) as mock_state,
            patch(f"{MODULE}.log") as mock_log,
        ):
            mock_state.return_value = {"redirect_path": "/integrations", "user_id": "uid1"}
            mock_composio.return_value.get_connected_account_by_id.side_effect = Exception("boom")
            response = await client.get(
                f"{OAUTH_BASE}/composio/callback",
                params={"status": "success", "state": "tok", "connectedAccountId": "acc1"},
                follow_redirects=False,
            )

        assert response.status_code == 307
        assert response.headers["location"] == (
            f"{settings.FRONTEND_URL}/redirect?oauth_error=failed"
        )
        mock_log.error.assert_called_once_with(
            f"{LogTag.OAUTH} Unexpected error in Composio callback",
            connected_account_id="acc1",
            error_type="Exception",
            error="boom",
            exc_info=True,
        )
