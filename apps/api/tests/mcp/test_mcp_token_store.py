"""
Unit tests for MCP Token Store.

Tests cover:
- OAuth token storage and retrieval
- Token encryption/decryption
- OAuth state management (CSRF protection)
- Token expiration checking
- DCR client storage
- OAuth discovery caching
- OIDC nonce storage
- Token introspection
"""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cryptography.fernet import Fernet

from app.services.mcp.mcp_token_store import MCPTokenStore

from .conftest import (
    MOCK_ACCESS_TOKEN,
    MOCK_INTEGRATION_ID,
    MOCK_REFRESH_TOKEN,
    MOCK_USER_ID,
    get_mock_dcr_response,
    get_mock_introspection_response,
)


# ==============================================================================
# Fixtures
# ==============================================================================


@pytest.fixture
def encryption_key():
    """Generate a valid Fernet encryption key."""
    return Fernet.generate_key().decode()


@pytest.fixture
def token_store(encryption_key):
    """Create a token store with mocked encryption key."""
    with patch("app.services.mcp.mcp_token_store.settings") as mock_settings:
        mock_settings.MCP_ENCRYPTION_KEY = encryption_key
        store = MCPTokenStore(user_id=MOCK_USER_ID)
        return store


@pytest.fixture
def mock_db_session():
    """Create a mock database session."""
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    return session


@pytest.fixture
def mock_redis():
    """Create mock Redis functions."""
    with (
        patch("app.services.mcp.mcp_token_store.get_cache") as mock_get,
        patch("app.services.mcp.mcp_token_store.set_cache") as mock_set,
        patch(
            "app.services.mcp.mcp_token_store.get_and_delete_cache"
        ) as mock_get_delete,
    ):
        yield {
            "get_cache": mock_get,
            "set_cache": mock_set,
            "get_and_delete_cache": mock_get_delete,
        }


# ==============================================================================
# Encryption Tests
# ==============================================================================


class TestEncryption:
    """Tests for encryption/decryption functionality."""

    def test_encrypt_decrypt_roundtrip(self, token_store):
        """Encrypted data should decrypt to original value."""
        original = "sensitive-token-data"
        encrypted = token_store._encrypt(original)
        decrypted = token_store._decrypt(encrypted)

        assert decrypted == original
        assert encrypted != original

    def test_different_data_produces_different_ciphertext(self, token_store):
        """Different data should produce different ciphertext."""
        encrypted1 = token_store._encrypt("token1")
        encrypted2 = token_store._encrypt("token2")

        assert encrypted1 != encrypted2

    def test_same_data_produces_different_ciphertext(self, token_store):
        """Same data should produce different ciphertext (due to IV)."""
        data = "same-token"
        encrypted1 = token_store._encrypt(data)
        encrypted2 = token_store._encrypt(data)

        # Fernet uses random IV, so ciphertexts should differ
        assert encrypted1 != encrypted2

    def test_missing_encryption_key_raises(self):
        """Should raise error when encryption key is not configured."""
        with patch("app.services.mcp.mcp_token_store.settings") as mock_settings:
            mock_settings.MCP_ENCRYPTION_KEY = None
            store = MCPTokenStore(user_id=MOCK_USER_ID)

            with pytest.raises(ValueError) as exc_info:
                store._encrypt("test")

            assert "MCP_ENCRYPTION_KEY" in str(exc_info.value)


# ==============================================================================
# OAuth Token Storage Tests
# ==============================================================================


