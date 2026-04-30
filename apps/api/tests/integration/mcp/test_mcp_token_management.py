"""Integration tests for MCP token storage and retrieval.

Tests the MCPTokenStore class with mocked PostgreSQL sessions and Redis
to verify token storage, expiry checks, and credential deletion.
Encryption is handled transparently by the EncryptedText SQLAlchemy
TypeDecorator; in tests using mocked sessions, values are plaintext.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.db_oauth import MCPAuthType, MCPCredential, MCPCredentialStatus
from app.services.mcp.mcp_token_store import MCPTokenStore


@pytest.fixture
def token_store():
    """Create an MCPTokenStore for the test user."""
    return MCPTokenStore("test-user")


def _make_bearer_credential(
    token_store: MCPTokenStore, integration_id: str, plaintext: str
) -> MCPCredential:
    """Build an MCPCredential simulating what the DB would return after decryption.

    In production, EncryptedText.process_result_value decrypts the stored
    ciphertext before Python sees the value.  In tests with mocked sessions the
    TypeDecorator never runs, so we set access_token to the plaintext directly.
    """
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return MCPCredential(
        user_id=token_store.user_id,
        integration_id=integration_id,
        auth_type=MCPAuthType.BEARER,
        access_token=plaintext,
        status=MCPCredentialStatus.CONNECTED,
        connected_at=now,
    )


def _make_db_session_context(mock_session: AsyncMock) -> AsyncMock:
    """Wrap a mock session in an async-context-manager that get_db_session() returns."""
    context = AsyncMock()
    context.__aenter__ = AsyncMock(return_value=mock_session)
    context.__aexit__ = AsyncMock(return_value=False)
    return context


@pytest.mark.integration
class TestMCPTokenManagement:
    """Test token store credential lifecycle."""

    @patch("app.services.mcp.mcp_token_store.get_db_session")
    async def test_store_and_get_bearer_token(self, mock_get_session, token_store):
        """store_bearer_token writes a credential; access_token is plaintext in mock context.

        Encryption happens at the SQLAlchemy TypeDecorator level (EncryptedText).
        The mocked session never invokes process_bind_param, so the Python-side
        object retains the original plaintext value.
        """
        mock_session = AsyncMock()
        mock_result = MagicMock()
        # No existing credential on store path
        mock_result.scalar_one_or_none = MagicMock(return_value=None)
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()
        mock_get_session.return_value = _make_db_session_context(mock_session)

        await token_store.store_bearer_token("integration-1", "bearer-secret-123")

        # Verify session.add was called with an MCPCredential
        assert mock_session.add.called
        added_obj = mock_session.add.call_args[0][0]
        assert added_obj.user_id == "test-user"
        assert added_obj.integration_id == "integration-1"
        # In mock context the TypeDecorator never runs — value stays plaintext.
        assert added_obj.access_token == "bearer-secret-123"

    # ------------------------------------------------------------------
    # get_bearer_token retrieval tests — the path the old test never called
    # ------------------------------------------------------------------

    @patch("app.services.mcp.mcp_token_store.get_db_session")
    async def test_get_bearer_token_returns_stored_value(
        self, mock_get_session, token_store
    ):
        """get_bearer_token returns the plaintext token from the credential.

        In production EncryptedText decrypts the DB value before Python sees
        it.  In tests the mock session skips that step, so the Python-side
        access_token is already the plaintext we set here.
        """
        plaintext = "bearer-secret-abc"
        stored_cred = _make_bearer_credential(token_store, "int-get-bearer", plaintext)

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=stored_cred)
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_get_session.return_value = _make_db_session_context(mock_session)

        result = await token_store.get_bearer_token("int-get-bearer")

        assert result == plaintext, (
            f"get_bearer_token should return '{plaintext}', got {result!r}"
        )

    @patch("app.services.mcp.mcp_token_store.get_db_session")
    async def test_get_bearer_token_returns_none_for_unknown_key(
        self, mock_get_session, token_store
    ):
        """get_bearer_token must return None when no credential exists for the key."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=None)
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_get_session.return_value = _make_db_session_context(mock_session)

        result = await token_store.get_bearer_token("non-existent-integration")

        assert result is None, (
            "get_bearer_token must return None for an unknown integration_id"
        )

    @patch("app.services.mcp.mcp_token_store.get_db_session")
    async def test_token_expiry_bearer_disconnected_returns_none(
        self, mock_get_session, token_store
    ):
        """Bearer tokens whose credential has a non-CONNECTED status are not returned."""
        stale_cred = _make_bearer_credential(
            token_store, "int-stale", "stale-bearer-token"
        )
        stale_cred.status = MCPCredentialStatus.ERROR

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=stale_cred)
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_get_session.return_value = _make_db_session_context(mock_session)

        result = await token_store.get_bearer_token("int-stale")

        assert result is None, (
            "get_bearer_token must return None for a non-CONNECTED credential; "
            f"got {result!r} instead"
        )

    @patch("app.services.mcp.mcp_token_store.get_db_session")
    async def test_store_oauth_tokens(self, mock_get_session, token_store):
        """store_oauth_tokens writes access and refresh tokens.

        In mock context (TypeDecorator never runs) the Python-side objects
        retain plaintext values; real storage would transparently encrypt them.
        """
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=None)
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()
        mock_get_session.return_value = _make_db_session_context(mock_session)

        expires = datetime.now(timezone.utc) + timedelta(hours=1)
        await token_store.store_oauth_tokens(
            "integration-2",
            access_token="access-abc",
            refresh_token="refresh-xyz",
            expires_at=expires,
        )

        added_obj = mock_session.add.call_args[0][0]
        # In mock context values are plaintext (TypeDecorator not invoked).
        assert added_obj.access_token == "access-abc"
        assert added_obj.refresh_token == "refresh-xyz"

    @patch("app.services.mcp.mcp_token_store.get_db_session")
    async def test_get_oauth_token_returns_none_when_expired(
        self, mock_get_session, token_store
    ):
        """get_oauth_token should return None if the token has expired."""
        expired_cred = MagicMock()
        expired_cred.access_token = "expired-token"
        expired_cred.status = MCPCredentialStatus.CONNECTED
        expired_cred.auth_type = MCPAuthType.OAUTH
        # Set expired time (1 hour ago), naive UTC as stored in DB
        expired_cred.token_expires_at = (
            datetime.now(timezone.utc) - timedelta(hours=1)
        ).replace(tzinfo=None)

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=expired_cred)
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_get_session.return_value = _make_db_session_context(mock_session)

        result = await token_store.get_oauth_token("integration-expired")
        assert result is None

    @patch("app.services.mcp.mcp_token_store.get_db_session")
    async def test_delete_credentials(self, mock_get_session, token_store):
        """delete_credentials should remove the credential from the session."""
        mock_cred = MagicMock()
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=mock_cred)
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.delete = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_get_session.return_value = _make_db_session_context(mock_session)

        await token_store.delete_credentials("integration-del")

        mock_session.delete.assert_awaited_once_with(mock_cred)
        mock_session.commit.assert_awaited_once()

    @patch("app.services.mcp.mcp_token_store.set_cache", new_callable=AsyncMock)
    async def test_create_oauth_state(self, mock_set_cache, token_store):
        """create_oauth_state should store state and verifier in Redis."""
        state_token = await token_store.create_oauth_state("int-oauth", "verifier-abc")

        assert isinstance(state_token, str)
        assert len(state_token) > 0
        mock_set_cache.assert_awaited_once()
        call_args = mock_set_cache.call_args
        assert "verifier-abc" in str(call_args)

    @patch(
        "app.services.mcp.mcp_token_store.get_and_delete_cache",
        new_callable=AsyncMock,
    )
    async def test_verify_oauth_state_valid(self, mock_get_delete, token_store):
        """verify_oauth_state should return True and code_verifier for valid state."""
        mock_get_delete.return_value = {
            "state": "correct-state",
            "code_verifier": "my-verifier",
        }

        is_valid, verifier = await token_store.verify_oauth_state(
            "int-oauth", "correct-state"
        )

        assert is_valid is True
        assert verifier == "my-verifier"

    @patch(
        "app.services.mcp.mcp_token_store.get_and_delete_cache",
        new_callable=AsyncMock,
    )
    async def test_verify_oauth_state_invalid(self, mock_get_delete, token_store):
        """verify_oauth_state should return False for mismatched state."""
        mock_get_delete.return_value = {
            "state": "correct-state",
            "code_verifier": "my-verifier",
        }

        is_valid, verifier = await token_store.verify_oauth_state(
            "int-oauth", "wrong-state"
        )

        assert is_valid is False
        assert verifier is None

    @patch("app.services.mcp.mcp_token_store.get_db_session")
    async def test_delete_credentials_noop_when_not_found(
        self, mock_get_session, token_store
    ):
        """delete_credentials should not call delete or commit when no credential exists."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=None)
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.delete = AsyncMock()
        mock_session.commit = AsyncMock()

        context = AsyncMock()
        context.__aenter__ = AsyncMock(return_value=mock_session)
        context.__aexit__ = AsyncMock(return_value=False)
        mock_get_session.return_value = context

        await token_store.delete_credentials("integration-missing")

        mock_session.delete.assert_not_awaited()
        mock_session.commit.assert_not_awaited()

    @patch(
        "app.services.mcp.mcp_token_store.get_and_delete_cache",
        new_callable=AsyncMock,
    )
    async def test_verify_oauth_state_legacy_format(self, mock_get_delete, token_store):
        """verify_oauth_state should handle legacy plain-string state (no JSON dict)."""
        legacy_state = "legacy-state-token-xyz"
        mock_get_delete.return_value = legacy_state

        is_valid, verifier = await token_store.verify_oauth_state(
            "int-oauth", legacy_state
        )

        assert is_valid is True
        # Legacy format carries no code_verifier
        assert verifier is None

    @patch(
        "app.services.mcp.mcp_token_store.get_and_delete_cache",
        new_callable=AsyncMock,
    )
    async def test_verify_oauth_state_legacy_format_mismatch(
        self, mock_get_delete, token_store
    ):
        """verify_oauth_state should return False when legacy state does not match."""
        mock_get_delete.return_value = "legacy-state-token-xyz"

        is_valid, verifier = await token_store.verify_oauth_state(
            "int-oauth", "wrong-state"
        )

        assert is_valid is False
        assert verifier is None


@pytest.mark.integration
class TestGetBearerToken:
    """Test get_bearer_token filtering logic (auth_type, status, access_token)."""

    @patch("app.services.mcp.mcp_token_store.get_db_session")
    async def test_returns_decrypted_token_for_active_bearer(
        self, mock_get_session, token_store
    ):
        """get_bearer_token returns the token value for a healthy BEARER credential."""
        bearer_cred = MagicMock()
        bearer_cred.access_token = "my-bearer-secret"
        bearer_cred.status = MCPCredentialStatus.CONNECTED
        bearer_cred.auth_type = MCPAuthType.BEARER

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=bearer_cred)
        mock_session.execute = AsyncMock(return_value=mock_result)

        context = AsyncMock()
        context.__aenter__ = AsyncMock(return_value=mock_session)
        context.__aexit__ = AsyncMock(return_value=False)
        mock_get_session.return_value = context

        result = await token_store.get_bearer_token("integration-bearer")

        assert result == "my-bearer-secret"

    @patch("app.services.mcp.mcp_token_store.get_db_session")
    async def test_returns_none_for_wrong_auth_type(
        self, mock_get_session, token_store
    ):
        """get_bearer_token should return None when the stored credential is OAuth, not BEARER."""
        oauth_cred = MagicMock()
        oauth_cred.access_token = "oauth-access-token"
        oauth_cred.status = MCPCredentialStatus.CONNECTED
        oauth_cred.auth_type = MCPAuthType.OAUTH

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=oauth_cred)
        mock_session.execute = AsyncMock(return_value=mock_result)

        context = AsyncMock()
        context.__aenter__ = AsyncMock(return_value=mock_session)
        context.__aexit__ = AsyncMock(return_value=False)
        mock_get_session.return_value = context

        result = await token_store.get_bearer_token("integration-oauth")

        assert result is None

    @patch("app.services.mcp.mcp_token_store.get_db_session")
    async def test_returns_none_for_inactive_status(
        self, mock_get_session, token_store
    ):
        """get_bearer_token should return None when the credential status is not CONNECTED."""
        inactive_cred = MagicMock()
        inactive_cred.access_token = "my-bearer-secret"
        inactive_cred.status = MCPCredentialStatus.ERROR
        inactive_cred.auth_type = MCPAuthType.BEARER

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=inactive_cred)
        mock_session.execute = AsyncMock(return_value=mock_result)

        context = AsyncMock()
        context.__aenter__ = AsyncMock(return_value=mock_session)
        context.__aexit__ = AsyncMock(return_value=False)
        mock_get_session.return_value = context

        result = await token_store.get_bearer_token("integration-inactive")

        assert result is None
