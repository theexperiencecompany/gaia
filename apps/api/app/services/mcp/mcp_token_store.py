"""
MCP Token Store - PostgreSQL-based credential storage.

Stores MCP credentials encrypted in PostgreSQL instead of filesystem.
Follows same patterns as Composio for parity.
"""

import json
import secrets
from datetime import datetime
from typing import Optional

from cryptography.fernet import Fernet
from sqlalchemy import select

from app.config.loggers import langchain_logger as logger
from app.config.settings import settings
from app.db.postgresql import get_db_session
from app.db.redis import delete_cache, get_cache, set_cache
from app.models.oauth_models import MCPCredential

# Redis key prefixes
OAUTH_STATE_PREFIX = "mcp_oauth_state"
OAUTH_STATE_TTL = 600  # 10 minutes
OAUTH_DISCOVERY_PREFIX = "mcp_oauth_discovery"
OAUTH_DISCOVERY_TTL = 86400  # 24 hours - discovery data doesn't change often


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
            self._cipher = Fernet(key.encode())
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
        if cred and cred.access_token and cred.status == "connected":
            return self._decrypt(cred.access_token)
        return None

    async def get_oauth_token(self, integration_id: str) -> Optional[str]:
        """Get decrypted OAuth access token."""
        cred = await self.get_credential(integration_id)
        if cred and cred.access_token and cred.status == "connected":
            return self._decrypt(cred.access_token)
        return None

    async def store_bearer_token(self, integration_id: str, token: str) -> None:
        """Store encrypted bearer token."""
        encrypted = self._encrypt(token)
        now = datetime.utcnow()

        async with get_db_session() as session:
            # Query within this session
            result = await session.execute(
                select(MCPCredential).where(
                    MCPCredential.user_id == self.user_id,
                    MCPCredential.integration_id == integration_id,
                )
            )
            cred = result.scalar_one_or_none()

            if cred:
                cred.access_token = encrypted
                cred.status = "connected"
                cred.connected_at = now
                cred.error_message = None
                session.add(cred)
            else:
                cred = MCPCredential(
                    user_id=self.user_id,
                    integration_id=integration_id,
                    auth_type="bearer",
                    access_token=encrypted,
                    status="connected",
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
        client_registration: Optional[dict] = None,
    ) -> None:
        """Store encrypted OAuth tokens."""
        encrypted_access = self._encrypt(access_token)
        encrypted_refresh = self._encrypt(refresh_token) if refresh_token else None
        now = datetime.utcnow()

        async with get_db_session() as session:
            # Query within this session
            result = await session.execute(
                select(MCPCredential).where(
                    MCPCredential.user_id == self.user_id,
                    MCPCredential.integration_id == integration_id,
                )
            )
            cred = result.scalar_one_or_none()

            if cred:
                cred.access_token = encrypted_access
                cred.refresh_token = encrypted_refresh
                cred.token_expires_at = expires_at
                cred.status = "connected"
                cred.connected_at = now
                cred.error_message = None
                if client_registration:
                    cred.client_registration = json.dumps(client_registration)
                session.add(cred)
            else:
                cred = MCPCredential(
                    user_id=self.user_id,
                    integration_id=integration_id,
                    auth_type="oauth",
                    access_token=encrypted_access,
                    refresh_token=encrypted_refresh,
                    token_expires_at=expires_at,
                    status="connected",
                    connected_at=now,
                    client_registration=json.dumps(client_registration)
                    if client_registration
                    else None,
                )
                session.add(cred)
            await session.commit()
            logger.info(f"Stored OAuth tokens for {integration_id}")

    async def store_unauthenticated(self, integration_id: str) -> None:
        """Store connection for unauthenticated MCP (just marks as connected)."""
        now = datetime.utcnow()

        async with get_db_session() as session:
            # Query within this session
            result = await session.execute(
                select(MCPCredential).where(
                    MCPCredential.user_id == self.user_id,
                    MCPCredential.integration_id == integration_id,
                )
            )
            cred = result.scalar_one_or_none()

            if cred:
                cred.status = "connected"
                cred.connected_at = now
                cred.error_message = None
                session.add(cred)
            else:
                cred = MCPCredential(
                    user_id=self.user_id,
                    integration_id=integration_id,
                    auth_type="none",
                    status="connected",
                    connected_at=now,
                )
                session.add(cred)
            await session.commit()
            logger.info(f"Stored unauthenticated connection for {integration_id}")

    async def create_oauth_state(self, integration_id: str, code_verifier: str) -> str:
        """
        Create OAuth state for CSRF protection.

        Stores state and PKCE code_verifier in Redis with TTL.
        Returns the state token to include in OAuth URL.
        """
        state = secrets.token_urlsafe(32)

        # Store state and code_verifier together in Redis
        cache_key = f"{OAUTH_STATE_PREFIX}:{self.user_id}:{integration_id}"
        state_data = json.dumps({"state": state, "code_verifier": code_verifier})
        await set_cache(cache_key, state_data, ttl=OAUTH_STATE_TTL)

        # Also mark the credential as pending
        async with get_db_session() as session:
            result = await session.execute(
                select(MCPCredential).where(
                    MCPCredential.user_id == self.user_id,
                    MCPCredential.integration_id == integration_id,
                )
            )
            cred = result.scalar_one_or_none()

            if cred:
                cred.status = "pending"
                session.add(cred)
            else:
                cred = MCPCredential(
                    user_id=self.user_id,
                    integration_id=integration_id,
                    auth_type="oauth",
                    status="pending",
                )
                session.add(cred)
            await session.commit()

        return state

    async def verify_oauth_state(
        self, integration_id: str, state: str
    ) -> tuple[bool, Optional[str]]:
        """
        Verify OAuth state matches stored state.

        Retrieves from Redis and deletes after verification (one-time use).
        Returns (is_valid, code_verifier) tuple.
        """
        cache_key = f"{OAUTH_STATE_PREFIX}:{self.user_id}:{integration_id}"
        stored_data = await get_cache(cache_key)

        if not stored_data:
            return False, None

        try:
            data = json.loads(stored_data)
            stored_state = data.get("state")
            code_verifier = data.get("code_verifier")
        except (json.JSONDecodeError, TypeError):
            # Legacy format - just state string (backwards compat)
            stored_state = stored_data
            code_verifier = None

        if stored_state and stored_state == state:
            # Delete after successful verification (one-time use)
            await delete_cache(cache_key)
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
        status: str,
        error: Optional[str] = None,
    ) -> None:
        """Update integration connection status."""
        async with get_db_session() as session:
            result = await session.execute(
                select(MCPCredential).where(
                    MCPCredential.user_id == self.user_id,
                    MCPCredential.integration_id == integration_id,
                )
            )
            cred = result.scalar_one_or_none()
            if cred:
                cred.status = status
                cred.error_message = error
                session.add(cred)
                await session.commit()

    async def is_connected(self, integration_id: str) -> bool:
        """Check if integration is connected."""
        cred = await self.get_credential(integration_id)
        return cred is not None and cred.status == "connected"

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
                    auth_type="oauth",
                    status="pending",
                    client_registration=json.dumps(dcr_data),
                )
                session.add(cred)
            await session.commit()
            logger.info(f"Stored DCR client for {integration_id}")

    async def store_oauth_discovery(self, integration_id: str, discovery: dict) -> None:
        """Cache OAuth discovery data in Redis."""
        cache_key = f"{OAUTH_DISCOVERY_PREFIX}:{integration_id}"
        await set_cache(cache_key, json.dumps(discovery), ttl=OAUTH_DISCOVERY_TTL)
        logger.info(f"Cached OAuth discovery for {integration_id}")

    async def get_oauth_discovery(self, integration_id: str) -> Optional[dict]:
        """Get cached OAuth discovery data from Redis."""
        cache_key = f"{OAUTH_DISCOVERY_PREFIX}:{integration_id}"
        cached = await get_cache(cache_key)
        if cached:
            try:
                return json.loads(cached)
            except json.JSONDecodeError:
                return None
        return None