class TestOAuthTokenStorage:
    """Tests for OAuth token storage and retrieval."""

    @pytest.mark.asyncio
    async def test_store_oauth_tokens(self, token_store, mock_db_session):
        """Should store encrypted OAuth tokens."""
        expires_at = datetime.now(timezone.utc) + timedelta(hours=1)

        with patch(
            "app.services.mcp.mcp_token_store.get_db_session",
            return_value=mock_db_session,
        ):
            # Mock no existing credential
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = None
            mock_db_session.execute.return_value = mock_result

            await token_store.store_oauth_tokens(
                integration_id=MOCK_INTEGRATION_ID,
                access_token=MOCK_ACCESS_TOKEN,
                refresh_token=MOCK_REFRESH_TOKEN,
                expires_at=expires_at,
            )

            # Verify session.add was called with credential
            assert mock_db_session.add.called
            assert mock_db_session.commit.called

    @pytest.mark.asyncio
    async def test_get_oauth_token_returns_decrypted(
        self, token_store, mock_db_session
    ):
        """Should return decrypted OAuth token."""
        encrypted_token = token_store._encrypt(MOCK_ACCESS_TOKEN)

        # Create mock credential
        mock_cred = MagicMock()
        mock_cred.access_token = encrypted_token
        mock_cred.status = "connected"
        mock_cred.token_expires_at = datetime.now(timezone.utc) + timedelta(hours=1)

        with patch(
            "app.services.mcp.mcp_token_store.get_db_session",
            return_value=mock_db_session,
        ):
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = mock_cred
            mock_db_session.execute.return_value = mock_result

            result = await token_store.get_oauth_token(MOCK_INTEGRATION_ID)

        assert result == MOCK_ACCESS_TOKEN

    @pytest.mark.asyncio
    async def test_get_oauth_token_returns_none_when_expired(
        self, token_store, mock_db_session
    ):
        """Should return None for expired tokens."""
        encrypted_token = token_store._encrypt(MOCK_ACCESS_TOKEN)

        mock_cred = MagicMock()
        mock_cred.access_token = encrypted_token
        mock_cred.status = "connected"
        mock_cred.token_expires_at = datetime.now(timezone.utc) - timedelta(hours=1)

        with patch(
            "app.services.mcp.mcp_token_store.get_db_session",
            return_value=mock_db_session,
        ):
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = mock_cred
            mock_db_session.execute.return_value = mock_result

            result = await token_store.get_oauth_token(MOCK_INTEGRATION_ID)

        assert result is None

    @pytest.mark.asyncio
    async def test_get_oauth_token_returns_none_when_not_connected(
        self, token_store, mock_db_session
    ):
        """Should return None when status is not 'connected'."""
        encrypted_token = token_store._encrypt(MOCK_ACCESS_TOKEN)

        mock_cred = MagicMock()
        mock_cred.access_token = encrypted_token
        mock_cred.status = "pending"  # Not connected
        mock_cred.token_expires_at = None

        with patch(
            "app.services.mcp.mcp_token_store.get_db_session",
            return_value=mock_db_session,
        ):
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = mock_cred
            mock_db_session.execute.return_value = mock_result

            result = await token_store.get_oauth_token(MOCK_INTEGRATION_ID)

        assert result is None


class TestTokenExpiration:
    """Tests for token expiration checking."""

    @pytest.mark.asyncio
    async def test_is_token_expiring_soon_returns_true(
        self, token_store, mock_db_session
    ):
        """Should return True when token expires within threshold."""
        mock_cred = MagicMock()
        mock_cred.token_expires_at = datetime.now(timezone.utc) + timedelta(minutes=2)

        with patch(
            "app.services.mcp.mcp_token_store.get_db_session",
            return_value=mock_db_session,
        ):
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = mock_cred
            mock_db_session.execute.return_value = mock_result

            # Default threshold is 300 seconds (5 minutes)
            result = await token_store.is_token_expiring_soon(MOCK_INTEGRATION_ID)

        assert result is True

    @pytest.mark.asyncio
    async def test_is_token_expiring_soon_returns_false(
        self, token_store, mock_db_session
    ):
        """Should return False when token has time remaining."""
        mock_cred = MagicMock()
        mock_cred.token_expires_at = datetime.now(timezone.utc) + timedelta(hours=1)

        with patch(
            "app.services.mcp.mcp_token_store.get_db_session",
            return_value=mock_db_session,
        ):
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = mock_cred
            mock_db_session.execute.return_value = mock_result

            result = await token_store.is_token_expiring_soon(MOCK_INTEGRATION_ID)

        assert result is False


# ==============================================================================
# OAuth State (CSRF Protection) Tests
# ==============================================================================


