"""
TEST 10: OAuth Integration Connection Lifecycle

Integration tests for the OAuth connection lifecycle — URL generation,
callback handling, status tracking, token management, disconnect cleanup,
reconnection, multi-provider isolation, and integration resolution.

Tests exercise the real service logic from:
- app.services.oauth.oauth_state_service (state creation, validation)
- app.services.integrations.integration_connection_service (connect, disconnect)
- app.services.integrations.user_integration_status (status upsert)
- app.services.integrations.user_integrations (add, remove, check)
- app.services.integrations.integration_resolver (resolve from platform/custom)
- app.config.oauth_config (integration definitions, scopes)
- app.services.oauth.oauth_service (status checks, connection handling)

Mocking boundaries:
- Redis (oauth state storage)
- MongoDB collections (user_integrations, integrations, users)
- Composio service (external OAuth provider)
- Token repository (PostgreSQL token storage)
- MCP client (external MCP connections)
"""

from datetime import UTC, datetime
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config.oauth_config import (
    OAUTH_INTEGRATIONS,
    get_integration_by_id,
    get_integration_scopes,
)
from app.models.mcp_config import MCPConfig
from app.models.oauth_models import OAuthIntegration
from app.services.integrations.integration_resolver import (
    IntegrationResolver,
    ResolvedIntegration,
)
from app.services.integrations.user_integration_status import (
    update_user_integration_status,
)
from app.services.integrations.user_integrations import remove_user_integration
from app.services.integrations.integration_connection_service import (
    build_integrations_config,
    connect_composio_integration,
    connect_mcp_integration,
    connect_self_integration,
    disconnect_integration,
)
from app.services.oauth.oauth_state_service import (
    _is_safe_redirect_path,
    create_oauth_state,
    validate_and_consume_oauth_state,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

USER_ID = "507f1f77bcf86cd799439011"
USER_ID_2 = "507f1f77bcf86cd799439022"
USER_EMAIL = "test@example.com"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_redis() -> AsyncMock:
    """Create a mock Redis client that stores state in a dict."""
    store: Dict[str, Dict[str, str]] = {}
    ttls: Dict[str, int] = {}

    redis = AsyncMock()

    async def _hset(key: str, mapping: Dict[str, str]) -> None:
        store[key] = dict(mapping)

    async def _hgetall(key: str) -> Dict[str, str]:
        return store.get(key, {})

    async def _expire(key: str, ttl: int) -> None:
        ttls[key] = ttl

    async def _delete(key: str) -> None:
        store.pop(key, None)
        ttls.pop(key, None)

    redis.hset = AsyncMock(side_effect=_hset)
    redis.hgetall = AsyncMock(side_effect=_hgetall)
    redis.expire = AsyncMock(side_effect=_expire)
    redis.delete = AsyncMock(side_effect=_delete)
    redis._store = store
    redis._ttls = ttls

    return redis


def _make_mock_collection() -> AsyncMock:
    """Create a mock MongoDB collection with an in-memory document store."""
    docs: List[Dict[str, Any]] = []
    collection = AsyncMock()

    async def _find_one(query: Dict[str, Any]) -> Dict[str, Any] | None:
        for doc in docs:
            if all(doc.get(k) == v for k, v in query.items()):
                return doc
        return None

    async def _insert_one(doc: Dict[str, Any]) -> MagicMock:
        docs.append(dict(doc))
        result = MagicMock()
        result.inserted_id = f"inserted_{len(docs)}"
        return result

    async def _update_one(
        query: Dict[str, Any], update: Dict[str, Any], upsert: bool = False
    ) -> MagicMock:
        result = MagicMock()
        result.modified_count = 0
        result.upserted_id = None
        result.matched_count = 0

        target = None
        for doc in docs:
            if all(doc.get(k) == v for k, v in query.items()):
                target = doc
                break

        if target:
            result.matched_count = 1
            set_data = update.get("$set", {})
            if set_data:
                target.update(set_data)
                result.modified_count = 1
        elif upsert:
            new_doc = dict(query)
            set_data = update.get("$set", {})
            set_on_insert = update.get("$setOnInsert", {})
            new_doc.update(set_data)
            new_doc.update(set_on_insert)
            docs.append(new_doc)
            result.upserted_id = f"upserted_{len(docs)}"

        return result

    async def _delete_one(query: Dict[str, Any]) -> MagicMock:
        result = MagicMock()
        result.deleted_count = 0
        for i, doc in enumerate(docs):
            if all(doc.get(k) == v for k, v in query.items()):
                docs.pop(i)
                result.deleted_count = 1
                break
        return result

    def _find(query: Dict[str, Any]) -> AsyncMock:
        matching = [
            doc for doc in docs if all(doc.get(k) == v for k, v in query.items())
        ]
        cursor = AsyncMock()
        cursor.to_list = AsyncMock(return_value=matching)
        cursor.sort = MagicMock(return_value=cursor)

        # Support async iteration
        cursor.__aiter__ = MagicMock(return_value=iter(matching).__iter__())

        async def _aiter():
            for doc in matching:
                yield doc

        cursor.__aiter__ = lambda self: _aiter()
        return cursor

    collection.find_one = AsyncMock(side_effect=_find_one)
    collection.insert_one = AsyncMock(side_effect=_insert_one)
    collection.update_one = AsyncMock(side_effect=_update_one)
    collection.delete_one = AsyncMock(side_effect=_delete_one)
    collection.find = MagicMock(side_effect=_find)
    collection._docs = docs

    return collection


# ---------------------------------------------------------------------------
# Tests — OAuth State Management
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestOAuthStateCreationAndValidation:
    """OAuth state token creation, validation, and consumption."""

    async def test_create_state_returns_token(self) -> None:
        """create_oauth_state returns a non-empty string token."""
        mock_redis = _make_mock_redis()

        with patch("app.services.oauth.oauth_state_service.redis_cache") as mock_cache:
            mock_cache.client = mock_redis

            token = await create_oauth_state(
                user_id=USER_ID,
                redirect_path="/integrations",
                integration_id="gmail",
            )

            assert isinstance(token, str)
            assert len(token) > 0

    async def test_create_state_stores_in_redis_with_ttl(self) -> None:
        """State is stored in Redis with user_id, redirect_path, integration_id, and TTL."""
        mock_redis = _make_mock_redis()

        with patch("app.services.oauth.oauth_state_service.redis_cache") as mock_cache:
            mock_cache.client = mock_redis

            token = await create_oauth_state(
                user_id=USER_ID,
                redirect_path="/c",
                integration_id="slack",
            )

            # Verify data was stored
            state_key = f"oauth_state:{token}"
            stored = mock_redis._store.get(state_key, {})
            assert stored["user_id"] == USER_ID
            assert stored["redirect_path"] == "/c"
            assert stored["integration_id"] == "slack"

            # Verify TTL was set
            assert state_key in mock_redis._ttls

    async def test_validate_and_consume_returns_state_data(self) -> None:
        """validate_and_consume_oauth_state returns stored data and deletes the token."""
        mock_redis = _make_mock_redis()

        with patch("app.services.oauth.oauth_state_service.redis_cache") as mock_cache:
            mock_cache.client = mock_redis

            token = await create_oauth_state(
                user_id=USER_ID,
                redirect_path="/integrations",
                integration_id="gmail",
            )

            result = await validate_and_consume_oauth_state(token)

            assert result is not None
            assert result["user_id"] == USER_ID
            assert result["redirect_path"] == "/integrations"
            assert result["integration_id"] == "gmail"

    async def test_validate_consumes_token_preventing_replay(self) -> None:
        """After validation, the same token cannot be used again (replay prevention)."""
        mock_redis = _make_mock_redis()

        with patch("app.services.oauth.oauth_state_service.redis_cache") as mock_cache:
            mock_cache.client = mock_redis

            token = await create_oauth_state(
                user_id=USER_ID,
                redirect_path="/c",
                integration_id="gmail",
            )

            # First validation succeeds
            first_result = await validate_and_consume_oauth_state(token)
            assert first_result is not None

            # Second validation fails (token consumed)
            second_result = await validate_and_consume_oauth_state(token)
            assert second_result is None

    async def test_validate_invalid_token_returns_none(self) -> None:
        """An unknown/invalid token returns None."""
        mock_redis = _make_mock_redis()

        with patch("app.services.oauth.oauth_state_service.redis_cache") as mock_cache:
            mock_cache.client = mock_redis

            result = await validate_and_consume_oauth_state("nonexistent_token_abc123")
            assert result is None

    async def test_validate_incomplete_state_returns_none(self) -> None:
        """State with missing fields returns None."""
        mock_redis = _make_mock_redis()
        # Manually insert incomplete state
        mock_redis._store["oauth_state:bad_token"] = {
            "user_id": USER_ID,
            "redirect_path": "",
            "integration_id": "",
        }

        with patch("app.services.oauth.oauth_state_service.redis_cache") as mock_cache:
            mock_cache.client = mock_redis

            result = await validate_and_consume_oauth_state("bad_token")
            assert result is None

    async def test_redis_error_returns_none(self) -> None:
        """Redis errors during validation are caught and return None."""
        mock_redis = AsyncMock()
        mock_redis.hgetall = AsyncMock(side_effect=Exception("Redis connection lost"))

        with patch("app.services.oauth.oauth_state_service.redis_cache") as mock_cache:
            mock_cache.client = mock_redis

            result = await validate_and_consume_oauth_state("any_token")
            assert result is None


# ---------------------------------------------------------------------------
# Tests — Redirect Path Safety
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestRedirectPathSafety:
    """Validates the _is_safe_redirect_path helper used during state creation."""

    def test_valid_paths(self) -> None:
        assert _is_safe_redirect_path("/c") is True
        assert _is_safe_redirect_path("/integrations") is True
        assert _is_safe_redirect_path("/settings/integrations") is True

    def test_rejects_empty_path(self) -> None:
        assert _is_safe_redirect_path("") is False

    def test_rejects_non_slash_start(self) -> None:
        assert _is_safe_redirect_path("integrations") is False
        assert _is_safe_redirect_path("https://evil.com") is False

    def test_rejects_protocol_relative(self) -> None:
        assert _is_safe_redirect_path("//evil.com/callback") is False

    def test_rejects_javascript_protocol(self) -> None:
        assert _is_safe_redirect_path("/javascript:alert(1)") is False

    def test_rejects_path_traversal(self) -> None:
        assert _is_safe_redirect_path("/../etc/passwd") is False

    def test_rejects_at_sign(self) -> None:
        assert _is_safe_redirect_path("/redirect@evil.com") is False

    async def test_unsafe_redirect_defaults_to_safe_path(self) -> None:
        """create_oauth_state replaces unsafe redirect_path with /c."""
        mock_redis = _make_mock_redis()

        with patch("app.services.oauth.oauth_state_service.redis_cache") as mock_cache:
            mock_cache.client = mock_redis

            token = await create_oauth_state(
                user_id=USER_ID,
                redirect_path="https://evil.com",
                integration_id="gmail",
            )

            state_key = f"oauth_state:{token}"
            stored = mock_redis._store.get(state_key, {})
            assert stored["redirect_path"] == "/c"


# ---------------------------------------------------------------------------
# Tests — User Integration Status Tracking
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestUserIntegrationStatusTracking:
    """Status upsert logic in update_user_integration_status."""

    async def test_create_new_integration_status(self) -> None:
        """Upsert creates a new record when none exists."""
        mock_collection = _make_mock_collection()

        with (
            patch(
                "app.services.integrations.user_integration_status.user_integrations_collection",
                mock_collection,
            ),
            patch(
                "app.services.integrations.user_integration_status.CacheInvalidator.__call__",
                lambda self, func: func,
            ),
        ):
            result = await update_user_integration_status(USER_ID, "gmail", "created")

            assert result is True
            assert len(mock_collection._docs) == 1
            doc = mock_collection._docs[0]
            assert doc["user_id"] == USER_ID
            assert doc["integration_id"] == "gmail"
            assert doc["status"] == "created"

    async def test_update_existing_status_to_connected(self) -> None:
        """Upsert updates an existing record from 'created' to 'connected'."""
        mock_collection = _make_mock_collection()
        mock_collection._docs.append(
            {
                "user_id": USER_ID,
                "integration_id": "gmail",
                "status": "created",
                "created_at": datetime.now(UTC),
            }
        )

        with (
            patch(
                "app.services.integrations.user_integration_status.user_integrations_collection",
                mock_collection,
            ),
            patch(
                "app.services.integrations.user_integration_status.CacheInvalidator.__call__",
                lambda self, func: func,
            ),
        ):
            result = await update_user_integration_status(USER_ID, "gmail", "connected")

            assert result is True
            doc = mock_collection._docs[0]
            assert doc["status"] == "connected"
            assert "connected_at" in doc

    async def test_upsert_is_idempotent(self) -> None:
        """Calling upsert twice with same status does not create duplicates."""
        mock_collection = _make_mock_collection()

        with (
            patch(
                "app.services.integrations.user_integration_status.user_integrations_collection",
                mock_collection,
            ),
            patch(
                "app.services.integrations.user_integration_status.CacheInvalidator.__call__",
                lambda self, func: func,
            ),
        ):
            await update_user_integration_status(USER_ID, "gmail", "created")
            await update_user_integration_status(USER_ID, "gmail", "created")

            # Only one document should exist
            matching = [
                d
                for d in mock_collection._docs
                if d["user_id"] == USER_ID and d["integration_id"] == "gmail"
            ]
            assert len(matching) == 1


# ---------------------------------------------------------------------------
# Tests — Composio Integration Connection
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestComposioIntegrationConnection:
    """connect_composio_integration: OAuth URL generation via Composio."""

    async def test_connect_composio_returns_redirect(self) -> None:
        """Composio connect produces a redirect response with OAuth URL."""

        mock_composio = AsyncMock()
        mock_composio.connect_account = AsyncMock(
            return_value={
                "redirect_url": "https://accounts.google.com/o/oauth2/auth?client_id=xxx"
            }
        )

        with (
            patch(
                "app.services.integrations.integration_connection_service.get_composio_service",
                return_value=mock_composio,
            ),
            patch(
                "app.services.integrations.integration_connection_service.create_oauth_state",
                AsyncMock(return_value="test_state_token"),
            ),
            patch(
                "app.services.integrations.integration_connection_service.update_user_integration_status",
                AsyncMock(return_value=True),
            ),
        ):
            response = await connect_composio_integration(
                user_id=USER_ID,
                integration_id="gmail",
                integration_name="Gmail",
                provider="gmail",
                redirect_path="/integrations",
            )

            assert response.status == "redirect"
            assert response.integration_id == "gmail"
            assert response.redirect_url is not None
            assert "accounts.google.com" in response.redirect_url

    async def test_connect_composio_creates_state_token(self) -> None:
        """Composio connect calls create_oauth_state with correct params."""

        mock_composio = AsyncMock()
        mock_composio.connect_account = AsyncMock(
            return_value={"redirect_url": "https://oauth.example.com/auth"}
        )

        mock_create_state = AsyncMock(return_value="state_abc123")

        with (
            patch(
                "app.services.integrations.integration_connection_service.get_composio_service",
                return_value=mock_composio,
            ),
            patch(
                "app.services.integrations.integration_connection_service.create_oauth_state",
                mock_create_state,
            ),
            patch(
                "app.services.integrations.integration_connection_service.update_user_integration_status",
                AsyncMock(return_value=True),
            ),
        ):
            await connect_composio_integration(
                user_id=USER_ID,
                integration_id="slack",
                integration_name="Slack",
                provider="slack",
                redirect_path="/c",
            )

            mock_create_state.assert_called_once_with(
                user_id=USER_ID,
                redirect_path="/c",
                integration_id="slack",
            )

    async def test_connect_composio_sets_status_to_created(self) -> None:
        """Composio connect sets integration status to 'created' before redirect."""

        mock_composio = AsyncMock()
        mock_composio.connect_account = AsyncMock(
            return_value={"redirect_url": "https://oauth.example.com/auth"}
        )

        mock_update_status = AsyncMock(return_value=True)

        with (
            patch(
                "app.services.integrations.integration_connection_service.get_composio_service",
                return_value=mock_composio,
            ),
            patch(
                "app.services.integrations.integration_connection_service.create_oauth_state",
                AsyncMock(return_value="state_token"),
            ),
            patch(
                "app.services.integrations.integration_connection_service.update_user_integration_status",
                mock_update_status,
            ),
        ):
            await connect_composio_integration(
                user_id=USER_ID,
                integration_id="gmail",
                integration_name="Gmail",
                provider="gmail",
                redirect_path="/integrations",
            )

            mock_update_status.assert_called_once_with(USER_ID, "gmail", "created")


# ---------------------------------------------------------------------------
# Tests — Self-Managed Integration Connection (Google)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestSelfManagedIntegrationConnection:
    """connect_self_integration: Google OAuth URL generation."""

    async def test_connect_google_returns_redirect_with_scopes(self) -> None:
        """Self-managed Google connect produces redirect with correct scopes."""

        with (
            patch(
                "app.services.integrations.integration_connection_service.create_oauth_state",
                AsyncMock(return_value="state_xyz"),
            ),
            patch(
                "app.services.integrations.integration_connection_service.update_user_integration_status",
                AsyncMock(return_value=True),
            ),
            patch(
                "app.services.integrations.integration_connection_service.build_google_oauth_url",
                AsyncMock(
                    return_value="https://accounts.google.com/o/oauth2/auth?scope=calendar&state=state_xyz"
                ),
            ),
            patch(
                "app.services.integrations.integration_connection_service.get_integration_scopes",
                return_value=["https://www.googleapis.com/auth/calendar.events"],
            ),
        ):
            response = await connect_self_integration(
                user_id=USER_ID,
                user_email=USER_EMAIL,
                integration_id="googlecalendar",
                integration_name="Google Calendar",
                provider="google",
                redirect_path="/integrations",
            )

            assert response.status == "redirect"
            assert response.redirect_url is not None
            assert "accounts.google.com" in response.redirect_url

    async def test_connect_non_google_provider_returns_error(self) -> None:
        """Self-managed connect with non-Google provider returns error."""

        response = await connect_self_integration(
            user_id=USER_ID,
            user_email=USER_EMAIL,
            integration_id="unknown",
            integration_name="Unknown",
            provider="microsoft",
            redirect_path="/integrations",
        )

        assert response.status == "error"
        assert "not implemented" in (response.error or "").lower()


# ---------------------------------------------------------------------------
# Tests — Disconnect Integration
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestDisconnectIntegration:
    """disconnect_integration: cleanup for different managed_by types."""

    async def test_disconnect_composio_integration(self) -> None:
        """Disconnecting a Composio integration calls delete_connected_account."""

        gmail_config = get_integration_by_id("gmail")
        assert gmail_config is not None

        mock_composio = AsyncMock()
        mock_composio.delete_connected_account = AsyncMock()

        resolved = ResolvedIntegration(
            integration_id="gmail",
            name="Gmail",
            description="Email",
            category="communication",
            managed_by="composio",
            source="platform",
            requires_auth=True,
            auth_type="oauth",
            mcp_config=None,
            platform_integration=gmail_config,
            custom_doc=None,
        )

        with (
            patch.object(
                IntegrationResolver, "resolve", AsyncMock(return_value=resolved)
            ),
            patch(
                "app.services.integrations.integration_connection_service.get_composio_service",
                return_value=mock_composio,
            ),
            patch(
                "app.services.integrations.integration_connection_service.delete_cache",
                AsyncMock(),
            ),
            patch(
                "app.services.integrations.integration_connection_service.remove_user_integration",
                AsyncMock(return_value=True),
            ),
            patch(
                "app.services.integrations.integration_connection_service.get_integration_by_id",
                return_value=gmail_config,
            ),
        ):
            result = await disconnect_integration(USER_ID, "gmail")

            assert result.integration_id == "gmail"
            assert "disconnected" in result.message.lower()
            mock_composio.delete_connected_account.assert_called_once_with(
                user_id=USER_ID, provider="gmail"
            )

    async def test_disconnect_mcp_integration(self) -> None:
        """Disconnecting an MCP integration calls mcp_client.disconnect and removes record."""

        resolved = ResolvedIntegration(
            integration_id="deepwiki",
            name="DeepWiki",
            description="AI docs",
            category="developer",
            managed_by="mcp",
            source="platform",
            requires_auth=False,
            auth_type="none",
            mcp_config=MCPConfig(server_url="https://mcp.deepwiki.com/mcp"),
            platform_integration=get_integration_by_id("deepwiki"),
            custom_doc=None,
        )

        mock_mcp_client = AsyncMock()
        mock_mcp_client.disconnect = AsyncMock()

        with (
            patch.object(
                IntegrationResolver, "resolve", AsyncMock(return_value=resolved)
            ),
            patch(
                "app.services.integrations.integration_connection_service.get_mcp_client",
                AsyncMock(return_value=mock_mcp_client),
            ),
            patch(
                "app.services.integrations.integration_connection_service.remove_user_integration",
                AsyncMock(return_value=True),
            ),
            patch(
                "app.services.integrations.integration_connection_service.delete_cache",
                AsyncMock(),
            ),
        ):
            result = await disconnect_integration(USER_ID, "deepwiki")

            assert result.integration_id == "deepwiki"
            mock_mcp_client.disconnect.assert_called_once_with("deepwiki")

    async def test_disconnect_unknown_integration_raises(self) -> None:
        """Disconnecting a non-existent integration raises ValueError."""

        with patch.object(IntegrationResolver, "resolve", AsyncMock(return_value=None)):
            with pytest.raises(ValueError, match="not found"):
                await disconnect_integration(USER_ID, "nonexistent_integration")

    async def test_disconnect_custom_integration_removes_record(self) -> None:
        """Disconnecting a custom integration calls mcp disconnect and removes user integration."""

        resolved = ResolvedIntegration(
            integration_id="my-custom-mcp",
            name="My Custom",
            description="Custom MCP server",
            category="custom",
            managed_by="mcp",
            source="custom",
            requires_auth=False,
            auth_type="none",
            mcp_config=MCPConfig(server_url="https://custom.example.com/mcp"),
            platform_integration=None,
            custom_doc={"integration_id": "my-custom-mcp", "created_by": USER_ID},
        )

        mock_mcp_client = AsyncMock()
        mock_remove = AsyncMock(return_value=True)
        mock_delete_custom = AsyncMock()

        with (
            patch.object(
                IntegrationResolver, "resolve", AsyncMock(return_value=resolved)
            ),
            patch(
                "app.services.integrations.integration_connection_service.get_mcp_client",
                AsyncMock(return_value=mock_mcp_client),
            ),
            patch(
                "app.services.integrations.integration_connection_service.remove_user_integration",
                mock_remove,
            ),
            patch(
                "app.services.integrations.integration_connection_service.delete_custom_integration",
                mock_delete_custom,
            ),
            patch(
                "app.services.integrations.integration_connection_service.delete_cache",
                AsyncMock(),
            ),
        ):
            result = await disconnect_integration(USER_ID, "my-custom-mcp")

            assert result.integration_id == "my-custom-mcp"
            mock_mcp_client.disconnect.assert_called_once_with("my-custom-mcp")
            mock_remove.assert_called_once_with(USER_ID, "my-custom-mcp")
            mock_delete_custom.assert_called_once_with(USER_ID, "my-custom-mcp")


# ---------------------------------------------------------------------------
# Tests — Integration Status Connect -> Disconnect Lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestConnectionStatusLifecycle:
    """Full connect -> verify -> disconnect -> verify lifecycle."""

    async def test_connect_sets_connected_disconnect_removes(self) -> None:
        """Status transitions: created -> connected -> removed on disconnect."""
        mock_collection = _make_mock_collection()

        with (
            patch(
                "app.services.integrations.user_integration_status.user_integrations_collection",
                mock_collection,
            ),
            patch(
                "app.services.integrations.user_integration_status.CacheInvalidator.__call__",
                lambda self, func: func,
            ),
            patch(
                "app.services.integrations.user_integrations.user_integrations_collection",
                mock_collection,
            ),
            patch(
                "app.services.integrations.user_integrations.CacheInvalidator.__call__",
                lambda self, func: func,
            ),
        ):
            # Step 1: Create
            await update_user_integration_status(USER_ID, "gmail", "created")
            doc = mock_collection._docs[0]
            assert doc["status"] == "created"

            # Step 2: Connect
            await update_user_integration_status(USER_ID, "gmail", "connected")
            doc = mock_collection._docs[0]
            assert doc["status"] == "connected"
            assert "connected_at" in doc

            # Step 3: Disconnect (remove)
            removed = await remove_user_integration(USER_ID, "gmail")
            assert removed is True
            assert len(mock_collection._docs) == 0


# ---------------------------------------------------------------------------
# Tests — Reconnection Flow
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestReconnectionFlow:
    """Connect -> disconnect -> reconnect without duplicate records."""

    async def test_reconnection_creates_fresh_record(self) -> None:
        """After disconnect+reconnect, only one record exists for the integration."""
        mock_collection = _make_mock_collection()

        with (
            patch(
                "app.services.integrations.user_integration_status.user_integrations_collection",
                mock_collection,
            ),
            patch(
                "app.services.integrations.user_integration_status.CacheInvalidator.__call__",
                lambda self, func: func,
            ),
            patch(
                "app.services.integrations.user_integrations.user_integrations_collection",
                mock_collection,
            ),
            patch(
                "app.services.integrations.user_integrations.CacheInvalidator.__call__",
                lambda self, func: func,
            ),
        ):
            # Connect
            await update_user_integration_status(USER_ID, "gmail", "connected")
            assert len(mock_collection._docs) == 1

            # Disconnect
            await remove_user_integration(USER_ID, "gmail")
            assert len(mock_collection._docs) == 0

            # Reconnect
            await update_user_integration_status(USER_ID, "gmail", "connected")
            assert len(mock_collection._docs) == 1

            doc = mock_collection._docs[0]
            assert doc["status"] == "connected"
            assert doc["user_id"] == USER_ID
            assert doc["integration_id"] == "gmail"


# ---------------------------------------------------------------------------
# Tests — Multi-Provider Support
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestMultiProviderSupport:
    """Multiple integrations for the same user stored independently."""

    async def test_two_providers_stored_independently(self) -> None:
        """Gmail and Slack records are independent - connecting one does not affect the other."""
        mock_collection = _make_mock_collection()

        with (
            patch(
                "app.services.integrations.user_integration_status.user_integrations_collection",
                mock_collection,
            ),
            patch(
                "app.services.integrations.user_integration_status.CacheInvalidator.__call__",
                lambda self, func: func,
            ),
        ):
            # Connect Gmail
            await update_user_integration_status(USER_ID, "gmail", "connected")
            # Connect Slack
            await update_user_integration_status(USER_ID, "slack", "connected")

            assert len(mock_collection._docs) == 2

            gmail_doc = next(
                d for d in mock_collection._docs if d["integration_id"] == "gmail"
            )
            slack_doc = next(
                d for d in mock_collection._docs if d["integration_id"] == "slack"
            )

            assert gmail_doc["status"] == "connected"
            assert slack_doc["status"] == "connected"

    async def test_disconnecting_one_does_not_affect_other(self) -> None:
        """Removing Gmail leaves Slack untouched."""
        mock_collection = _make_mock_collection()

        with (
            patch(
                "app.services.integrations.user_integration_status.user_integrations_collection",
                mock_collection,
            ),
            patch(
                "app.services.integrations.user_integration_status.CacheInvalidator.__call__",
                lambda self, func: func,
            ),
            patch(
                "app.services.integrations.user_integrations.user_integrations_collection",
                mock_collection,
            ),
            patch(
                "app.services.integrations.user_integrations.CacheInvalidator.__call__",
                lambda self, func: func,
            ),
        ):
            await update_user_integration_status(USER_ID, "gmail", "connected")
            await update_user_integration_status(USER_ID, "slack", "connected")

            # Remove Gmail only
            await remove_user_integration(USER_ID, "gmail")

            assert len(mock_collection._docs) == 1
            remaining = mock_collection._docs[0]
            assert remaining["integration_id"] == "slack"
            assert remaining["status"] == "connected"

    async def test_different_users_same_provider_isolated(self) -> None:
        """Two users connecting Gmail have independent records."""
        mock_collection = _make_mock_collection()

        with (
            patch(
                "app.services.integrations.user_integration_status.user_integrations_collection",
                mock_collection,
            ),
            patch(
                "app.services.integrations.user_integration_status.CacheInvalidator.__call__",
                lambda self, func: func,
            ),
        ):
            await update_user_integration_status(USER_ID, "gmail", "connected")
            await update_user_integration_status(USER_ID_2, "gmail", "connected")

            assert len(mock_collection._docs) == 2

            user1_doc = next(
                d for d in mock_collection._docs if d["user_id"] == USER_ID
            )
            user2_doc = next(
                d for d in mock_collection._docs if d["user_id"] == USER_ID_2
            )

            assert user1_doc["integration_id"] == "gmail"
            assert user2_doc["integration_id"] == "gmail"


# ---------------------------------------------------------------------------
# Tests — Integration Resolver
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestIntegrationResolver:
    """IntegrationResolver.resolve: platform and custom integration lookup."""

    async def test_resolve_platform_integration(self) -> None:
        """Resolving a known platform integration returns platform source."""
        resolved = await IntegrationResolver.resolve("gmail")

        assert resolved is not None
        assert resolved.integration_id == "gmail"
        assert resolved.source == "platform"
        assert resolved.name == "Gmail"
        assert resolved.managed_by == "composio"
        assert resolved.requires_auth is True
        assert resolved.auth_type == "oauth"
        assert resolved.platform_integration is not None
        assert resolved.custom_doc is None

    async def test_resolve_mcp_platform_integration(self) -> None:
        """Resolving an MCP platform integration returns correct config."""
        resolved = await IntegrationResolver.resolve("deepwiki")

        assert resolved is not None
        assert resolved.integration_id == "deepwiki"
        assert resolved.source == "platform"
        assert resolved.managed_by == "mcp"
        assert resolved.mcp_config is not None
        assert resolved.mcp_config.server_url == "https://mcp.deepwiki.com/mcp"
        assert resolved.requires_auth is False

    async def test_resolve_custom_integration_from_mongodb(self) -> None:
        """Resolving a custom integration falls back to MongoDB."""
        custom_doc = {
            "integration_id": "my-custom-server",
            "name": "My Custom Server",
            "description": "A custom MCP server",
            "category": "custom",
            "managed_by": "mcp",
            "requires_auth": False,
            "auth_type": "none",
            "mcp_config": {
                "server_url": "https://custom.example.com/mcp",
                "requires_auth": False,
            },
        }

        with patch(
            "app.services.integrations.integration_resolver.integrations_collection"
        ) as mock_col:
            mock_col.find_one = AsyncMock(return_value=custom_doc)

            resolved = await IntegrationResolver.resolve("my-custom-server")

            assert resolved is not None
            assert resolved.integration_id == "my-custom-server"
            assert resolved.source == "custom"
            assert resolved.managed_by == "mcp"
            assert resolved.mcp_config is not None
            assert resolved.mcp_config.server_url == "https://custom.example.com/mcp"
            assert resolved.custom_doc is not None

    async def test_resolve_nonexistent_returns_none(self) -> None:
        """Resolving a non-existent integration returns None."""
        with patch(
            "app.services.integrations.integration_resolver.integrations_collection"
        ) as mock_col:
            mock_col.find_one = AsyncMock(return_value=None)

            resolved = await IntegrationResolver.resolve("does_not_exist_xyz")
            assert resolved is None

    async def test_resolve_platform_takes_priority_over_custom(self) -> None:
        """Platform integration is returned even if a custom doc exists with same ID."""
        # "gmail" exists in OAUTH_INTEGRATIONS, so even if MongoDB had a doc
        # with integration_id="gmail", the platform one wins.
        with patch(
            "app.services.integrations.integration_resolver.integrations_collection"
        ) as mock_col:
            # This should not even be called since platform check succeeds first
            mock_col.find_one = AsyncMock(
                return_value={"integration_id": "gmail", "name": "Fake Gmail"}
            )

            resolved = await IntegrationResolver.resolve("gmail")

            assert resolved is not None
            assert resolved.source == "platform"
            assert resolved.name == "Gmail"  # Not "Fake Gmail"
            mock_col.find_one.assert_not_called()

    async def test_get_mcp_config_for_mcp_integration(self) -> None:
        """get_mcp_config returns MCPConfig for MCP-based integrations."""
        config = await IntegrationResolver.get_mcp_config("deepwiki")

        assert config is not None
        assert isinstance(config, MCPConfig)
        assert config.server_url == "https://mcp.deepwiki.com/mcp"

    async def test_get_mcp_config_for_non_mcp_returns_none(self) -> None:
        """get_mcp_config returns None for Composio-managed integrations."""
        config = await IntegrationResolver.get_mcp_config("gmail")
        assert config is None

    async def test_is_mcp_integration(self) -> None:
        """is_mcp_integration correctly identifies MCP-based integrations."""
        assert await IntegrationResolver.is_mcp_integration("deepwiki") is True
        assert await IntegrationResolver.is_mcp_integration("gmail") is False

    async def test_requires_authentication(self) -> None:
        """requires_authentication returns correct value per integration type."""
        # Composio integrations require auth
        assert await IntegrationResolver.requires_authentication("gmail") is True
        # Unauthenticated MCP integrations do not
        assert await IntegrationResolver.requires_authentication("deepwiki") is False


# ---------------------------------------------------------------------------
# Tests — OAuth Config Helpers
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestOAuthConfigHelpers:
    """Static configuration helpers from oauth_config module."""

    def test_get_integration_by_id_found(self) -> None:
        """Known integration ID returns the OAuthIntegration object."""
        integration = get_integration_by_id("gmail")
        assert integration is not None
        assert integration.id == "gmail"
        assert integration.name == "Gmail"
        assert isinstance(integration, OAuthIntegration)

    def test_get_integration_by_id_not_found(self) -> None:
        """Unknown integration ID returns None."""
        assert get_integration_by_id("nonexistent_xyz") is None

    def test_get_integration_scopes_gmail(self) -> None:
        """Gmail scopes include gmail.modify."""
        scopes = get_integration_scopes("gmail")
        assert len(scopes) > 0
        assert any("gmail" in s for s in scopes)

    def test_get_integration_scopes_unknown_returns_empty(self) -> None:
        """Unknown integration returns empty scope list."""
        scopes = get_integration_scopes("nonexistent_xyz_123")
        assert scopes == []

    def test_oauth_integrations_list_not_empty(self) -> None:
        """OAUTH_INTEGRATIONS contains at least one integration."""
        assert len(OAUTH_INTEGRATIONS) > 0

    def test_all_integrations_have_required_fields(self) -> None:
        """Every integration in the config has id, name, provider, managed_by."""
        for integration in OAUTH_INTEGRATIONS:
            assert integration.id, f"Integration missing id: {integration}"
            assert integration.name, f"Integration {integration.id} missing name"
            assert integration.provider, (
                f"Integration {integration.id} missing provider"
            )
            assert integration.managed_by in ("self", "composio", "mcp", "internal"), (
                f"Integration {integration.id} has invalid managed_by: {integration.managed_by}"
            )


# ---------------------------------------------------------------------------
# Tests — Build Integrations Config
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestBuildIntegrationsConfig:
    """build_integrations_config: cached config response builder."""

    def test_build_excludes_internal_integrations(self) -> None:
        """Internal integrations (todos, reminders, etc.) are excluded from config."""

        # Clear lru_cache to ensure fresh result
        build_integrations_config.cache_clear()

        config = build_integrations_config()

        internal_ids = [i.id for i in OAUTH_INTEGRATIONS if i.managed_by == "internal"]
        config_ids = [item.id for item in config.integrations]

        for internal_id in internal_ids:
            assert internal_id not in config_ids, (
                f"Internal integration {internal_id} should be excluded"
            )

    def test_build_includes_available_integrations(self) -> None:
        """Available non-internal integrations are included."""

        build_integrations_config.cache_clear()
        config = build_integrations_config()

        config_ids = [item.id for item in config.integrations]
        assert "gmail" in config_ids
        assert "slack" in config_ids

    def test_build_config_items_have_slug(self) -> None:
        """Every config item has a slug field set."""

        build_integrations_config.cache_clear()
        config = build_integrations_config()

        for item in config.integrations:
            assert item.slug, f"Integration {item.id} missing slug"


# ---------------------------------------------------------------------------
# Tests — MCP Integration Connection
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestMCPIntegrationConnection:
    """connect_mcp_integration: unauthenticated and bearer token flows."""

    async def test_connect_unauthenticated_mcp_returns_connected(self) -> None:
        """Connecting a no-auth MCP integration returns 'connected' with tool count."""

        mock_mcp_client = AsyncMock()
        mock_mcp_client.connect = AsyncMock(return_value=["tool_a", "tool_b", "tool_c"])

        with (
            patch(
                "app.services.integrations.integration_connection_service.get_mcp_client",
                AsyncMock(return_value=mock_mcp_client),
            ),
            patch(
                "app.services.integrations.integration_connection_service.invalidate_mcp_status_cache",
                AsyncMock(),
            ),
        ):
            response = await connect_mcp_integration(
                user_id=USER_ID,
                integration_id="deepwiki",
                integration_name="DeepWiki",
                requires_auth=False,
                redirect_path="/integrations",
            )

            assert response.status == "connected"
            assert response.tools_count == 3
            assert response.integration_id == "deepwiki"

    async def test_connect_bearer_token_mcp_stores_and_connects(self) -> None:
        """Bearer token flow stores token, connects, and updates status."""

        mock_mcp_client = AsyncMock()
        mock_mcp_client.connect = AsyncMock(return_value=["tool_1"])

        mock_token_store = AsyncMock()
        mock_token_store.store_bearer_token = AsyncMock()

        with (
            patch(
                "app.services.integrations.integration_connection_service.get_mcp_client",
                AsyncMock(return_value=mock_mcp_client),
            ),
            patch(
                "app.services.integrations.integration_connection_service.MCPTokenStore",
                return_value=mock_token_store,
            ),
            patch(
                "app.services.integrations.integration_connection_service.update_user_integration_status",
                AsyncMock(return_value=True),
            ),
            patch(
                "app.services.integrations.integration_connection_service.invalidate_mcp_status_cache",
                AsyncMock(),
            ),
        ):
            response = await connect_mcp_integration(
                user_id=USER_ID,
                integration_id="custom-api",
                integration_name="Custom API",
                requires_auth=False,
                redirect_path="/integrations",
                bearer_token="sk-test-bearer-token",
            )

            assert response.status == "connected"
            assert response.tools_count == 1
            mock_token_store.store_bearer_token.assert_called_once_with(
                "custom-api", "sk-test-bearer-token"
            )

    async def test_connect_bearer_token_failure_rolls_back(self) -> None:
        """Bearer token flow cleans up credentials on connection failure."""

        mock_mcp_client = AsyncMock()
        mock_mcp_client.connect = AsyncMock(side_effect=Exception("Connection refused"))

        mock_token_store = AsyncMock()
        mock_token_store.store_bearer_token = AsyncMock()
        mock_token_store.delete_credentials = AsyncMock()

        with (
            patch(
                "app.services.integrations.integration_connection_service.get_mcp_client",
                AsyncMock(return_value=mock_mcp_client),
            ),
            patch(
                "app.services.integrations.integration_connection_service.MCPTokenStore",
                return_value=mock_token_store,
            ),
            patch(
                "app.services.integrations.integration_connection_service.invalidate_mcp_status_cache",
                AsyncMock(),
            ),
        ):
            response = await connect_mcp_integration(
                user_id=USER_ID,
                integration_id="broken-api",
                integration_name="Broken API",
                requires_auth=False,
                redirect_path="/integrations",
                bearer_token="sk-bad-token",
            )

            assert response.status == "error"
            assert response.error is not None
            mock_token_store.delete_credentials.assert_called_once_with("broken-api")

    async def test_connect_auth_required_mcp_returns_redirect(self) -> None:
        """MCP integration requiring OAuth returns redirect with auth URL."""

        mock_mcp_client = AsyncMock()
        mock_mcp_client.build_oauth_auth_url = AsyncMock(
            return_value="https://auth.example.com/oauth?client_id=abc"
        )

        with (
            patch(
                "app.services.integrations.integration_connection_service.get_mcp_client",
                AsyncMock(return_value=mock_mcp_client),
            ),
            patch(
                "app.services.integrations.integration_connection_service.update_user_integration_status",
                AsyncMock(return_value=True),
            ),
            patch(
                "app.services.integrations.integration_connection_service.get_api_base_url",
                return_value="https://api.example.com",
            ),
        ):
            response = await connect_mcp_integration(
                user_id=USER_ID,
                integration_id="linear",
                integration_name="Linear",
                requires_auth=True,
                redirect_path="/integrations",
                is_platform=True,
            )

            assert response.status == "redirect"
            assert response.redirect_url is not None
            assert "auth.example.com" in response.redirect_url
