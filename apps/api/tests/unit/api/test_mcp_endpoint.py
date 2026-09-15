"""Unit tests for the MCP integration endpoints (app/api/v1/endpoints/mcp.py).

The OAuth callback route owns the redirect URLs: every test pins the exact
Location the browser is sent to. The MCPClient is the seam; the oauth_callback
service runs for real.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import AsyncClient
import pytest

from app.api.v1.endpoints.mcp import mcp_oauth_callback
from app.constants.log_tags import LogTag
from app.services.analytics_service import AnalyticsEvents
from tests.conftest import FAKE_USER
from tests.helpers import captured_wide_event

pytestmark = pytest.mark.unit

MCP_BASE = "/api/v1/mcp"
CALLBACK_URL = f"{MCP_BASE}/oauth/callback"
_MODULE = "app.api.v1.endpoints.mcp"
_CALLBACK = "app.services.mcp.oauth_callback"
USER_ID = FAKE_USER["user_id"]
REDIRECT_URI = "http://api/api/v1/mcp/oauth/callback"


def _mcp_client(*, retry_url: str | None = None) -> MagicMock:
    mcp_client = MagicMock()
    mcp_client.handle_oauth_callback = AsyncMock()
    mcp_client.build_scope_retry_url = AsyncMock(return_value=retry_url)
    mcp_client.token_store = MagicMock()
    mcp_client.token_store.clear_excluded_scopes = AsyncMock()
    return mcp_client


def _resolved(name: str = "GitHub") -> MagicMock:
    resolved = MagicMock()
    resolved.name = name
    return resolved


@contextmanager
def _callback_seams(
    mcp_client: MagicMock, resolved: MagicMock | None = None
) -> Iterator[dict[str, MagicMock]]:
    with (
        patch(f"{_MODULE}.get_mcp_client", new_callable=AsyncMock, return_value=mcp_client),
        patch(
            f"{_MODULE}.IntegrationResolver.resolve",
            new_callable=AsyncMock,
            return_value=resolved,
        ),
        patch(f"{_CALLBACK}.invalidate_user_integration_caches", new_callable=AsyncMock) as inv,
        patch(f"{_MODULE}.get_api_base_url", return_value="http://api"),
        patch(f"{_MODULE}.get_frontend_url", return_value="http://frontend"),
        patch(f"{_CALLBACK}.capture_context_event") as capture,
    ):
        yield {"invalidate": inv, "capture": capture}


class TestMCPOAuthCallback:
    """GET /api/v1/mcp/oauth/callback."""

    async def test_success_redirects_to_the_frontend_with_the_quoted_name(
        self, client: AsyncClient
    ) -> None:
        mcp_client = _mcp_client()

        with _callback_seams(mcp_client, _resolved("My MCP Server")) as seams:
            resp = await client.get(
                CALLBACK_URL,
                params={"state": "tok:github:/integrations", "code": "code1"},
                follow_redirects=False,
            )

        assert resp.status_code == 307
        assert (
            resp.headers["location"]
            == "http://frontend/integrations?id=github&status=connected&name=My%20MCP%20Server"
        )
        mcp_client.handle_oauth_callback.assert_awaited_once_with(
            integration_id="github",
            code="code1",
            state="tok",
            redirect_uri=REDIRECT_URI,
        )
        mcp_client.token_store.clear_excluded_scopes.assert_awaited_once_with("github")
        seams["invalidate"].assert_awaited_once_with(USER_ID)
        seams["capture"].assert_called_once_with(
            AnalyticsEvents.INTEGRATION_CONNECTED,
            {"integration_id": "github", "connection_method": "oauth"},
        )

    async def test_success_honours_the_redirect_path_carried_in_state(
        self, client: AsyncClient
    ) -> None:
        with _callback_seams(_mcp_client(), _resolved("GitHub")):
            resp = await client.get(
                CALLBACK_URL,
                params={"state": "tok:github:/settings/integrations", "code": "code1"},
                follow_redirects=False,
            )

        assert (
            resp.headers["location"]
            == "http://frontend/settings/integrations?id=github&status=connected&name=GitHub"
        )

    async def test_success_defaults_the_redirect_path_and_name(self, client: AsyncClient) -> None:
        # Two-part state: no redirect path. Unresolvable integration: the id
        # stands in for the name.
        with _callback_seams(_mcp_client(), resolved=None):
            resp = await client.get(
                CALLBACK_URL,
                params={"state": "tok:github", "code": "code1"},
                follow_redirects=False,
            )

        assert (
            resp.headers["location"]
            == "http://frontend/integrations?id=github&status=connected&name=github"
        )

    async def test_success_records_the_connect_on_the_wide_event(self) -> None:
        with _callback_seams(_mcp_client(), _resolved("GitHub")):
            async with captured_wide_event() as event:
                await mcp_oauth_callback(
                    state="tok:github:/integrations",
                    code="code1",
                    error=None,
                    error_description=None,
                    user=FAKE_USER,
                )
                # The boundary stamps its own outcome on exit; the route's is
                # only readable before that.
                outcome = event["outcome"]

        assert event["user"] == {"id": USER_ID}
        assert event["operation"] == "mcp_oauth_callback"
        assert outcome == "connected"
        assert event["mcp"] == {
            "operation": "connect",
            "server_id": "github",
            "server_name": "GitHub",
            "success": True,
        }
        assert event["audit"] == [
            {"msg": "mcp integration connected via oauth", "actor": USER_ID, "resource": "github"}
        ]
        assert "errors" not in event

    async def test_malformed_state_redirects_with_invalid_state(self, client: AsyncClient) -> None:
        with _callback_seams(_mcp_client()):
            resp = await client.get(
                CALLBACK_URL,
                params={"state": "no-colon-at-all", "code": "code1"},
                follow_redirects=False,
            )

        assert resp.status_code == 307
        assert (
            resp.headers["location"]
            == "http://frontend/integrations?status=failed&error=invalid_state"
        )

    async def test_missing_code_redirects_with_missing_code(self, client: AsyncClient) -> None:
        mcp_client = _mcp_client()

        with _callback_seams(mcp_client, _resolved()) as seams:
            resp = await client.get(
                CALLBACK_URL,
                params={"state": "tok:github:/settings/integrations"},
                follow_redirects=False,
            )

        assert resp.status_code == 307
        assert (
            resp.headers["location"]
            == "http://frontend/settings/integrations?id=github&status=failed&error=missing_code"
        )
        mcp_client.handle_oauth_callback.assert_not_awaited()
        seams["capture"].assert_not_called()

    async def test_provider_error_redirects_with_the_resolved_code(
        self, client: AsyncClient
    ) -> None:
        mcp_client = _mcp_client()

        with _callback_seams(mcp_client) as seams:
            resp = await client.get(
                CALLBACK_URL,
                params={
                    "state": "tok:github:/integrations",
                    "error": "access_denied",
                    "error_description": "User denied access",
                },
                follow_redirects=False,
            )

        assert resp.status_code == 307
        assert (
            resp.headers["location"]
            == "http://frontend/integrations?id=github&status=failed&error=access_denied"
        )
        mcp_client.token_store.clear_excluded_scopes.assert_awaited_once_with("github")
        mcp_client.handle_oauth_callback.assert_not_awaited()
        seams["capture"].assert_not_called()

    async def test_provider_error_with_a_code_still_fails(self, client: AsyncClient) -> None:
        # An error response wins over a stray code: nothing is exchanged.
        mcp_client = _mcp_client()

        with _callback_seams(mcp_client):
            resp = await client.get(
                CALLBACK_URL,
                params={
                    "state": "tok:github:/settings/integrations",
                    "code": "code1",
                    "error": "server_error",
                },
                follow_redirects=False,
            )

        assert (
            resp.headers["location"]
            == "http://frontend/settings/integrations?id=github&status=failed&error=oauth_server_error"
        )
        mcp_client.handle_oauth_callback.assert_not_awaited()

    async def test_invalid_scope_retries_authorization_with_the_callback_details(
        self, client: AsyncClient
    ) -> None:
        mcp_client = _mcp_client(retry_url="https://provider/authorize?scope=less")

        with _callback_seams(mcp_client):
            resp = await client.get(
                CALLBACK_URL,
                params={
                    "state": "tok:github:/settings/integrations",
                    "error": "invalid_scope",
                    "error_description": "user:org:read rejected",
                },
                follow_redirects=False,
            )

        assert resp.status_code == 307
        assert resp.headers["location"] == "https://provider/authorize?scope=less"
        mcp_client.build_scope_retry_url.assert_awaited_once_with(
            "github", "user:org:read rejected", REDIRECT_URI, "/settings/integrations"
        )
        mcp_client.handle_oauth_callback.assert_not_awaited()

    async def test_invalid_scope_without_a_retry_url_fails_with_the_provider_code(
        self, client: AsyncClient
    ) -> None:
        mcp_client = _mcp_client(retry_url=None)

        with _callback_seams(mcp_client):
            resp = await client.get(
                CALLBACK_URL,
                params={"state": "tok:github:/integrations", "error": "invalid_scope"},
                follow_redirects=False,
            )

        assert (
            resp.headers["location"]
            == "http://frontend/integrations?id=github&status=failed&error=invalid_scope"
        )
        mcp_client.build_scope_retry_url.assert_awaited_once_with(
            "github", None, REDIRECT_URI, "/integrations"
        )

    @pytest.mark.parametrize(
        ("exc", "code"),
        [
            (ValueError("Invalid state token"), "invalid_state"),
            (RuntimeError("Token exchange failed"), "token_exchange_failed"),
            (RuntimeError("OAuth discovery failed"), "discovery_failed"),
            (RuntimeError("connection reset"), "connection_failed"),
        ],
    )
    async def test_exchange_failure_redirects_with_a_sanitized_code(
        self, client: AsyncClient, exc: Exception, code: str
    ) -> None:
        mcp_client = _mcp_client()
        mcp_client.handle_oauth_callback = AsyncMock(side_effect=exc)

        with _callback_seams(mcp_client, _resolved()) as seams:
            resp = await client.get(
                CALLBACK_URL,
                params={"state": "tok:github:/settings/integrations", "code": "code1"},
                follow_redirects=False,
            )

        assert resp.status_code == 307
        assert (
            resp.headers["location"]
            == f"http://frontend/settings/integrations?id=github&status=failed&error={code}"
        )
        seams["invalidate"].assert_not_awaited()
        seams["capture"].assert_not_called()

    async def test_exchange_failure_is_recorded_on_the_wide_event(self) -> None:
        mcp_client = _mcp_client()
        mcp_client.handle_oauth_callback = AsyncMock(side_effect=ValueError("Invalid state token"))

        with _callback_seams(mcp_client, _resolved("GitHub")):
            async with captured_wide_event() as event:
                resp = await mcp_oauth_callback(
                    state="tok:github:/integrations",
                    code="code1",
                    error=None,
                    error_description=None,
                    user=FAKE_USER,
                )
                outcome = event["outcome"]

        assert (
            resp.headers["location"]
            == "http://frontend/integrations?id=github&status=failed&error=invalid_state"
        )
        assert outcome == "failed"
        assert event["mcp"] == {
            "operation": "connect",
            "server_id": "github",
            "server_name": "GitHub",
            "success": False,
            "error_type": "ValueError",
        }
        assert event["errors"] == [
            {
                "msg": f"{LogTag.MCP} mcp_oauth_callback failed",
                "integration_id": "github",
                "user_id": USER_ID,
                "error_type": "ValueError",
            }
        ]
        assert "audit" not in event

    async def test_clear_excluded_scopes_failure_does_not_fail_the_connect(
        self, client: AsyncClient
    ) -> None:
        mcp_client = _mcp_client()
        mcp_client.token_store.clear_excluded_scopes = AsyncMock(side_effect=TimeoutError("redis"))

        with _callback_seams(mcp_client, _resolved("GitHub")) as seams:
            resp = await client.get(
                CALLBACK_URL,
                params={"state": "tok:github:/integrations", "code": "code1"},
                follow_redirects=False,
            )

        assert (
            resp.headers["location"]
            == "http://frontend/integrations?id=github&status=connected&name=GitHub"
        )
        seams["invalidate"].assert_awaited_once_with(USER_ID)

    async def test_requires_auth(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.get(
            CALLBACK_URL, params={"state": "tok:github:/integrations", "code": "code1"}
        )

        assert resp.status_code == 401

    async def test_requires_state(self, client: AsyncClient) -> None:
        resp = await client.get(CALLBACK_URL, params={"code": "code1"})

        assert resp.status_code == 422
