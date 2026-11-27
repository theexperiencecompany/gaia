"""
MCP Token Store - PostgreSQL-based credential storage.

Stores MCP credentials encrypted in PostgreSQL instead of filesystem.
Follows same patterns as Composio for parity.
"""

from collections.abc import Mapping
from datetime import UTC, datetime
import hashlib
import hmac
import json
import secrets
from typing import cast

from cryptography.fernet import Fernet
from pydantic import ValidationError
from sqlalchemy import select

from app.config.settings import settings
from app.constants.cache import (
    OAUTH_DISCOVERY_PREFIX,
    OAUTH_DISCOVERY_TTL,
    OAUTH_EXCLUDED_SCOPES_PREFIX,
    OAUTH_STATE_PREFIX,
    OAUTH_STATE_TTL,
)
from app.constants.log_tags import LogTag
from app.constants.mcp import (
    MCP_OAUTH_BROWSER_COOKIE,
    MCP_OAUTH_GRANT_LOCK_ACQUIRE_TIMEOUT_SECONDS,
    MCP_OAUTH_GRANT_LOCK_LEASE_SECONDS,
    MCP_OAUTH_GRANT_LOCK_MAX_HOLD_SECONDS,
    MCP_OAUTH_GRANT_LOCK_PREFIX,
    MCP_OAUTH_GRANT_LOCK_RENEW_SECONDS,
    OAUTH_BROWSER_NONCE_BYTES,
)
from app.db.postgresql import get_db_session
from app.db.redis import delete_cache, get_and_delete_cache, get_cache, set_cache
from app.models.db_oauth import MCPAuthType, MCPCredential, MCPCredentialStatus
from app.models.mcp_config import (
    DCRClientRegistration,
    OAuthDiscovery,
    OAuthPendingState,
    OAuthStateOwner,
)
from app.utils.mcp_oauth_utils import TokenIntrospectionResponse, introspect_token as do_introspect
from app.utils.redis_lock import DistributedLock
from shared.py.wide_events import log


class OAuthStateStoreError(RuntimeError):
    """The OAuth state could not be stored, so its callback could never complete."""

    def __init__(self, what: str) -> None:
        super().__init__(f"could not store the OAuth state ({what}) in Redis")


def _oauth_owner_key(state: str) -> str:
    return f"{OAUTH_STATE_PREFIX}:owner:{state}"


def _pending_state(stored: object) -> OAuthPendingState | None:
    """Read a pending state as create_oauth_state wrote it; None when nothing is pending."""
    if not stored:
        return None
    try:
        # set_cache may hand it back already deserialized or still as JSON text
        return (
            OAuthPendingState.model_validate(stored)
            if isinstance(stored, dict)
            else OAuthPendingState.model_validate_json(str(stored))
        )
    except ValidationError:
        # legacy format: the state string alone
        return OAuthPendingState(state=str(stored))


def _oauth_browser_key(state: str) -> str:
    return f"{OAUTH_STATE_PREFIX}:browser:{state}"


def _digest(nonce: str) -> str:
    return hashlib.sha256(nonce.encode()).hexdigest()


async def _forget_state(state: str) -> None:
    await delete_cache(_oauth_owner_key(state))
    await delete_cache(_oauth_browser_key(state))


def oauth_browser_cookie(integration_id: str) -> str:
    """Name the cookie that binds one integration's pending flow to its browser, so two flows never share one."""
    return f"{MCP_OAUTH_BROWSER_COOKIE}_{hashlib.sha256(integration_id.encode()).hexdigest()[:16]}"


async def bind_oauth_state_to_browser(state: str) -> str:
    """Bind a state to the browser that is about to open it; return the nonce that browser keeps as a cookie."""
    nonce = secrets.token_urlsafe(
        OAUTH_BROWSER_NONCE_BYTES
    )  # pragma: no mutate — None is the same 32-byte default
    if not await set_cache(_oauth_browser_key(state), _digest(nonce), ttl=OAUTH_STATE_TTL):
        raise OAuthStateStoreError("browser binding")
    return nonce


