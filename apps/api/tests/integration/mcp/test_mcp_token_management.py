"""Integration tests for MCP token storage and retrieval.

Tests the MCPTokenStore class with mocked PostgreSQL sessions and Redis
to verify encrypt/decrypt roundtrips, token storage, expiry checks,
and credential deletion.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cryptography.fernet import Fernet

from app.models.db_oauth import MCPAuthType, MCPCredential, MCPCredentialStatus
from app.services.mcp.mcp_token_store import MCPTokenStore


def _fernet_key() -> str:
    """Generate a valid Fernet key for testing."""
    return Fernet.generate_key().decode()


@pytest.fixture
def fernet_key():
    return _fernet_key()


@pytest.fixture
def token_store(fernet_key):
    """Create a MCPTokenStore with a valid Fernet key injected directly."""
    store = MCPTokenStore("test-user")
    # Inject cipher directly to bypass settings lookup
    store._cipher = Fernet(fernet_key.encode())
    return store


def _make_bearer_credential(
    token_store: MCPTokenStore, integration_id: str, plaintext: str
) -> MCPCredential:
    """Build an MCPCredential as store_bearer_token would, using the same cipher."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return MCPCredential(
        user_id=token_store.user_id,
        integration_id=integration_id,
        auth_type=MCPAuthType.BEARER,
        access_token=token_store._encrypt(plaintext),
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
    """Test token store encrypt/decrypt and credential lifecycle."""

    def test_encrypt_decrypt_roundtrip(self, token_store):
        """Encrypting then decrypting should return the original plaintext."""
        original = "my-secret-token-abc123"
        encrypted = token_store._encrypt(original)
        assert encrypted != original
        decrypted = token_store._decrypt(encrypted)
        assert decrypted == original

    def test_different_encryptions_produce_different_ciphertext(self, token_store):
        """Fernet produces unique ciphertext on each encryption call."""
        token = "same-token"
        enc1 = token_store._encrypt(token)
        enc2 = token_store._encrypt(token)
        assert enc1 != enc2  # Fernet uses a timestamp nonce

    @patch("app.services.mcp.mcp_token_store.get_db_session")
    async def test_store_and_get_bearer_token(self, mock_get_session, token_store):
        """store_bearer_token writes an encrypted credential that is non-plaintext."""
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
        # The stored token should be encrypted (not plaintext)
        assert added_obj.access_token != "bearer-secret-123"

    # ------------------------------------------------------------------
    # get_bearer_token retrieval tests — the path the old test never called
    # ------------------------------------------------------------------

    @patch("app.services.mcp.mcp_token_store.get_db_session")
    async def test_get_bearer_token_returns_stored_value(
        self, mock_get_session, token_store
    ):
        """get_bearer_token must decrypt and return the same value that was stored.

        This is the retrieval path that the previous test_store_and_get_bearer_token
        never exercised.  The mock DB returns a CONNECTED BEARER credential whose
        access_token was encrypted with the same cipher, and the method must
        return the original plaintext.
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
            f"get_bearer_token should decrypt to '{plaintext}', got {result!r}"
        )

    @patch("app.services.mcp.mcp_token_store.get_db_session")
    async def test_get_bearer_token_returns_none_for_unknown_key(
        self, mock_get_session, token_store
    ):
        """get_bearer_token must return None when no credential exists for the key.

        The production code calls get_credential() → None, then the guard
        `if cred and cred.access_token and ...` short-circuits to return None.
        This test ensures that branch is reached and produces None rather than
        raising an exception.
        """
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
        """Bearer tokens whose credential has a non-CONNECTED status are not returned.

        MCPTokenStore.get_bearer_token() checks ``cred.status ==
        MCPCredentialStatus.CONNECTED``.  A credential with status ERROR
        (or any other non-CONNECTED value) must be treated as absent so that
        a stale / revoked token is never forwarded to an MCP server.

        This models the 'expired-by-status' path: the credential exists in the
        DB but is no longer valid because the connection errored or the token
        was explicitly invalidated.
        """
        plaintext = "stale-bearer-token"
        stale_cred = _make_bearer_credential(token_store, "int-stale", plaintext)
        # Simulate a token that has been revoked / connection failed
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
        """store_oauth_tokens should encrypt both access and refresh tokens."""
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
        assert added_obj.access_token != "access-abc"
        assert added_obj.refresh_token != "refresh-xyz"
        # Decrypt to verify
        assert token_store._decrypt(added_obj.access_token) == "access-abc"
        assert token_store._decrypt(added_obj.refresh_token) == "refresh-xyz"

    @patch("app.services.mcp.mcp_token_store.get_db_session")
    async def test_get_oauth_token_returns_none_when_expired(
        self, mock_get_session, token_store
    ):
        """get_oauth_token should return None if the token has expired."""
        expired_cred = MagicMock()
        expired_cred.access_token = token_store._encrypt("expired-token")
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
        # Simulate a cache entry that is a raw string (legacy format before dict
        # storage was introduced).  json.loads on a bare state string would raise
        # JSONDecodeError, triggering the backwards-compat fallback path.
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
        """get_bearer_token should decrypt and return the token for a healthy BEARER credential."""
        bearer_cred = MagicMock()
        bearer_cred.access_token = token_store._encrypt("my-bearer-secret")
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
        oauth_cred.access_token = token_store._encrypt("oauth-access-token")
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
        inactive_cred.access_token = token_store._encrypt("my-bearer-secret")
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
