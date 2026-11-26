"""Unit tests for the MCP integration endpoints (app/api/v1/endpoints/mcp.py).

The OAuth callback route owns the redirect URLs: every test pins the exact
Location the browser is sent to. The MCPClient and the OAuth flow functions
are the seam; the oauth_callback service runs for real.
"""

from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from httpx import AsyncClient
import pytest

from app.api.v1.dependencies.oauth_dependencies import get_optional_user
from app.api.v1.endpoints.mcp import mcp_oauth_callback
from app.constants import mcp as mcp_constants
from app.constants.log_tags import LogTag
from app.services.mcp import mcp_token_store
from app.services.mcp.mcp_token_store import MCPTokenStore
from shared.py.analytics import UserId
from shared.py.analytics.catalog.integrations import IntegrationConnected
from tests.conftest import FAKE_USER
from tests.helpers import captured_wide_event

pytestmark = pytest.mark.unit

MCP_BASE = "/api/v1/mcp"
CALLBACK_URL = f"{MCP_BASE}/oauth/callback"
_MODULE = "app.api.v1.endpoints.mcp"
_CALLBACK = "app.services.mcp.oauth_callback"
USER_ID = FAKE_USER.user_id
REDIRECT_URI = "http://api/api/v1/mcp/oauth/callback"


def _mcp_client() -> MagicMock:
    mcp_client = MagicMock()
    mcp_client.token_store = MagicMock()
    mcp_client.token_store.clear_excluded_scopes = AsyncMock()
    return mcp_client


def _resolved(name: str = "GitHub") -> MagicMock:
    resolved = MagicMock()
    resolved.name = name
    return resolved


@contextmanager
def _callback_seams(
    mcp_client: MagicMock,
    resolved: MagicMock | None = None,
    *,
    retry_url: str | None = None,
    exchange_error: Exception | None = None,
    real_owner_lookup: bool = False,
) -> Iterator[dict[str, MagicMock]]:
    owner_lookup = (
        nullcontext()
        if real_owner_lookup
        else patch(
            f"{_MODULE}.resolve_oauth_state_owner",
            new_callable=AsyncMock,
            return_value=USER_ID,
        )
    )
    with (
        owner_lookup,
        patch(
            f"{_CALLBACK}.handle_oauth_callback", new_callable=AsyncMock, side_effect=exchange_error
        ) as exchange,
        patch(
            f"{_CALLBACK}.build_scope_retry_url", new_callable=AsyncMock, return_value=retry_url
        ) as scope_retry,
        patch(f"{_MODULE}.get_mcp_client", new_callable=AsyncMock, return_value=mcp_client),
        patch(
            f"{_MODULE}.IntegrationResolver.resolve",
            new_callable=AsyncMock,
            return_value=resolved,
        ),
        patch(f"{_CALLBACK}.invalidate_user_integration_caches", new_callable=AsyncMock) as inv,
        patch(
            f"{_CALLBACK}.user_integration_repository.has_connected_before",
            new_callable=AsyncMock,
            return_value=False,
        ),
        patch(f"{_MODULE}.get_mcp_oauth_redirect_uri", return_value=REDIRECT_URI),
        patch(f"{_MODULE}.get_frontend_url", return_value="http://frontend"),
        patch(f"{_CALLBACK}.capture") as capture,
    ):
        yield {
            "invalidate": inv,
            "capture": capture,
            "exchange": exchange,
            "scope_retry": scope_retry,
        }