async def oauth_state_bound_to_browser(state: str, nonce: str | None) -> bool:
    """Whether nonce is the one the state was bound to when its browser opened it."""
    if not nonce:
        return False
    stored = await get_cache(_oauth_browser_key(state))
    return isinstance(stored, str) and hmac.compare_digest(stored, _digest(nonce))


async def resolve_oauth_state_owner(state: str, integration_id: str) -> str | None:
    """Return the user a state token was minted for, when it was minted for this integration; None otherwise."""
    owner = await get_cache(_oauth_owner_key(state), OAuthStateOwner)
    return owner.user_id if owner is not None and owner.integration_id == integration_id else None


def _is_credential_usable(cred: MCPCredential | None) -> bool:
    if not cred or cred.status != MCPCredentialStatus.CONNECTED:
        return False
    if cred.auth_type == MCPAuthType.NONE:
        return True
    if cred.auth_type == MCPAuthType.BEARER:
        return bool(cred.access_token)
    if cred.refresh_token:
        return True
    expires_at = cred.token_expires_at
    if expires_at is not None and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    return bool(cred.access_token) and (expires_at is None or expires_at > datetime.now(UTC))


class MCPTokenStore:
    """PostgreSQL-based token storage for MCP credentials."""

    def __init__(self, user_id: str):
        self.user_id = user_id
        self._cipher: Fernet | None = None

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
                ) from e
        return self._cipher

    def _encrypt(self, data: str) -> str:
        """Encrypt sensitive data."""
        return self._get_cipher().encrypt(data.encode()).decode()

    def _decrypt(self, data: str) -> str:
        """Decrypt sensitive data."""
        return self._get_cipher().decrypt(data.encode()).decode()

    async def get_credential(self, integration_id: str) -> MCPCredential | None:
        """Get stored credential for integration."""
        async with get_db_session() as session:
            result = await session.execute(
                select(MCPCredential).where(
                    MCPCredential.user_id == self.user_id,
                    MCPCredential.integration_id == integration_id,
                )
            )
            return result.scalar_one_or_none()

    async def get_bearer_token(self, integration_id: str) -> str | None:
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

    async def get_oauth_token(self, integration_id: str) -> str | None:
        """Get decrypted OAuth access token if not expired."""
        cred = await self.get_credential(integration_id)
        if not cred:
            log.debug(
                f"{LogTag.MCP} No credential record found in DB", integration_id=integration_id
            )
            return None

        if not cred.access_token:
            log.debug(
                f"{LogTag.MCP} Credential exists but no access_token", integration_id=integration_id
            )
            return None

        if cred.status != MCPCredentialStatus.CONNECTED:
            log.debug(
                f"{LogTag.MCP} Credential status is not 'connected'",
                integration_id=integration_id,
                status=cred.status,
            )
            return None

        # token_expires_at is a timezone-aware column (DateTime(timezone=True)),
        # so compare against timezone-aware UTC.
        if cred.token_expires_at and cred.token_expires_at < datetime.now(UTC):
            log.warning(f"{LogTag.MCP} OAuth token expired for", integration_id=integration_id)
            return None

        log.debug(f"{LogTag.MCP} Returning decrypted OAuth token", integration_id=integration_id)
        return self._decrypt(cred.access_token)

    async def get_refresh_token(self, integration_id: str) -> str | None:
        """Get decrypted refresh token."""
        cred = await self.get_credential(integration_id)
        if cred and cred.refresh_token:
            return self._decrypt(cred.refresh_token)
        return None

    async def store_bearer_token(self, integration_id: str, token: str) -> None:
        """Store encrypted bearer token."""
        encrypted = self._encrypt(token)
        now = datetime.now(UTC)

        async with get_db_session() as session:
            # Query within this session
            result = await session.execute(
                select(MCPCredential).where(
                    MCPCredential.user_id == self.user_id,
                    MCPCredential.integration_id == integration_id,
                )
            )
            cred: MCPCredential | None = result.scalar_one_or_none()

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
            log.info(f"{LogTag.MCP} Stored bearer token for", integration_id=integration_id)

    async def store_oauth_tokens(
        self,
        integration_id: str,
        access_token: str,
        refresh_token: str | None = None,
        expires_at: datetime | None = None,
    ) -> None:
        """Store encrypted OAuth tokens."""
        encrypted_access = self._encrypt(access_token)
        encrypted_refresh = self._encrypt(refresh_token) if refresh_token else None
        now = datetime.now(UTC)

        async with get_db_session() as session:
            # Query within this session
            result = await session.execute(
                select(MCPCredential).where(
                    MCPCredential.user_id == self.user_id,
                    MCPCredential.integration_id == integration_id,
                )
            )
            cred: MCPCredential | None = result.scalar_one_or_none()

            if cred:
                cred.access_token = encrypted_access
                cred.refresh_token = encrypted_refresh
                cred.token_expires_at = expires_at
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
                    token_expires_at=expires_at,
                    status=MCPCredentialStatus.CONNECTED,  # Required for get_oauth_token() to work
                    connected_at=now,
                )
                session.add(cred)
            await session.commit()
            log.info(f"{LogTag.MCP} Stored OAuth tokens for", integration_id=integration_id)

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
                log.info(
                    f"{LogTag.MCP} Created credential record for unauthenticated",
                    integration_id=integration_id,
                )

    async def create_oauth_state(self, integration_id: str, code_verifier: str) -> str:
        """Create OAuth state and PKCE code_verifier for CSRF protection, stored in Redis with TTL.

        PostgreSQL only stores the PKCE state for the flow; connection status
        lives in MongoDB user_integrations.
        """
        state = secrets.token_urlsafe(32)

        # Store state and code_verifier together in Redis
        # IMPORTANT: Pass dict directly - set_cache handles serialization via TypeAdapter.
        # Pre-serializing with json.dumps() causes double-encoding, breaking code_verifier retrieval.
        cache_key = f"{OAUTH_STATE_PREFIX}:{self.user_id}:{integration_id}"
        state_data: dict[str, str] = {"state": state, "code_verifier": code_verifier}
        # A new flow replaces the pending one, so the replaced state must stop resolving too.
        if (replaced := _pending_state(await get_cache(cache_key))) is not None:
            await _forget_state(replaced.state)
        # The callback arrives from a browser with no GAIA session (a link opened from a
        # chat app), so the state token itself has to say whose flow it belongs to.
        stored = await set_cache(cache_key, state_data, ttl=OAUTH_STATE_TTL) and await set_cache(
            _oauth_owner_key(state),
            OAuthStateOwner(user_id=self.user_id, integration_id=integration_id),
            ttl=OAUTH_STATE_TTL,
            model=OAuthStateOwner,
        )
        if not stored:
            raise OAuthStateStoreError(integration_id)
        return state

    async def verify_oauth_state(self, integration_id: str, state: str) -> tuple[bool, str | None]:
        """
        Verify OAuth state matches stored state.

        Uses atomic get-and-delete to prevent replay attacks (Issue 5.2 fix).
        Returns (is_valid, code_verifier) tuple.
        """
        cache_key = f"{OAUTH_STATE_PREFIX}:{self.user_id}:{integration_id}"
        # Atomic get-and-delete prevents race condition where two callbacks
        # could both validate before either deletes the state
        stored_data = await get_and_delete_cache(cache_key)
        await _forget_state(state)

        pending = _pending_state(stored_data)
        if pending is None:
            return False, None

        if pending.state and pending.state == state:
            return True, pending.code_verifier
        return False, None

    def grant_lock(self, integration_id: str) -> DistributedLock:
        """Return the cross-replica lock a refresh and a delete of this OAuth grant both hold."""
        return DistributedLock(
            f"{MCP_OAUTH_GRANT_LOCK_PREFIX}{self.user_id}:{integration_id}",
            lease_seconds=MCP_OAUTH_GRANT_LOCK_LEASE_SECONDS,
            acquire_timeout_seconds=MCP_OAUTH_GRANT_LOCK_ACQUIRE_TIMEOUT_SECONDS,
            renew_seconds=MCP_OAUTH_GRANT_LOCK_RENEW_SECONDS,
            max_hold_seconds=MCP_OAUTH_GRANT_LOCK_MAX_HOLD_SECONDS,
        )

    async def delete_credentials(self, integration_id: str) -> None:
        """Delete credentials for integration (disconnect), after any refresh in flight has stored."""
        # A disconnect must win even when the lease cannot be taken; hold() logs that case.
        async with self.grant_lock(integration_id).hold(), get_db_session() as session:
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
                log.info(f"{LogTag.MCP} Deleted MCP credentials for", integration_id=integration_id)

    async def clear_oauth_grant(self, integration_id: str) -> None:
        """Drop a proven-dead grant's access and refresh tokens while keeping the credential row.

        A refresh runs only once the access token expired or was rejected, so when the
        refresh can never succeed the access token is dead too; keeping either makes
        liveness checks report the integration usable with no re-auth prompt.
        """
        async with get_db_session() as session:
            result = await session.execute(
                select(MCPCredential).where(
                    MCPCredential.user_id == self.user_id,
                    MCPCredential.integration_id == integration_id,
                )
            )
            cred = result.scalar_one_or_none()
            if cred and (cred.refresh_token or cred.access_token):
                cred.access_token = None
                cred.refresh_token = None
                cred.token_expires_at = None
                session.add(cred)
                await session.commit()
                log.info(
                    f"{LogTag.MCP} Cleared dead OAuth grant for",
                    integration_id=integration_id,
                )

    async def is_connected(self, integration_id: str) -> bool:
        """Check whether a connected credential can be used or refreshed."""
        cred = await self.get_credential(integration_id)
        return _is_credential_usable(cred)

    async def get_credentials_map(self, integration_ids: list[str]) -> dict[str, MCPCredential]:
        """Fetch credentials for several integrations in one query."""
        if not integration_ids:
            return {}
        async with get_db_session() as session:
            result = await session.execute(
                select(MCPCredential).where(
                    MCPCredential.user_id == self.user_id,
                    MCPCredential.integration_id.in_(integration_ids),
                )
            )
            rows = result.scalars().all()
        return {row.integration_id: row for row in rows}

    async def are_connected(self, integration_ids: list[str]) -> dict[str, bool]:
        """Batch version of is_connected: one query, in-memory evaluation."""
        if not integration_ids:
            return {}
        creds = await self.get_credentials_map(integration_ids)
        return {
            integration_id: _is_credential_usable(creds.get(integration_id))
            for integration_id in integration_ids
        }

    async def get_dcr_client(self, integration_id: str) -> DCRClientRegistration | None:
        """Get stored DCR client registration."""
        cred = await self.get_credential(integration_id)
        if cred and cred.client_registration:
            try:
                # Written by store_dcr_client from an RFC 7591 registration
                # response; only the credential fields are ever read back.
                return DCRClientRegistration.model_validate_json(cred.client_registration)
            except ValidationError:
                return None
        return None

    async def delete_dcr_client(self, integration_id: str) -> None:
        """Delete stored DCR client registration.

        Clears the client_registration field so the next OAuth flow
        performs fresh Dynamic Client Registration instead of reusing
        a potentially revoked/invalid client_id.
        """
        async with get_db_session() as session:
            result = await session.execute(
                select(MCPCredential).where(
                    MCPCredential.user_id == self.user_id,
                    MCPCredential.integration_id == integration_id,
                )
            )
            cred = result.scalar_one_or_none()
            if cred and cred.client_registration:
                cred.client_registration = None
                session.add(cred)
                await session.commit()
                log.info(f"{LogTag.MCP} Deleted DCR client for", integration_id=integration_id)

    async def store_dcr_client(self, integration_id: str, dcr_data: Mapping[str, object]) -> None:
        """Store DCR client registration from dynamic registration.

        The whole RFC 7591 response is persisted verbatim — servers return
        arbitrary extra metadata alongside the credentials — so the write side
        stays an open JSON object. Reads go through DCRClientRegistration.
        """
        async with get_db_session() as session:
            result = await session.execute(
                select(MCPCredential).where(
                    MCPCredential.user_id == self.user_id,
                    MCPCredential.integration_id == integration_id,
                )
            )
            cred = result.scalar_one_or_none()

            if cred:
                cred.client_registration = json.dumps(dict(dcr_data))
                session.add(cred)
            else:
                cred = MCPCredential(
                    user_id=self.user_id,
                    integration_id=integration_id,
                    auth_type=MCPAuthType.OAUTH,
                    status=MCPCredentialStatus.PENDING,
                    client_registration=json.dumps(dict(dcr_data)),
                )
                session.add(cred)
            await session.commit()
            log.info(f"{LogTag.MCP} Stored DCR client for", integration_id=integration_id)

    async def store_oauth_discovery(self, integration_id: str, discovery: OAuthDiscovery) -> None:
        """Cache OAuth discovery data in Redis for 24 hours.

        Global per integration (key: mcp_oauth_discovery:{integration_id}, no
        user_id) since discovery data is the same for all users; per-user DCR
        client_id is stored separately in PostgreSQL.
        """
        cache_key = f"{OAUTH_DISCOVERY_PREFIX}:{integration_id}"
        await set_cache(cache_key, discovery.model_dump(mode="json"), ttl=OAUTH_DISCOVERY_TTL)
        log.info(f"{LogTag.MCP} Cached OAuth discovery for", integration_id=integration_id)

    async def get_oauth_discovery(self, integration_id: str) -> OAuthDiscovery | None:
        """Get cached OAuth discovery data from Redis."""
        cache_key = f"{OAUTH_DISCOVERY_PREFIX}:{integration_id}"
        cached = await get_cache(cache_key)
        if cached and isinstance(cached, dict):
            return OAuthDiscovery.model_validate(cached)
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
        log.debug(f"{LogTag.MCP} Stored OIDC nonce for", integration_id=integration_id)

    async def get_and_delete_oauth_nonce(self, integration_id: str) -> str | None:
        """
        Get and delete OIDC nonce (atomic operation).

        Returns the nonce if found, None otherwise.
        """
        cache_key = f"mcp_oauth_nonce:{self.user_id}:{integration_id}"
        return cast(str | None, await get_and_delete_cache(cache_key))

    async def get_excluded_scopes(self, integration_id: str) -> set[str]:
        """
        Get scopes the auth server rejected with invalid_scope.

        Accumulated within a single OAuth flow (TTL-bounded) so each
        re-authorization retry drops the offending scope(s) and converges.
        """
        cache_key = f"{OAUTH_EXCLUDED_SCOPES_PREFIX}:{self.user_id}:{integration_id}"
        cached = cast(list[str] | None, await get_cache(cache_key))
        return set(cached) if cached else set()

    async def add_excluded_scopes(self, integration_id: str, scopes: set[str]) -> set[str]:
        """Add rejected scopes to the exclusion set; returns the merged set."""
        merged = await self.get_excluded_scopes(integration_id) | scopes
        cache_key = f"{OAUTH_EXCLUDED_SCOPES_PREFIX}:{self.user_id}:{integration_id}"
        await set_cache(cache_key, sorted(merged), ttl=OAUTH_STATE_TTL)
        return merged

    async def clear_excluded_scopes(self, integration_id: str) -> None:
        """Clear the exclusion set after a successful or abandoned OAuth flow."""
        cache_key = f"{OAUTH_EXCLUDED_SCOPES_PREFIX}:{self.user_id}:{integration_id}"
        await get_and_delete_cache(cache_key)

    async def introspect_token(
        self,
        integration_id: str,
        client_id: str | None = None,
        client_secret: str | None = None,
    ) -> TokenIntrospectionResponse | None:
        """
        Introspect token at authorization server per RFC 7662.

        Returns introspection response with 'active' field, or None if failed.
        """
        discovery = await self.get_oauth_discovery(integration_id)
        if not discovery:
            return None

        introspection_endpoint = discovery.as_metadata.introspection_endpoint
        if not introspection_endpoint:
            return None

        access_token = await self.get_oauth_token(integration_id)
        if not access_token:
            return None

        return await do_introspect(
            introspection_endpoint=str(introspection_endpoint),
            token=access_token,
            token_type_hint="access_token",  # nosec B106 - OAuth token type hint, not a password
            client_id=client_id,
            client_secret=client_secret,
        )
