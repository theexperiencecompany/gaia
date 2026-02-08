"""
MCP Token Store - PostgreSQL-based credential storage.

Stores MCP credentials encrypted in PostgreSQL instead of filesystem.
Follows same patterns as Composio for parity.
"""

import json
import secrets
from datetime import datetime, timezone
from typing import Optional

from app.config.loggers import langchain_logger as logger
from app.config.settings import settings
from app.constants.cache import (
    OAUTH_DISCOVERY_PREFIX,
    OAUTH_DISCOVERY_TTL,
    OAUTH_STATE_PREFIX,
    OAUTH_STATE_TTL,
)
from app.db.postgresql import get_db_session
from app.db.redis import delete_cache, get_and_delete_cache, get_cache, set_cache
from app.models.db_oauth import MCPAuthType, MCPCredential, MCPCredentialStatus
from app.utils.mcp_oauth_utils import introspect_token as do_introspect
from cryptography.fernet import Fernet
from sqlalchemy import select


class MCPTokenStore:
    """PostgreSQL-based token storage for MCP credentials."""

    def __init__(self, user_id: str):
        self.user_id = user_id
        self._cipher: Optional[Fernet] = None

    def _get_cipher(self) -> Fernet:
        """Get Fernet cipher from Infisical secret (lazy init)."""
        if self._cipher is None:
            key = getattr(settings, "MCP_ENCRYPTION_KEY", None)
            if not key:
                raise ValueError("MCP_ENCRYPTION_KEY not configured in Infisical")
            try:
                # Fernet expects a URL-safe base64-encoded 32-byte key
                self._cipher = Fernet(key.encode())
            except Exception as e:
                raise ValueError(
                    f"MCP_ENCRYPTION_KEY is not a valid Fernet key (must be 32 url-safe base64-encoded bytes): {e}"
                )
        return self._cipher

    def _encrypt(self, data: str) -> str:
        """Encrypt sensitive data."""
        return self._get_cipher().encrypt(data.encode()).decode()

    def _decrypt(self, data: str) -> str:
        """Decrypt sensitive data."""
        return self._get_cipher().decrypt(data.encode()).decode()

    async def get_credential(self, integration_id: str) -> Optional[MCPCredential]:
        """Get stored credential for integration."""
        async with get_db_session() as session:
            result = await session.execute(
                select(MCPCredential).where(
                    MCPCredential.user_id == self.user_id,
                    MCPCredential.integration_id == integration_id,
                )
            )
            return result.scalar_one_or_none()

    async def get_bearer_token(self, integration_id: str) -> Optional[str]:
        """Get decrypted bearer token."""
        cred = await self.get_credential(integration_id)
        if (
            cred
            and cred.access_token
            and cred.status == MCPCredentialStatus.CONNECTED
            and cred.auth_type == MCPAuthType.BEARER
        ):
            return self._decrypt(cred.access_token)
        return None

    async def get_oauth_token(self, integration_id: str) -> Optional[str]:
        """Get decrypted OAuth access token if not expired."""
        cred = await self.get_credential(integration_id)
        if not cred:
            logger.debug(f"[{integration_id}] No credential record found in DB")
            return None

        if not cred.access_token:
            logger.debug(f"[{integration_id}] Credential exists but no access_token")
            return None

        if cred.status != MCPCredentialStatus.CONNECTED:
            logger.debug(
                f"[{integration_id}] Credential status is '{cred.status}', expected 'connected'"
            )
            return None

        # Check if token is expired
        # Note: token_expires_at is stored as naive UTC in PostgreSQL TIMESTAMP WITHOUT TIME ZONE
        # We compare with naive UTC for consistency
        if cred.token_expires_at:
            now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
            if cred.token_expires_at < now_utc:
                logger.warning(f"OAuth token expired for {integration_id}")
                return None

        logger.debug(f"[{integration_id}] Returning decrypted OAuth token")
        return self._decrypt(cred.access_token)

    async def get_refresh_token(self, integration_id: str) -> Optional[str]:
        """Get decrypted refresh token."""
        cred = await self.get_credential(integration_id)
        if cred and cred.refresh_token:
            return self._decrypt(cred.refresh_token)
        return None

    async def is_token_expiring_soon(
        self, integration_id: str, threshold_seconds: int = 300
    ) -> bool:
        """Check if token expires within threshold (default 5 minutes)."""
        cred = await self.get_credential(integration_id)
        if cred and cred.token_expires_at:
            from datetime import timedelta

            # Use naive UTC for comparison with stored naive timestamps
            expiry_threshold = (
                datetime.now(timezone.utc) + timedelta(seconds=threshold_seconds)
            ).replace(tzinfo=None)
            return cred.token_expires_at < expiry_threshold
        return False

    async def store_bearer_token(self, integration_id: str, token: str) -> None:
        """Store encrypted bearer token."""
        encrypted = self._encrypt(token)
        # Use naive UTC datetime for PostgreSQL TIMESTAMP WITHOUT TIME ZONE column
        now = datetime.now(timezone.utc).replace(tzinfo=None)

        async with get_db_session() as session:
            # Query within this session
            result = await session.execute(
                select(MCPCredential).where(
                    MCPCredential.user_id == self.user_id,
                    MCPCredential.integration_id == integration_id,
                )
            )
            cred: Optional[MCPCredential] = result.scalar_one_or_none()

            if cred:
                cred.access_token = encrypted
                cred.status = MCPCredentialStatus.CONNECTED
                cred.connected_at = now
                cred.error_message = None
                session.add(cred)
            else:
                cred = MCPCredential(
                    user_id=self.user_id,
                    integration_id=integration_id,
                    auth_type=MCPAuthType.BEARER,
                    access_token=encrypted,
                    status=MCPCredentialStatus.CONNECTED,
                    connected_at=now,
                )
                session.add(cred)
            await session.commit()
            logger.info(f"Stored bearer token for {integration_id}")

    async def store_oauth_tokens(
        self,
        integration_id: str,
        access_token: str,
        refresh_token: Optional[str] = None,
        expires_at: Optional[datetime] = None,
    ) -> None:
        """Store encrypted OAuth tokens."""
        encrypted_access = self._encrypt(access_token)
        encrypted_refresh = self._encrypt(refresh_token) if refresh_token else None
        # Use naive UTC datetime for PostgreSQL TIMESTAMP WITHOUT TIME ZONE column
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        # Also strip timezone from expires_at if provided
        naive_expires_at = expires_at.replace(tzinfo=None) if expires_at else None

        async with get_db_session() as session:
            # Query within this session
            result = await session.execute(
                select(MCPCredential).where(
                    MCPCredential.user_id == self.user_id,
                    MCPCredential.integration_id == integration_id,
                )
            )
            cred: Optional[MCPCredential] = result.scalar_one_or_none()

            if cred:
                cred.access_token = encrypted_access
                cred.refresh_token = encrypted_refresh
                cred.token_expires_at = naive_expires_at
                # Set status to connected so get_oauth_token() can retrieve it
                cred.status = MCPCredentialStatus.CONNECTED
                cred.connected_at = now
                session.add(cred)
            else:
                cred = MCPCredential(
                    user_id=self.user_id,
                    integration_id=integration_id,
                    auth_type=MCPAuthType.OAUTH,
                    access_token=encrypted_access,
                    refresh_token=encrypted_refresh,
                    token_expires_at=naive_expires_at,
                    status=MCPCredentialStatus.CONNECTED,  # Required for get_oauth_token() to work
                    connected_at=now,
                )
                session.add(cred)
            await session.commit()
            logger.info(f"Stored OAuth tokens for {integration_id}")

    async def store_unauthenticated(self, integration_id: str) -> None:
        """Store connection for unauthenticated MCP.

        Creates a credential record to track that this integration exists.
        Connection status is managed in MongoDB user_integrations, not here.
        """
        async with get_db_session() as session:
            # Query within this session
            result = await session.execute(
                select(MCPCredential).where(
                    MCPCredential.user_id == self.user_id,
                    MCPCredential.integration_id == integration_id,
                )
            )
            cred = result.scalar_one_or_none()

            if not cred:
                # Only create if doesn't exist - no status updates needed
                cred = MCPCredential(
                    user_id=self.user_id,
                    integration_id=integration_id,
                    auth_type=MCPAuthType.NONE,
                    status=MCPCredentialStatus.CONNECTED,  # Ready to use immediately
                )
                session.add(cred)
                await session.commit()
                logger.info(
                    f"Created credential record for unauthenticated {integration_id}"
                )

    async def create_oauth_state(self, integration_id: str, code_verifier: str) -> str:
        """
        Create OAuth state for CSRF protection.

        Stores state and PKCE code_verifier in Redis with TTL.
        Returns the state token to include in OAuth URL.

        Note: Connection status is managed in MongoDB user_integrations.
        PostgreSQL only stores the PKCE state for the OAuth flow.
        """
        state = secrets.token_urlsafe(32)

        # Store state and code_verifier together in Redis
        # IMPORTANT: Pass dict directly - set_cache handles serialization via TypeAdapter.
        # Pre-serializing with json.dumps() causes double-encoding, breaking code_verifier retrieval.
        cache_key = f"{OAUTH_STATE_PREFIX}:{self.user_id}:{integration_id}"
        state_data = {"state": state, "code_verifier": code_verifier}
        await set_cache(cache_key, state_data, ttl=OAUTH_STATE_TTL)

        return state

    async def verify_oauth_state(
        self, integration_id: str, state: str
    ) -> tuple[bool, Optional[str]]:
        """
        Verify OAuth state matches stored state.

        Uses atomic get-and-delete to prevent replay attacks (Issue 5.2 fix).
        Returns (is_valid, code_verifier) tuple.
        """
        cache_key = f"{OAUTH_STATE_PREFIX}:{self.user_id}:{integration_id}"
        # Atomic get-and-delete prevents race condition where two callbacks
        # could both validate before either deletes the state
        stored_data = await get_and_delete_cache(cache_key)

        if not stored_data:
            return False, None

        try:
            if isinstance(stored_data, dict):
                data = stored_data
            else:
                data = json.loads(stored_data)
            stored_state = data.get("state")
            code_verifier = data.get("code_verifier")
        except (json.JSONDecodeError, TypeError):
            # Legacy format - just state string (backwards compat)
            stored_state = stored_data
            code_verifier = None

        if stored_state and stored_state == state:
            return True, code_verifier
        return False, None

    async def delete_credentials(self, integration_id: str) -> None:
        """Delete credentials for integration (disconnect)."""
        async with get_db_session() as session:
            result = await session.execute(
                select(MCPCredential).where(
                    MCPCredential.user_id == self.user_id,
                    MCPCredential.integration_id == integration_id,
                )
            )
            cred = result.scalar_one_or_none()
            if cred:
                await session.delete(cred)
                await session.commit()
                logger.info(f"Deleted MCP credentials for {integration_id}")

    async def update_status(
        self,
        integration_id: str,
        status: MCPCredentialStatus,
        error: Optional[str] = None,
    ) -> None:
        """Update PostgreSQL credential status (informational only).

        NOTE: Connection status is managed in MongoDB user_integrations.
        This method only updates the PostgreSQL status field for debugging/auditing.
        Use update_user_integration_status() to change the canonical connection status.
        """
        async with get_db_session() as session:
            result = await session.execute(
                select(MCPCredential).where(
                    MCPCredential.user_id == self.user_id,
                    MCPCredential.integration_id == integration_id,
                )
            )
            cred: Optional[MCPCredential] = result.scalar_one_or_none()
            if cred:
                cred.status = MCPCredentialStatus(status)
                cred.error_message = error
                session.add(cred)
                await session.commit()

    async def has_credentials(self, integration_id: str) -> bool:
        """Check if we have stored tokens/credentials for this integration.

        Note: This checks for token existence, NOT connection status.
        Connection status is managed in MongoDB user_integrations.
        """
        cred = await self.get_credential(integration_id)
        return cred is not None and cred.access_token is not None

    async def is_connected(self, integration_id: str) -> bool:
        """Check if user has a connected credential for this integration.

        Returns True if credential exists and has 'connected' status.
        """
        cred = await self.get_credential(integration_id)
        return cred is not None and cred.status == MCPCredentialStatus.CONNECTED

    async def get_integrations_with_credentials(self) -> list[str]:
        """Get all MCP integration IDs that have stored credentials.

        Note: This returns integrations with tokens, NOT necessarily connected.
        Connection status is managed in MongoDB user_integrations.
        """
        async with get_db_session() as session:
            result = await session.execute(
                select(MCPCredential.integration_id).where(
                    MCPCredential.user_id == self.user_id,
                    MCPCredential.access_token.isnot(None),
                )
            )
            return [row[0] for row in result.fetchall()]

    async def get_dcr_client(self, integration_id: str) -> Optional[dict]:
        """Get stored DCR client registration."""
        cred = await self.get_credential(integration_id)
        if cred and cred.client_registration:
            try:
                return json.loads(cred.client_registration)
            except json.JSONDecodeError:
                return None
        return None

    async def store_dcr_client(self, integration_id: str, dcr_data: dict) -> None:
        """Store DCR client registration from dynamic registration."""
        async with get_db_session() as session:
            result = await session.execute(
                select(MCPCredential).where(
                    MCPCredential.user_id == self.user_id,
                    MCPCredential.integration_id == integration_id,
                )
            )
            cred = result.scalar_one_or_none()

            if cred:
                cred.client_registration = json.dumps(dcr_data)
                session.add(cred)
            else:
                cred = MCPCredential(
                    user_id=self.user_id,
                    integration_id=integration_id,
                    auth_type=MCPAuthType.OAUTH,
                    status=MCPCredentialStatus.PENDING,
                    client_registration=json.dumps(dcr_data),
                )
                session.add(cred)
            await session.commit()
            logger.info(f"Stored DCR client for {integration_id}")

    async def store_oauth_discovery(self, integration_id: str, discovery: dict) -> None:
        """
        Cache OAuth discovery data in Redis.

        NOTE: This cache is GLOBAL per integration, not per-user. The key is:
        `mcp_oauth_discovery:{integration_id}` (no user_id component).

        This is intentional because OAuth discovery data (authorization_endpoint,
        token_endpoint, registration_endpoint, etc.) is the same for all users
        connecting to the same MCP server. User-specific data like DCR client_id
        is stored separately in PostgreSQL per user.

        TTL: 24 hours (OAuth metadata changes infrequently)
        """
        cache_key = f"{OAUTH_DISCOVERY_PREFIX}:{integration_id}"
        # Pass dict directly - set_cache handles serialization
        await set_cache(cache_key, discovery, ttl=OAUTH_DISCOVERY_TTL)
        logger.info(f"Cached OAuth discovery for {integration_id}")

    async def get_oauth_discovery(self, integration_id: str) -> Optional[dict]:
        """Get cached OAuth discovery data from Redis."""
        cache_key = f"{OAUTH_DISCOVERY_PREFIX}:{integration_id}"
        # get_cache already deserializes via TypeAdapter, returning dict directly
        cached = await get_cache(cache_key)
        if cached and isinstance(cached, dict):
            return cached
        return None

    async def store_oauth_nonce(self, integration_id: str, nonce: str) -> None:
        """
        Store OIDC nonce for validation in callback.

        Per OpenID Connect spec, the nonce is used to associate a client session
        with an ID Token and to mitigate replay attacks.

        TTL: Same as OAuth state (10 minutes)
        """
        cache_key = f"mcp_oauth_nonce:{self.user_id}:{integration_id}"
        await set_cache(cache_key, nonce, ttl=OAUTH_STATE_TTL)
        logger.debug(f"Stored OIDC nonce for {integration_id}")

    async def get_and_delete_oauth_nonce(self, integration_id: str) -> Optional[str]:
        """
        Get and delete OIDC nonce (atomic operation).

        Returns the nonce if found, None otherwise.
        """
        cache_key = f"mcp_oauth_nonce:{self.user_id}:{integration_id}"
        return await get_and_delete_cache(cache_key)

    async def introspect_token(
        self,
        integration_id: str,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
    ) -> Optional[dict]:
        """
        Introspect token at authorization server per RFC 7662.

        Returns introspection response with 'active' field, or None if failed.
        """
        oauth_config = await self.get_oauth_discovery(integration_id)
        if not oauth_config:
            return None

        introspection_endpoint = oauth_config.get("introspection_endpoint")
        if not introspection_endpoint:
            return None

        access_token = await self.get_oauth_token(integration_id)
        if not access_token:
            return None

        return await do_introspect(
            introspection_endpoint=introspection_endpoint,
            token=access_token,
            token_type_hint="access_token",  # nosec B106 - OAuth token type hint, not a password
            client_id=client_id,
            client_secret=client_secret,
        )

    async def delete_oauth_discovery(self, integration_id: str) -> bool:
        """
        Delete OAuth discovery cache for an integration.

        Use this to force re-discovery of OAuth endpoints, for example
        when the auth server configuration has changed.

        Returns True if cache was deleted, False if not found.
        """
        cache_key = f"{OAUTH_DISCOVERY_PREFIX}:{integration_id}"
        result = await delete_cache(cache_key)
        if result:
            logger.info(f"Deleted OAuth discovery cache for {integration_id}")
        return result or False

    async def cleanup_integration(self, integration_id: str) -> None:
        """
        Clean up all OAuth-related data for an integration.

        This removes:
        - OAuth discovery cache (Redis)
        - Stored credentials (PostgreSQL)

        Use when an integration is removed or when OAuth needs to be reset.
        """
        # Delete discovery cache
        await self.delete_oauth_discovery(integration_id)

        # Delete stored credentials
        await self.delete_credentials(integration_id)

        logger.info(f"Cleaned up all OAuth data for {integration_id}")