class TestMCPOAuthCallbackWithoutASession:
    """A link opened from a chat app reaches the callback with no GAIA session."""

    @pytest.mark.regression
    @pytest.mark.usefixtures("fake_redis")
    async def test_the_browser_that_opened_the_connect_link_completes_the_flow(
        self, unauthed_client: AsyncClient
    ) -> None:
        state = await MCPTokenStore(USER_ID).create_oauth_state("github", "verifier")
        # read at call time: the regression lane imports this file against master
        nonce = await mcp_token_store.bind_oauth_state_to_browser(state)
        unauthed_client.cookies.set(mcp_constants.MCP_OAUTH_BROWSER_COOKIE, nonce)
        mcp_client = _mcp_client()

        with (
            _callback_seams(mcp_client, _resolved("GitHub"), real_owner_lookup=True) as seams,
            patch(f"{_MODULE}.get_mcp_client", new_callable=AsyncMock) as get_client,
        ):
            get_client.return_value = mcp_client
            resp = await unauthed_client.get(
                CALLBACK_URL,
                params={"state": f"{state}:github:/integrations", "code": "code1"},
                follow_redirects=False,
            )

        assert resp.headers["location"] == (
            "http://frontend/integrations?id=github&status=connected&name=GitHub"
        )
        get_client.assert_awaited_once_with(user_id=USER_ID)
        seams["capture"].assert_called_once()
        assert seams["capture"].call_args.args[0] == UserId(USER_ID)

    @pytest.mark.usefixtures("fake_redis")
    async def test_unknown_state_redirects_with_expired_state(
        self, unauthed_client: AsyncClient
    ) -> None:
        with _callback_seams(_mcp_client(), real_owner_lookup=True) as seams:
            resp = await unauthed_client.get(
                CALLBACK_URL,
                params={"state": "never-minted:github:/integrations", "code": "code1"},
                follow_redirects=False,
            )

        assert resp.headers["location"] == (
            "http://frontend/integrations?id=github&status=failed&error=expired_state"
        )
        seams["exchange"].assert_not_awaited()

    @pytest.mark.usefixtures("fake_redis")
    async def test_state_for_another_integration_redirects_with_expired_state(
        self, unauthed_client: AsyncClient
    ) -> None:
        state = await MCPTokenStore(USER_ID).create_oauth_state("resend", "verifier")

        with _callback_seams(_mcp_client(), real_owner_lookup=True) as seams:
            resp = await unauthed_client.get(
                CALLBACK_URL,
                params={"state": f"{state}:github:/integrations", "code": "code1"},
                follow_redirects=False,
            )

        assert resp.headers["location"] == (
            "http://frontend/integrations?id=github&status=failed&error=expired_state"
        )
        seams["exchange"].assert_not_awaited()


class TestMCPOAuthCallbackFromAnotherBrowser:
    """A provider link someone else started cannot attach the clicker's account to theirs."""

    @pytest.mark.usefixtures("fake_redis")
    async def test_a_browser_with_neither_session_nor_binding_is_refused(
        self, unauthed_client: AsyncClient
    ) -> None:
        state = await MCPTokenStore(USER_ID).create_oauth_state("github", "verifier")

        with _callback_seams(_mcp_client(), real_owner_lookup=True) as seams:
            resp = await unauthed_client.get(
                CALLBACK_URL,
                params={"state": f"{state}:github:/integrations", "code": "code1"},
                follow_redirects=False,
            )

        assert resp.headers["location"] == (
            "http://frontend/integrations?id=github&status=failed&error=wrong_browser"
        )
        seams["exchange"].assert_not_awaited()

    @pytest.mark.usefixtures("fake_redis")
    async def test_a_browser_bound_to_another_state_is_refused(
        self, unauthed_client: AsyncClient
    ) -> None:
        store = MCPTokenStore(USER_ID)
        state = await store.create_oauth_state("github", "verifier")
        other = await MCPTokenStore("other-user").create_oauth_state("github", "verifier")
        nonce = await mcp_token_store.bind_oauth_state_to_browser(other)
        unauthed_client.cookies.set(mcp_constants.MCP_OAUTH_BROWSER_COOKIE, nonce)

        with _callback_seams(_mcp_client(), real_owner_lookup=True) as seams:
            resp = await unauthed_client.get(
                CALLBACK_URL,
                params={"state": f"{state}:github:/integrations", "code": "code1"},
                follow_redirects=False,
            )

        assert "error=wrong_browser" in resp.headers["location"]
        seams["exchange"].assert_not_awaited()

    @pytest.mark.usefixtures("fake_redis")
    async def test_a_browser_signed_in_as_someone_else_is_refused(
        self, client: AsyncClient, test_app: FastAPI
    ) -> None:
        test_app.dependency_overrides[get_optional_user] = lambda: FAKE_USER
        state = await MCPTokenStore("someone-else").create_oauth_state("github", "verifier")

        with _callback_seams(_mcp_client(), real_owner_lookup=True) as seams:
            resp = await client.get(
                CALLBACK_URL,
                params={"state": f"{state}:github:/integrations", "code": "code1"},
                follow_redirects=False,
            )

        test_app.dependency_overrides.pop(get_optional_user, None)
        assert "error=wrong_browser" in resp.headers["location"]
        seams["exchange"].assert_not_awaited()


