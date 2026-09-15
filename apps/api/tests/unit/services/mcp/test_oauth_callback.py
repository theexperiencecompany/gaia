"""Unit tests for app.services.mcp.oauth_callback.

The MCPClient is the seam: every test hands the service a mock client and
asserts what it did with it and what it handed back to the route.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.constants.log_tags import LogTag
from app.services.analytics_service import AnalyticsEvents
from app.services.mcp.oauth_callback import (
    KNOWN_OAUTH_ERRORS,
    ProviderError,
    ScopeRetry,
    complete_oauth,
    resolve_provider_error,
    sanitized_error_code,
)
from tests.helpers import captured_wide_event

pytestmark = pytest.mark.unit

MODULE = "app.services.mcp.oauth_callback"
INTEGRATION_ID = "agentmail"
REDIRECT_URI = "http://api/api/v1/mcp/oauth/callback"
REDIRECT_PATH = "/integrations"
USER_ID = "507f1f77bcf86cd799439011"


def _client(*, retry_url: str | None = None) -> MagicMock:
    client = MagicMock()
    client.build_scope_retry_url = AsyncMock(return_value=retry_url)
    client.handle_oauth_callback = AsyncMock()
    client.token_store = MagicMock()
    client.token_store.clear_excluded_scopes = AsyncMock()
    return client


async def _resolve(
    client: MagicMock, error: str, error_description: str | None = "desc"
) -> ScopeRetry | ProviderError:
    return await resolve_provider_error(
        client,
        integration_id=INTEGRATION_ID,
        redirect_uri=REDIRECT_URI,
        redirect_path=REDIRECT_PATH,
        error=error,
        error_description=error_description,
    )


class TestResolveProviderError:
    async def test_invalid_scope_with_a_retry_url_sends_the_browser_back_through_auth(self):
        client = _client(retry_url="https://provider/authorize?scope=less")

        outcome = await _resolve(client, "invalid_scope", "scope user:org:read rejected")

        assert outcome == ScopeRetry(url="https://provider/authorize?scope=less")
        client.build_scope_retry_url.assert_awaited_once_with(
            INTEGRATION_ID, "scope user:org:read rejected", REDIRECT_URI, REDIRECT_PATH
        )
        # The exclusions are what the retry relies on — they must survive it.
        client.token_store.clear_excluded_scopes.assert_not_awaited()

    async def test_invalid_scope_without_a_retry_url_falls_through_to_the_error(self):
        client = _client(retry_url=None)

        outcome = await _resolve(client, "invalid_scope")

        assert outcome == ProviderError(code="invalid_scope")
        client.token_store.clear_excluded_scopes.assert_awaited_once_with(INTEGRATION_ID)

    async def test_retry_build_failure_falls_through_and_is_recorded(self):
        client = _client()
        client.build_scope_retry_url = AsyncMock(side_effect=RuntimeError("redis down"))

        async with captured_wide_event() as event:
            outcome = await _resolve(client, "invalid_scope", "scope rejected")

        assert outcome == ProviderError(code="invalid_scope")
        client.token_store.clear_excluded_scopes.assert_awaited_once_with(INTEGRATION_ID)
        assert event["warnings"] == [
            {
                "msg": f"{LogTag.MCP} OAuth error returned by provider",
                "integration_id": INTEGRATION_ID,
                "oauth_error": "invalid_scope",
                "oauth_error_description": "scope rejected",
            },
            {
                "msg": f"{LogTag.MCP} Scope retry URL build failed",
                "integration_id": INTEGRATION_ID,
                "error_type": "RuntimeError",
            },
        ]

    async def test_clear_excluded_scopes_failure_still_returns_the_error(self):
        client = _client()
        client.token_store.clear_excluded_scopes = AsyncMock(side_effect=ConnectionError("redis"))

        async with captured_wide_event() as event:
            outcome = await _resolve(client, "access_denied", None)

        assert outcome == ProviderError(code="access_denied")
        assert event["warnings"] == [
            {
                "msg": f"{LogTag.MCP} OAuth error returned by provider",
                "integration_id": INTEGRATION_ID,
                "oauth_error": "access_denied",
                "oauth_error_description": None,
            },
            {
                "msg": f"{LogTag.MCP} Failed to clear excluded scopes",
                "integration_id": INTEGRATION_ID,
                "error_type": "ConnectionError",
            },
        ]

    async def test_server_error_is_renamed_for_the_frontend(self):
        client = _client()

        outcome = await _resolve(client, "server_error")

        assert outcome == ProviderError(code="oauth_server_error")
        client.token_store.clear_excluded_scopes.assert_awaited_once_with(INTEGRATION_ID)

    @pytest.mark.parametrize(
        "error", sorted(KNOWN_OAUTH_ERRORS - {"server_error", "invalid_scope"})
    )
    async def test_known_provider_errors_pass_through_unchanged(self, error: str):
        client = _client()

        outcome = await _resolve(client, error)

        assert outcome == ProviderError(code=error)
        client.build_scope_retry_url.assert_not_awaited()
        client.token_store.clear_excluded_scopes.assert_awaited_once_with(INTEGRATION_ID)

    def test_the_known_error_set_is_the_oauth_spec_list(self):
        assert {
            "access_denied",
            "invalid_request",
            "unauthorized_client",
            "unsupported_response_type",
            "invalid_scope",
            "server_error",
            "temporarily_unavailable",
        } == KNOWN_OAUTH_ERRORS

    async def test_unknown_provider_error_becomes_authorization_failed(self):
        client = _client()

        outcome = await _resolve(client, "some_vendor_specific_code")

        assert outcome == ProviderError(code="authorization_failed")
        client.build_scope_retry_url.assert_not_awaited()

    async def test_the_provider_error_is_recorded_on_the_wide_event(self):
        client = _client()

        async with captured_wide_event() as event:
            await _resolve(client, "access_denied", "User denied access")

        assert event["warnings"] == [
            {
                "msg": f"{LogTag.MCP} OAuth error returned by provider",
                "integration_id": INTEGRATION_ID,
                "oauth_error": "access_denied",
                "oauth_error_description": "User denied access",
            }
        ]


class TestSanitizedErrorCode:
    @pytest.mark.parametrize(
        ("exc", "code"),
        [
            (ValueError("Invalid state token"), "invalid_state"),
            (ValueError("OAuth STATE mismatch"), "invalid_state"),
            (RuntimeError("token exchange failed: 401"), "token_exchange_failed"),
            (RuntimeError("Token endpoint rejected the code"), "token_exchange_failed"),
            (RuntimeError("OAuth discovery failed"), "discovery_failed"),
            (RuntimeError("Discovery document unreachable"), "discovery_failed"),
            (RuntimeError("connection reset by peer"), "connection_failed"),
            (RuntimeError(""), "connection_failed"),
        ],
    )
    def test_maps_the_exception_message_to_a_generic_code(self, exc: Exception, code: str):
        assert sanitized_error_code(exc) == code

    def test_state_wins_over_token_and_discovery(self):
        # "state" is checked first: a state-token failure is an invalid_state,
        # not a token exchange failure.
        assert sanitized_error_code(ValueError("state token discovery")) == "invalid_state"

    def test_token_wins_over_discovery(self):
        assert sanitized_error_code(ValueError("token discovery")) == "token_exchange_failed"


class TestCompleteOauth:
    async def _complete(self, client: MagicMock) -> None:
        await complete_oauth(
            client,
            user_id=USER_ID,
            integration_id=INTEGRATION_ID,
            code="auth-code",
            state_token="state-token",
            redirect_uri=REDIRECT_URI,
        )

    async def test_exchanges_the_code_with_the_client(self):
        client = _client()

        with (
            patch(f"{MODULE}.invalidate_user_integration_caches", new_callable=AsyncMock),
            patch(f"{MODULE}.capture_context_event"),
        ):
            await self._complete(client)

        client.handle_oauth_callback.assert_awaited_once_with(
            integration_id=INTEGRATION_ID,
            code="auth-code",
            state="state-token",
            redirect_uri=REDIRECT_URI,
        )
        client.token_store.clear_excluded_scopes.assert_awaited_once_with(INTEGRATION_ID)

    async def test_invalidates_the_user_caches_and_captures_the_event(self):
        client = _client()

        with (
            patch(
                f"{MODULE}.invalidate_user_integration_caches", new_callable=AsyncMock
            ) as invalidate,
            patch(f"{MODULE}.capture_context_event") as capture,
        ):
            await self._complete(client)

        invalidate.assert_awaited_once_with(USER_ID)
        capture.assert_called_once_with(
            AnalyticsEvents.INTEGRATION_CONNECTED,
            {"integration_id": INTEGRATION_ID, "connection_method": "oauth"},
        )

    async def test_clear_excluded_scopes_failure_does_not_fail_the_connect(self):
        client = _client()
        client.token_store.clear_excluded_scopes = AsyncMock(side_effect=TimeoutError("redis"))

        with (
            patch(
                f"{MODULE}.invalidate_user_integration_caches", new_callable=AsyncMock
            ) as invalidate,
            patch(f"{MODULE}.capture_context_event") as capture,
        ):
            async with captured_wide_event() as event:
                await self._complete(client)

        invalidate.assert_awaited_once_with(USER_ID)
        capture.assert_called_once_with(
            AnalyticsEvents.INTEGRATION_CONNECTED,
            {"integration_id": INTEGRATION_ID, "connection_method": "oauth"},
        )
        assert event["warnings"] == [
            {
                "msg": f"{LogTag.MCP} Failed to clear excluded scopes after OAuth success",
                "integration_id": INTEGRATION_ID,
                "error_type": "TimeoutError",
            }
        ]

    async def test_a_failed_exchange_propagates_before_any_bookkeeping(self):
        client = _client()
        client.handle_oauth_callback = AsyncMock(side_effect=ValueError("Invalid state token"))

        with (
            patch(
                f"{MODULE}.invalidate_user_integration_caches", new_callable=AsyncMock
            ) as invalidate,
            patch(f"{MODULE}.capture_context_event") as capture,
            pytest.raises(ValueError, match="Invalid state token"),
        ):
            await self._complete(client)

        client.token_store.clear_excluded_scopes.assert_not_awaited()
        invalidate.assert_not_awaited()
        capture.assert_not_called()
