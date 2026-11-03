"""revoke_integration_tokens: revokes only when discovery and an MCP config both exist."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.constants.log_tags import LogTag
from app.services.integrations.integration_resolver import IntegrationResolver
from app.services.mcp import token_management
from app.services.mcp.token_management import revoke_integration_tokens
from shared.py.wide_events import log

INTEGRATION_ID = "custom_revoke"


def _store(discovery: object, *, error: Exception | None = None) -> MagicMock:
    store = MagicMock()
    store.get_oauth_discovery = AsyncMock(return_value=discovery, side_effect=error)
    return store


@pytest.mark.unit
class TestRevokeIntegrationTokens:
    async def test_without_discovery_nothing_is_resolved_or_revoked(self) -> None:
        store = _store(None)

        with (
            patch.object(IntegrationResolver, "resolve", AsyncMock()) as resolve,
            patch.object(token_management, "revoke_tokens", AsyncMock()) as revoke,
        ):
            await revoke_integration_tokens(store, INTEGRATION_ID)

        store.get_oauth_discovery.assert_awaited_once_with(INTEGRATION_ID)
        resolve.assert_not_awaited()
        revoke.assert_not_awaited()

    async def test_unresolvable_integration_is_not_revoked(self) -> None:
        store = _store(object())

        with (
            patch.object(IntegrationResolver, "resolve", AsyncMock(return_value=None)) as resolve,
            patch.object(token_management, "revoke_tokens", AsyncMock()) as revoke,
        ):
            await revoke_integration_tokens(store, INTEGRATION_ID)

        resolve.assert_awaited_once_with(INTEGRATION_ID)
        revoke.assert_not_awaited()

    async def test_integration_without_mcp_config_is_not_revoked(self) -> None:
        store = _store(object())
        resolved = SimpleNamespace(mcp_config=None)

        with (
            patch.object(IntegrationResolver, "resolve", AsyncMock(return_value=resolved)),
            patch.object(token_management, "revoke_tokens", AsyncMock()) as revoke,
        ):
            await revoke_integration_tokens(store, INTEGRATION_ID)

        revoke.assert_not_awaited()

    async def test_revokes_with_the_stored_discovery_and_resolved_config(self) -> None:
        discovery = object()
        mcp_config = object()
        store = _store(discovery)
        resolved = SimpleNamespace(mcp_config=mcp_config)

        with (
            patch.object(IntegrationResolver, "resolve", AsyncMock(return_value=resolved)),
            patch.object(token_management, "revoke_tokens", AsyncMock()) as revoke,
        ):
            await revoke_integration_tokens(store, INTEGRATION_ID)

        revoke.assert_awaited_once_with(store, INTEGRATION_ID, mcp_config, discovery)

    async def test_failure_is_logged_and_swallowed(self) -> None:
        store = _store(None, error=RuntimeError("db down"))

        with patch.object(log, "warning") as warning:
            await revoke_integration_tokens(store, INTEGRATION_ID)

        warning.assert_called_once_with(
            f"{LogTag.MCP} Token revocation failed for",
            integration_id=INTEGRATION_ID,
            error="db down",
            error_type="RuntimeError",
        )
