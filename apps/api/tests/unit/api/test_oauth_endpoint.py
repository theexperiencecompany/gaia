"""Unit tests for OAuth API endpoints.

Tests the OAuth endpoints with mocked WorkOS client and service layer
to verify routing, status codes, redirects, and cookie handling.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

OAUTH_BASE = "/api/v1/oauth"


def _mock_auth_response(
    email: str = "test@example.com",
    first_name: str = "Test",
    last_name: str = "User",
    picture_url: str | None = None,
    sealed_session: str = "sealed_token_abc",
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


@pytest.mark.unit
class TestClientMetadata:
    """GET /api/v1/oauth/client-metadata.json"""

    @patch(
        "app.api.v1.endpoints.oauth.get_api_base_url",
        return_value="https://api.test.com",
    )
    async def test_client_metadata_success(
        self, mock_base: MagicMock, client: AsyncClient
    ):
        response = await client.get(f"{OAUTH_BASE}/client-metadata.json")
        assert response.status_code == 200
        data = response.json()
        assert data["client_name"] == "GAIA"
        assert "client_id" in data
        assert "redirect_uris" in data
        assert data["token_endpoint_auth_method"] == "none"


# ---------------------------------------------------------------------------
# GET /oauth/login/workos
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestLoginWorkOS:
    """GET /api/v1/oauth/login/workos"""

    @patch("app.api.v1.endpoints.oauth.redis_cache")
    @patch("app.api.v1.endpoints.oauth.workos")
    async def test_login_workos_redirect(
        self,
        mock_workos: MagicMock,
        mock_redis: MagicMock,
        client: AsyncClient,
    ):
        mock_workos.user_management.get_authorization_url.return_value = (
            "https://workos.example.com/auth"
        )
        mock_redis.client = AsyncMock()
        response = await client.get(
            f"{OAUTH_BASE}/login/workos", follow_redirects=False
        )
        assert response.status_code == 307
        assert "workos.example.com" in response.headers["location"]

    @patch("app.api.v1.endpoints.oauth.redis_cache")
    @patch("app.api.v1.endpoints.oauth.workos")
    async def test_login_workos_with_return_url(
        self,
        mock_workos: MagicMock,
        mock_redis: MagicMock,
        client: AsyncClient,
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
        mock_redis.client.setex.assert_awaited_once()


# ---------------------------------------------------------------------------
# GET /oauth/login/workos/mobile
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestLoginWorkOSMobile:
    """GET /api/v1/oauth/login/workos/mobile"""

    @patch("app.api.v1.endpoints.oauth.workos")
    @patch("app.api.v1.endpoints.oauth._store_mobile_redirect", new_callable=AsyncMock)
    async def test_login_mobile_returns_url(
        self,
        mock_store: AsyncMock,
        mock_workos: MagicMock,
        client: AsyncClient,
    ):
        mock_workos.user_management.get_authorization_url.return_value = (
            "https://workos.example.com/mobile"
        )
        response = await client.get(f"{OAUTH_BASE}/login/workos/mobile")
        assert response.status_code == 200
        data = response.json()
        assert "url" in data
        mock_store.assert_awaited_once()


# ---------------------------------------------------------------------------
# GET /oauth/workos/mobile/callback
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestWorkOSMobileCallback:
    """GET /api/v1/oauth/workos/mobile/callback"""

    @patch("app.api.v1.endpoints.oauth.store_user_info", new_callable=AsyncMock)
    @patch("app.api.v1.endpoints.oauth.workos")
    @patch(
        "app.api.v1.endpoints.oauth._get_and_delete_mobile_redirect",
        new_callable=AsyncMock,
    )
    async def test_mobile_callback_success(
        self,
        mock_redirect: AsyncMock,
        mock_workos: MagicMock,
        mock_store: AsyncMock,
        client: AsyncClient,
    ):
        mock_redirect.return_value = "gaiamobile://auth/callback"
        mock_workos.user_management.authenticate_with_code.return_value = (
            _mock_auth_response()
        )
        mock_store.return_value = (MagicMock(), False)
        response = await client.get(
            f"{OAUTH_BASE}/workos/mobile/callback?code=abc&state=xyz",
            follow_redirects=False,
        )
        assert response.status_code == 307
        assert "token=" in response.headers["location"]

    @patch(
        "app.api.v1.endpoints.oauth._get_and_delete_mobile_redirect",
        new_callable=AsyncMock,
    )
    async def test_mobile_callback_no_code(
        self,
        mock_redirect: AsyncMock,
        client: AsyncClient,
    ):
        mock_redirect.return_value = "gaiamobile://auth/callback"
        response = await client.get(
            f"{OAUTH_BASE}/workos/mobile/callback?state=xyz",
            follow_redirects=False,
        )
        assert response.status_code == 307
        assert "error=missing_code" in response.headers["location"]

    @patch("app.api.v1.endpoints.oauth.store_user_info", new_callable=AsyncMock)
    @patch("app.api.v1.endpoints.oauth.workos")
    @patch(
        "app.api.v1.endpoints.oauth._get_and_delete_mobile_redirect",
        new_callable=AsyncMock,
    )
    async def test_mobile_callback_workos_error(
        self,
        mock_redirect: AsyncMock,
        mock_workos: MagicMock,
        mock_store: AsyncMock,
        client: AsyncClient,
    ):
        mock_redirect.return_value = "gaiamobile://auth/callback"
        mock_workos.user_management.authenticate_with_code.side_effect = Exception(
            "boom"
        )
        response = await client.get(
            f"{OAUTH_BASE}/workos/mobile/callback?code=abc&state=xyz",
            follow_redirects=False,
        )
        assert response.status_code == 307
        assert "error=" in response.headers["location"]


# ---------------------------------------------------------------------------
# GET /oauth/login/workos/desktop
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestLoginWorkOSDesktop:
    """GET /api/v1/oauth/login/workos/desktop"""

    @patch("app.api.v1.endpoints.oauth.workos")
    async def test_login_desktop_redirect(
        self,
        mock_workos: MagicMock,
        client: AsyncClient,
    ):
        mock_workos.user_management.get_authorization_url.return_value = (
            "https://workos.example.com/desktop"
        )
        response = await client.get(
            f"{OAUTH_BASE}/login/workos/desktop", follow_redirects=False
        )
        assert response.status_code == 307


# ---------------------------------------------------------------------------
# GET /oauth/workos/desktop/callback
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestWorkOSDesktopCallback:
    """GET /api/v1/oauth/workos/desktop/callback"""

    @patch("app.api.v1.endpoints.oauth.store_user_info", new_callable=AsyncMock)
    @patch("app.api.v1.endpoints.oauth.workos")
    async def test_desktop_callback_success(
        self,
        mock_workos: MagicMock,
        mock_store: AsyncMock,
        client: AsyncClient,
    ):
        mock_workos.user_management.authenticate_with_code.return_value = (
            _mock_auth_response()
        )
        mock_store.return_value = (MagicMock(), False)
        response = await client.get(
            f"{OAUTH_BASE}/workos/desktop/callback?code=abc",
            follow_redirects=False,
        )
        assert response.status_code == 307
        assert "gaia://auth/callback?token=" in response.headers["location"]

    async def test_desktop_callback_no_code(self, client: AsyncClient):
        response = await client.get(
            f"{OAUTH_BASE}/workos/desktop/callback",
            follow_redirects=False,
        )
        assert response.status_code == 307
        assert "error=missing_code" in response.headers["location"]

    @patch("app.api.v1.endpoints.oauth.store_user_info", new_callable=AsyncMock)
    @patch("app.api.v1.endpoints.oauth.workos")
    async def test_desktop_callback_exception(
        self,
        mock_workos: MagicMock,
        mock_store: AsyncMock,
        client: AsyncClient,
    ):
        mock_workos.user_management.authenticate_with_code.side_effect = Exception(
            "boom"
        )
        response = await client.get(
            f"{OAUTH_BASE}/workos/desktop/callback?code=abc",
            follow_redirects=False,
        )
        assert response.status_code == 307
        assert "error=server_error" in response.headers["location"]


# ---------------------------------------------------------------------------
# GET /oauth/workos/callback
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestWorkOSCallback:
    """GET /api/v1/oauth/workos/callback"""

    @patch("app.api.v1.endpoints.oauth.store_user_info", new_callable=AsyncMock)
    @patch("app.api.v1.endpoints.oauth.workos")
    @patch("app.api.v1.endpoints.oauth.redis_cache")
    async def test_web_callback_success(
        self,
        mock_redis: MagicMock,
        mock_workos: MagicMock,
        mock_store: AsyncMock,
        client: AsyncClient,
    ):
        mock_redis.client.get = AsyncMock(return_value=None)
        mock_workos.user_management.authenticate_with_code.return_value = (
            _mock_auth_response()
        )
        mock_store.return_value = (MagicMock(), False)
        response = await client.get(
            f"{OAUTH_BASE}/workos/callback?code=abc&state=xyz",
            follow_redirects=False,
        )
        assert response.status_code == 307
        assert "wos_session" in response.headers.get("set-cookie", "")

    @patch("app.api.v1.endpoints.oauth.redis_cache")
    async def test_web_callback_no_code(
        self, mock_redis: MagicMock, client: AsyncClient
    ):
        mock_redis.client.get = AsyncMock(return_value=None)
        response = await client.get(
            f"{OAUTH_BASE}/workos/callback?state=xyz",
            follow_redirects=False,
        )
        assert response.status_code == 307
        assert "error=missing_code" in response.headers["location"]

    @patch("app.api.v1.endpoints.oauth.store_user_info", new_callable=AsyncMock)
    @patch("app.api.v1.endpoints.oauth.workos")
    @patch("app.api.v1.endpoints.oauth.redis_cache")
    async def test_web_callback_with_return_url(
        self,
        mock_redis: MagicMock,
        mock_workos: MagicMock,
        mock_store: AsyncMock,
        client: AsyncClient,
    ):
        mock_redis.client.get = AsyncMock(return_value="/settings")
        mock_redis.client.delete = AsyncMock()
        mock_workos.user_management.authenticate_with_code.return_value = (
            _mock_auth_response()
        )
        mock_store.return_value = (MagicMock(), False)
        response = await client.get(
            f"{OAUTH_BASE}/workos/callback?code=abc&state=xyz",
            follow_redirects=False,
        )
        assert response.status_code == 307
        assert "/settings" in response.headers["location"]

    @patch("app.api.v1.endpoints.oauth.store_user_info", new_callable=AsyncMock)
    @patch("app.api.v1.endpoints.oauth.workos")
    @patch("app.api.v1.endpoints.oauth.redis_cache")
    async def test_web_callback_exception(
        self,
        mock_redis: MagicMock,
        mock_workos: MagicMock,
        mock_store: AsyncMock,
        client: AsyncClient,
    ):
        mock_redis.client.get = AsyncMock(return_value=None)
        mock_workos.user_management.authenticate_with_code.side_effect = Exception(
            "boom"
        )
        response = await client.get(
            f"{OAUTH_BASE}/workos/callback?code=abc&state=xyz",
            follow_redirects=False,
        )
        assert response.status_code == 307
        assert "error=server_error" in response.headers["location"]


# ---------------------------------------------------------------------------
# GET /oauth/composio/callback
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestComposioCallback:
    """GET /api/v1/oauth/composio/callback"""

    @patch("app.api.v1.endpoints.oauth.handle_oauth_connection", new_callable=AsyncMock)
    @patch("app.api.v1.endpoints.oauth.get_integration_by_config")
    @patch("app.api.v1.endpoints.oauth.get_composio_service")
    @patch(
        "app.api.v1.endpoints.oauth.validate_and_consume_oauth_state",
        new_callable=AsyncMock,
    )
    async def test_composio_callback_success(
        self,
        mock_state: AsyncMock,
        mock_composio: MagicMock,
        mock_config: MagicMock,
        mock_handle: AsyncMock,
        client: AsyncClient,
    ):
        mock_state.return_value = {
            "redirect_path": "/integrations",
            "user_id": "uid1",
        }
        account = MagicMock()
        account.auth_config.id = "config1"
        account.user_id = "uid1"
        mock_composio.return_value.get_connected_account_by_id.return_value = account
        integration = MagicMock()
        integration.id = "gmail"
        mock_config.return_value = integration
        response = await client.get(
            f"{OAUTH_BASE}/composio/callback?status=success&state=tok&connectedAccountId=acc1",
            follow_redirects=False,
        )
        assert response.status_code == 307
        assert "oauth_success=true" in response.headers["location"]

    @patch(
        "app.api.v1.endpoints.oauth.validate_and_consume_oauth_state",
        new_callable=AsyncMock,
    )
    async def test_composio_callback_invalid_state(
        self, mock_state: AsyncMock, client: AsyncClient
    ):
        mock_state.return_value = None
        response = await client.get(
            f"{OAUTH_BASE}/composio/callback?status=success&state=bad",
            follow_redirects=False,
        )
        assert response.status_code == 307
        assert "oauth_error=invalid_state" in response.headers["location"]

    @patch(
        "app.api.v1.endpoints.oauth.validate_and_consume_oauth_state",
        new_callable=AsyncMock,
    )
    async def test_composio_callback_failed_status(
        self, mock_state: AsyncMock, client: AsyncClient
    ):
        mock_state.return_value = {
            "redirect_path": "/integrations",
            "user_id": "uid1",
        }
        response = await client.get(
            f"{OAUTH_BASE}/composio/callback?status=failed&state=tok",
            follow_redirects=False,
        )
        assert response.status_code == 307
        assert "oauth_error=failed" in response.headers["location"]

    @patch(
        "app.api.v1.endpoints.oauth.validate_and_consume_oauth_state",
        new_callable=AsyncMock,
    )
    async def test_composio_callback_access_denied(
        self, mock_state: AsyncMock, client: AsyncClient
    ):
        mock_state.return_value = {
            "redirect_path": "/integrations",
            "user_id": "uid1",
        }
        response = await client.get(
            f"{OAUTH_BASE}/composio/callback?status=failed&state=tok&error=access_denied",
            follow_redirects=False,
        )
        assert response.status_code == 307
        assert "oauth_error=cancelled" in response.headers["location"]