class TestMCPOAuthCallback:
    """GET /api/v1/mcp/oauth/callback."""

    @pytest.fixture(autouse=True)
    def signed_in(self, test_app: FastAPI) -> Iterator[None]:
        test_app.dependency_overrides[get_optional_user] = lambda: FAKE_USER
        yield
        test_app.dependency_overrides.pop(get_optional_user, None)

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
        seams["exchange"].assert_awaited_once_with(
            mcp_client.token_store,
            integration_id="github",
            code="code1",
            state="tok",
            redirect_uri=REDIRECT_URI,
            connect_after_oauth=mcp_client.connect_after_oauth,
        )
        mcp_client.token_store.clear_excluded_scopes.assert_awaited_once_with("github")
        seams["invalidate"].assert_awaited_once_with(USER_ID)
        seams["capture"].assert_called_once_with(
            UserId(USER_ID),
            IntegrationConnected(
                integration_id="github", connection_method="oauth", is_reconnect=False
            ),
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
                    browser_nonce=None,
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
        seams["exchange"].assert_not_awaited()
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
        seams["exchange"].assert_not_awaited()
        seams["capture"].assert_not_called()

    async def test_provider_error_with_a_code_still_fails(self, client: AsyncClient) -> None:
        # An error response wins over a stray code: nothing is exchanged.
        with _callback_seams(_mcp_client()) as seams:
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
        seams["exchange"].assert_not_awaited()

    async def test_invalid_scope_retries_authorization_with_the_callback_details(
        self, client: AsyncClient
    ) -> None:
        mcp_client = _mcp_client()

        with _callback_seams(
            mcp_client, retry_url="https://provider/authorize?scope=less"
        ) as seams:
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
        seams["scope_retry"].assert_awaited_once_with(
            mcp_client.token_store,
            "github",
            "user:org:read rejected",
            REDIRECT_URI,
            "/settings/integrations",
        )
        seams["exchange"].assert_not_awaited()

    async def test_invalid_scope_without_a_retry_url_fails_with_the_provider_code(
        self, client: AsyncClient
    ) -> None:
        mcp_client = _mcp_client()

        with _callback_seams(mcp_client) as seams:
            resp = await client.get(
                CALLBACK_URL,
                params={"state": "tok:github:/integrations", "error": "invalid_scope"},
                follow_redirects=False,
            )

        assert (
            resp.headers["location"]
            == "http://frontend/integrations?id=github&status=failed&error=invalid_scope"
        )
        seams["scope_retry"].assert_awaited_once_with(
            mcp_client.token_store, "github", None, REDIRECT_URI, "/integrations"
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
        with _callback_seams(_mcp_client(), _resolved(), exchange_error=exc) as seams:
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
        with _callback_seams(
            _mcp_client(), _resolved("GitHub"), exchange_error=ValueError("Invalid state token")
        ):
            async with captured_wide_event() as event:
                resp = await mcp_oauth_callback(
                    state="tok:github:/integrations",
                    code="code1",
                    error=None,
                    error_description=None,
                    user=FAKE_USER,
                    browser_nonce=None,
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

    async def test_requires_state(self, client: AsyncClient) -> None:
        resp = await client.get(CALLBACK_URL, params={"code": "code1"})

        assert resp.status_code == 422


class TestMCPConnectionTest:
    """POST /api/v1/mcp/test/{integration_id}."""

    async def test_the_resolved_server_url_is_what_gets_probed(self, client: AsyncClient) -> None:
        # The probe is the only thing that reaches out; probing anything but the
        # integration's own URL reports another server's health as this one's.
        probe_client = MagicMock()
        probe_client.probe_connection = AsyncMock(return_value={"error": "timeout"})
        resolved = MagicMock()
        resolved.mcp_config.server_url = "https://mcp.example.com/sse"
        with (
            patch(f"{_MODULE}.get_mcp_client", new_callable=AsyncMock, return_value=probe_client),
            patch(
                f"{_MODULE}.IntegrationResolver.resolve",
                new_callable=AsyncMock,
                return_value=resolved,
            ),
            patch(f"{_MODULE}.capture"),
        ):
            resp = await client.post(f"{MCP_BASE}/test/github")

        assert resp.status_code == 200
        assert resp.json()["status"] == "failed"
        probe_client.probe_connection.assert_awaited_once_with("https://mcp.example.com/sse")
