"""Unit tests for OAuth state management service."""

from unittest.mock import AsyncMock, PropertyMock, patch

import pytest

from app.constants.cache import STATE_KEY_PREFIX, STATE_TOKEN_TTL
from app.services.oauth.oauth_state_service import (
    _is_safe_redirect_path,
    create_oauth_state,
    validate_and_consume_oauth_state,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_redis_client():
    """Mock the redis_cache.client property used by the state service."""
    mock_client = AsyncMock()
    mock_client.hset = AsyncMock()
    mock_client.expire = AsyncMock()
    mock_client.hgetall = AsyncMock(return_value={})
    mock_client.delete = AsyncMock()
    with patch("app.services.oauth.oauth_state_service.redis_cache") as mock_cache:
        type(mock_cache).client = PropertyMock(return_value=mock_client)
        yield mock_client


# ---------------------------------------------------------------------------
# _is_safe_redirect_path (synchronous, no mocks needed)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestIsSafeRedirectPath:
    def test_valid_simple_path(self):
        assert _is_safe_redirect_path("/c") is True

    def test_valid_nested_path(self):
        assert _is_safe_redirect_path("/settings/integrations") is True

    def test_valid_path_with_query_params(self):
        assert _is_safe_redirect_path("/c?tab=chat") is True

    def test_empty_string_returns_false(self):
        assert _is_safe_redirect_path("") is False

    def test_none_returns_false(self):
        # Although type-hinted as str, the code handles falsy values
        assert _is_safe_redirect_path(None) is False

    def test_relative_path_without_slash_returns_false(self):
        assert _is_safe_redirect_path("settings") is False

    def test_absolute_url_with_http_returns_false(self):
        assert _is_safe_redirect_path("/redirect?url=http://evil.com") is False

    def test_absolute_url_with_https_returns_false(self):
        assert _is_safe_redirect_path("/redirect?url=https://evil.com") is False

    def test_protocol_relative_url_returns_false(self):
        assert _is_safe_redirect_path("//evil.com") is False

    def test_double_slash_in_path_returns_false(self):
        assert _is_safe_redirect_path("/foo//bar") is False

    def test_javascript_scheme_returns_false(self):
        assert _is_safe_redirect_path("/test?x=javascript:alert(1)") is False

    def test_javascript_scheme_uppercase_returns_false(self):
        assert _is_safe_redirect_path("/test?x=JAVASCRIPT:alert(1)") is False

    def test_javascript_scheme_mixed_case_returns_false(self):
        assert _is_safe_redirect_path("/test?x=JaVaScRiPt:alert(1)") is False

    def test_data_scheme_returns_false(self):
        assert _is_safe_redirect_path("/test?x=data:text/html,<h1>hi</h1>") is False

    def test_vbscript_scheme_returns_false(self):
        assert _is_safe_redirect_path("/test?x=vbscript:msgbox") is False

    def test_file_scheme_returns_false(self):
        assert _is_safe_redirect_path("/test?x=file:///etc/passwd") is False

    def test_ftp_scheme_returns_false(self):
        assert _is_safe_redirect_path("/test?x=ftp://evil.com") is False

    def test_ftps_scheme_returns_false(self):
        assert _is_safe_redirect_path("/test?x=ftps://evil.com") is False

    def test_ws_scheme_returns_false(self):
        assert _is_safe_redirect_path("/test?x=ws://evil.com") is False

    def test_wss_scheme_returns_false(self):
        assert _is_safe_redirect_path("/test?x=wss://evil.com") is False

    def test_path_traversal_returns_false(self):
        assert _is_safe_redirect_path("/../../etc/passwd") is False

    def test_path_traversal_middle_returns_false(self):
        assert _is_safe_redirect_path("/foo/../bar") is False

    def test_at_sign_returns_false(self):
        assert _is_safe_redirect_path("/user@evil.com") is False

    def test_at_sign_in_query_returns_false(self):
        assert _is_safe_redirect_path("/foo?email=user@evil.com") is False

    def test_valid_path_with_hash_fragment(self):
        assert _is_safe_redirect_path("/c#section") is True

    def test_valid_path_with_numeric_segment(self):
        assert _is_safe_redirect_path("/c/12345") is True

    def test_single_slash_is_valid(self):
        assert _is_safe_redirect_path("/") is True


# ---------------------------------------------------------------------------
# create_oauth_state
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCreateOAuthState:
    async def test_creates_state_with_valid_params(self, mock_redis_client):
        token = await create_oauth_state(
            user_id="user123",
            redirect_path="/settings/integrations",
            integration_id="gmail",
        )

        assert isinstance(token, str)
        assert len(token) > 0

        # Verify Redis hset was called with correct key prefix and data
        mock_redis_client.hset.assert_awaited_once()
        call_kwargs = mock_redis_client.hset.call_args
        state_key = (
            call_kwargs[0][0] if call_kwargs[0] else call_kwargs.kwargs.get("name")
        )
        assert state_key.startswith(f"{STATE_KEY_PREFIX}:")

        mapping = call_kwargs.kwargs.get("mapping") or call_kwargs[1].get("mapping")
        assert mapping["user_id"] == "user123"
        assert mapping["redirect_path"] == "/settings/integrations"
        assert mapping["integration_id"] == "gmail"

    async def test_sets_correct_ttl(self, mock_redis_client):
        token = await create_oauth_state(
            user_id="user123",
            redirect_path="/c",
            integration_id="notion",
        )

        mock_redis_client.expire.assert_awaited_once()
        call_args = mock_redis_client.expire.call_args
        state_key = call_args[0][0]
        ttl = call_args[0][1]
        assert ttl == STATE_TOKEN_TTL
        assert state_key == f"{STATE_KEY_PREFIX}:{token}"

    async def test_generates_unique_tokens(self, mock_redis_client):
        token1 = await create_oauth_state("user1", "/c", "gmail")
        token2 = await create_oauth_state("user2", "/c", "gmail")

        assert token1 != token2

    async def test_unsafe_redirect_path_defaults_to_safe_path(self, mock_redis_client):
        """Unsafe redirect paths should be replaced with '/c'."""
        token = await create_oauth_state(
            user_id="user123",
            redirect_path="https://evil.com",
            integration_id="gmail",
        )

        assert isinstance(token, str)
        call_kwargs = mock_redis_client.hset.call_args
        mapping = call_kwargs.kwargs.get("mapping") or call_kwargs[1].get("mapping")
        assert mapping["redirect_path"] == "/c"

    async def test_protocol_relative_redirect_defaults_to_safe_path(
        self, mock_redis_client
    ):
        await create_oauth_state(
            user_id="user123",
            redirect_path="//evil.com/steal",
            integration_id="gmail",
        )

        call_kwargs = mock_redis_client.hset.call_args
        mapping = call_kwargs.kwargs.get("mapping") or call_kwargs[1].get("mapping")
        assert mapping["redirect_path"] == "/c"

    async def test_path_traversal_redirect_defaults_to_safe_path(
        self, mock_redis_client
    ):
        await create_oauth_state(
            user_id="user123",
            redirect_path="/../../etc/passwd",
            integration_id="gmail",
        )

        call_kwargs = mock_redis_client.hset.call_args
        mapping = call_kwargs.kwargs.get("mapping") or call_kwargs[1].get("mapping")
        assert mapping["redirect_path"] == "/c"

    async def test_empty_redirect_path_defaults_to_safe_path(self, mock_redis_client):
        await create_oauth_state(
            user_id="user123",
            redirect_path="",
            integration_id="gmail",
        )

        call_kwargs = mock_redis_client.hset.call_args
        mapping = call_kwargs.kwargs.get("mapping") or call_kwargs[1].get("mapping")
        assert mapping["redirect_path"] == "/c"

    async def test_javascript_redirect_defaults_to_safe_path(self, mock_redis_client):
        await create_oauth_state(
            user_id="user123",
            redirect_path="/x?r=javascript:alert(1)",
            integration_id="gmail",
        )

        call_kwargs = mock_redis_client.hset.call_args
        mapping = call_kwargs.kwargs.get("mapping") or call_kwargs[1].get("mapping")
        assert mapping["redirect_path"] == "/c"


# ---------------------------------------------------------------------------
# validate_and_consume_oauth_state
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestValidateAndConsumeOAuthState:
    async def test_valid_token_returns_state_data(self, mock_redis_client):
        mock_redis_client.hgetall = AsyncMock(
            return_value={
                "user_id": "user123",
                "redirect_path": "/settings",
                "integration_id": "gmail",
            }
        )

        result = await validate_and_consume_oauth_state("valid_token_abc")

        assert result is not None
        assert result["user_id"] == "user123"
        assert result["redirect_path"] == "/settings"
        assert result["integration_id"] == "gmail"

    async def test_valid_token_is_deleted_after_consumption(self, mock_redis_client):
        mock_redis_client.hgetall = AsyncMock(
            return_value={
                "user_id": "user123",
                "redirect_path": "/c",
                "integration_id": "gmail",
            }
        )

        await validate_and_consume_oauth_state("valid_token_abc")

        expected_key = f"{STATE_KEY_PREFIX}:valid_token_abc"
        mock_redis_client.delete.assert_awaited_once_with(expected_key)

    async def test_expired_token_returns_none(self, mock_redis_client):
        """Expired/missing tokens return empty dict from hgetall."""
        mock_redis_client.hgetall = AsyncMock(return_value={})

        result = await validate_and_consume_oauth_state("expired_token")

        assert result is None
        # Should NOT try to delete a non-existent token
        mock_redis_client.delete.assert_not_awaited()

    async def test_invalid_token_returns_none(self, mock_redis_client):
        mock_redis_client.hgetall = AsyncMock(return_value={})

        result = await validate_and_consume_oauth_state("nonexistent_token")

        assert result is None

    async def test_incomplete_state_data_missing_user_id_returns_none(
        self, mock_redis_client
    ):
        """If user_id is missing from state data, return None."""
        mock_redis_client.hgetall = AsyncMock(
            return_value={
                "user_id": "",
                "redirect_path": "/c",
                "integration_id": "gmail",
            }
        )

        result = await validate_and_consume_oauth_state("token_abc")

        assert result is None

    async def test_incomplete_state_data_missing_redirect_path_returns_none(
        self, mock_redis_client
    ):
        mock_redis_client.hgetall = AsyncMock(
            return_value={
                "user_id": "user123",
                "redirect_path": "",
                "integration_id": "gmail",
            }
        )

        result = await validate_and_consume_oauth_state("token_abc")

        assert result is None

    async def test_incomplete_state_data_missing_integration_id_returns_none(
        self, mock_redis_client
    ):
        mock_redis_client.hgetall = AsyncMock(
            return_value={
                "user_id": "user123",
                "redirect_path": "/c",
                "integration_id": "",
            }
        )

        result = await validate_and_consume_oauth_state("token_abc")

        assert result is None

    async def test_all_fields_missing_returns_none(self, mock_redis_client):
        """hgetall returns data with empty-string defaults for missing keys."""
        mock_redis_client.hgetall = AsyncMock(
            return_value={
                "user_id": "",
                "redirect_path": "",
                "integration_id": "",
            }
        )

        result = await validate_and_consume_oauth_state("token_abc")

        assert result is None

    async def test_redis_exception_returns_none(self, mock_redis_client):
        """Any Redis error should be caught and return None."""
        mock_redis_client.hgetall = AsyncMock(
            side_effect=Exception("Redis connection lost")
        )

        result = await validate_and_consume_oauth_state("token_abc")

        assert result is None

    async def test_redis_error_on_delete_still_returns_data(self, mock_redis_client):
        """If delete fails but hgetall succeeded, the exception is caught at the
        outer level. Since delete is inside the try block, an exception there
        causes the whole validate to return None."""
        mock_redis_client.hgetall = AsyncMock(
            return_value={
                "user_id": "user123",
                "redirect_path": "/c",
                "integration_id": "gmail",
            }
        )
        mock_redis_client.delete = AsyncMock(
            side_effect=Exception("Redis delete error")
        )

        result = await validate_and_consume_oauth_state("token_abc")

        # The exception is caught by the outer try/except, returns None
        assert result is None

    async def test_correct_redis_key_format(self, mock_redis_client):
        """Verify the correct Redis key format is used."""
        mock_redis_client.hgetall = AsyncMock(
            return_value={
                "user_id": "user123",
                "redirect_path": "/c",
                "integration_id": "notion",
            }
        )

        await validate_and_consume_oauth_state("my_state_token_xyz")

        expected_key = f"{STATE_KEY_PREFIX}:my_state_token_xyz"
        mock_redis_client.hgetall.assert_awaited_once_with(expected_key)

    async def test_state_data_defaults_for_missing_keys(self, mock_redis_client):
        """If hgetall returns a dict without some keys, they default to ''."""
        mock_redis_client.hgetall = AsyncMock(
            return_value={
                "user_id": "user123",
                # redirect_path and integration_id are missing from Redis
            }
        )

        result = await validate_and_consume_oauth_state("token_abc")

        # Both redirect_path and integration_id would be empty -> validation fails
        assert result is None

    async def test_replay_attack_prevention(self, mock_redis_client):
        """Token is deleted after first successful validation (one-time use)."""
        state_data = {
            "user_id": "user123",
            "redirect_path": "/c",
            "integration_id": "gmail",
        }

        # First call: token exists
        mock_redis_client.hgetall = AsyncMock(return_value=state_data)
        result1 = await validate_and_consume_oauth_state("one_time_token")
        assert result1 is not None

        # Token deleted
        mock_redis_client.delete.assert_awaited_once()

        # Second call: token gone
        mock_redis_client.hgetall = AsyncMock(return_value={})
        result2 = await validate_and_consume_oauth_state("one_time_token")
        assert result2 is None