class TestOAuthState:
    """Tests for OAuth state management."""

    @pytest.mark.asyncio
    async def test_create_oauth_state(self, token_store, mock_redis):
        """Should create and store OAuth state with code_verifier."""
        mock_redis["set_cache"].return_value = None

        state = await token_store.create_oauth_state(
            MOCK_INTEGRATION_ID, "test-code-verifier"
        )

        assert state is not None
        assert len(state) > 20  # Should be sufficiently random
        mock_redis["set_cache"].assert_called_once()

    @pytest.mark.asyncio
    async def test_verify_oauth_state_valid(self, token_store, mock_redis):
        """Should verify valid OAuth state."""
        stored_data = json.dumps(
            {
                "state": "test-state-token",
                "code_verifier": "test-code-verifier",
            }
        )
        mock_redis["get_and_delete_cache"].return_value = stored_data

        is_valid, code_verifier = await token_store.verify_oauth_state(
            MOCK_INTEGRATION_ID, "test-state-token"
        )

        assert is_valid is True
        assert code_verifier == "test-code-verifier"

    @pytest.mark.asyncio
    async def test_verify_oauth_state_invalid(self, token_store, mock_redis):
        """Should reject invalid OAuth state."""
        stored_data = json.dumps(
            {
                "state": "correct-state",
                "code_verifier": "test-code-verifier",
            }
        )
        mock_redis["get_and_delete_cache"].return_value = stored_data

        is_valid, code_verifier = await token_store.verify_oauth_state(
            MOCK_INTEGRATION_ID, "wrong-state"
        )

        assert is_valid is False
        assert code_verifier is None

    @pytest.mark.asyncio
    async def test_verify_oauth_state_expired(self, token_store, mock_redis):
        """Should reject expired OAuth state (not found in Redis)."""
        mock_redis["get_and_delete_cache"].return_value = None

        is_valid, code_verifier = await token_store.verify_oauth_state(
            MOCK_INTEGRATION_ID, "any-state"
        )

        assert is_valid is False
        assert code_verifier is None


# ==============================================================================
# DCR Client Storage Tests
# ==============================================================================


class TestDCRClientStorage:
    """Tests for Dynamic Client Registration storage."""

    @pytest.mark.asyncio
    async def test_store_dcr_client(self, token_store, mock_db_session):
        """Should store DCR client registration data."""
        dcr_data = get_mock_dcr_response()

        with patch(
            "app.services.mcp.mcp_token_store.get_db_session",
            return_value=mock_db_session,
        ):
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = None
            mock_db_session.execute.return_value = mock_result

            await token_store.store_dcr_client(MOCK_INTEGRATION_ID, dcr_data)

            assert mock_db_session.add.called
            assert mock_db_session.commit.called

    @pytest.mark.asyncio
    async def test_get_dcr_client(self, token_store, mock_db_session):
        """Should retrieve DCR client registration data."""
        dcr_data = get_mock_dcr_response()

        mock_cred = MagicMock()
        mock_cred.client_registration = json.dumps(dcr_data)

        with patch(
            "app.services.mcp.mcp_token_store.get_db_session",
            return_value=mock_db_session,
        ):
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = mock_cred
            mock_db_session.execute.return_value = mock_result

            result = await token_store.get_dcr_client(MOCK_INTEGRATION_ID)

        assert result["client_id"] == dcr_data["client_id"]


# ==============================================================================
# OAuth Discovery Caching Tests
# ==============================================================================


class TestOAuthDiscoveryCache:
    """Tests for OAuth discovery caching."""

    @pytest.mark.asyncio
    async def test_store_oauth_discovery(self, token_store, mock_redis):
        """Should cache OAuth discovery data."""
        discovery = {
            "authorization_endpoint": "https://auth.example.com/authorize",
            "token_endpoint": "https://auth.example.com/token",
        }

        mock_redis["set_cache"].return_value = None

        await token_store.store_oauth_discovery(MOCK_INTEGRATION_ID, discovery)

        mock_redis["set_cache"].assert_called_once()
        call_args = mock_redis["set_cache"].call_args
        assert MOCK_INTEGRATION_ID in call_args[0][0]

    @pytest.mark.asyncio
    async def test_get_oauth_discovery_cached(self, token_store, mock_redis):
        """Should retrieve cached OAuth discovery data."""
        discovery = {
            "authorization_endpoint": "https://auth.example.com/authorize",
            "token_endpoint": "https://auth.example.com/token",
        }
        mock_redis["get_cache"].return_value = json.dumps(discovery)

        result = await token_store.get_oauth_discovery(MOCK_INTEGRATION_ID)

        assert result["authorization_endpoint"] == discovery["authorization_endpoint"]

    @pytest.mark.asyncio
    async def test_get_oauth_discovery_not_cached(self, token_store, mock_redis):
        """Should return None when discovery not cached."""
        mock_redis["get_cache"].return_value = None

        result = await token_store.get_oauth_discovery(MOCK_INTEGRATION_ID)

        assert result is None


# ==============================================================================
# OIDC Nonce Storage Tests
# ==============================================================================


class TestOIDCNonceStorage:
    """Tests for OIDC nonce storage."""

    @pytest.mark.asyncio
    async def test_store_oauth_nonce(self, token_store, mock_redis):
        """Should store OIDC nonce in Redis."""
        mock_redis["set_cache"].return_value = None

        await token_store.store_oauth_nonce(MOCK_INTEGRATION_ID, "test-nonce")

        mock_redis["set_cache"].assert_called_once()
        call_args = mock_redis["set_cache"].call_args
        assert "nonce" in call_args[0][0]
        assert call_args[0][1] == "test-nonce"

    @pytest.mark.asyncio
    async def test_get_and_delete_oauth_nonce(self, token_store, mock_redis):
        """Should retrieve and delete OIDC nonce."""
        mock_redis["get_and_delete_cache"].return_value = "test-nonce"

        result = await token_store.get_and_delete_oauth_nonce(MOCK_INTEGRATION_ID)

        assert result == "test-nonce"
        mock_redis["get_and_delete_cache"].assert_called_once()


# ==============================================================================
# Token Introspection Tests
# ==============================================================================


class TestTokenIntrospection:
    """Tests for token introspection via token store."""

    @pytest.mark.asyncio
    async def test_introspect_token_active(
        self, token_store, mock_redis, mock_db_session
    ):
        """Should return introspection response for active token."""
        discovery = {
            "introspection_endpoint": "https://auth.example.com/introspect",
        }
        mock_redis["get_cache"].return_value = json.dumps(discovery)

        encrypted_token = token_store._encrypt(MOCK_ACCESS_TOKEN)
        mock_cred = MagicMock()
        mock_cred.access_token = encrypted_token
        mock_cred.status = "connected"
        mock_cred.token_expires_at = None

        introspection_response = get_mock_introspection_response(active=True)

        with patch(
            "app.services.mcp.mcp_token_store.get_db_session",
            return_value=mock_db_session,
        ):
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = mock_cred
            mock_db_session.execute.return_value = mock_result

            with patch(
                "app.utils.mcp_oauth_utils.introspect_token",
                new_callable=AsyncMock,
                return_value=introspection_response,
            ):
                result = await token_store.introspect_token(MOCK_INTEGRATION_ID)

        assert result is not None
        assert result["active"] is True

    @pytest.mark.asyncio
    async def test_introspect_token_no_endpoint(self, token_store, mock_redis):
        """Should return None when no introspection endpoint available."""
        discovery = {
            "authorization_endpoint": "https://auth.example.com/authorize",
            # No introspection_endpoint
        }
        mock_redis["get_cache"].return_value = json.dumps(discovery)

        result = await token_store.introspect_token(MOCK_INTEGRATION_ID)

        assert result is None


# ==============================================================================
# Credential Deletion Tests
# ==============================================================================


class TestCredentialDeletion:
    """Tests for credential deletion."""

    @pytest.mark.asyncio
    async def test_delete_credentials(self, token_store, mock_db_session):
        """Should delete credentials from database."""
        mock_cred = MagicMock()

        with patch(
            "app.services.mcp.mcp_token_store.get_db_session",
            return_value=mock_db_session,
        ):
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = mock_cred
            mock_db_session.execute.return_value = mock_result

            await token_store.delete_credentials(MOCK_INTEGRATION_ID)

            mock_db_session.delete.assert_called_once_with(mock_cred)
            mock_db_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_credentials_not_found(self, token_store, mock_db_session):
        """Should handle deletion when credentials don't exist."""
        with patch(
            "app.services.mcp.mcp_token_store.get_db_session",
            return_value=mock_db_session,
        ):
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = None
            mock_db_session.execute.return_value = mock_result

            # Should not raise
            await token_store.delete_credentials(MOCK_INTEGRATION_ID)

            mock_db_session.delete.assert_not_called()
