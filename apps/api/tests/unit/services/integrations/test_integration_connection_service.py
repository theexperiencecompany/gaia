"""Regression: a connect failure must reach the toast as plain copy, not a provider exception dump."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.integrations import integration_connection_service as service

COMPOSIO_DUMP = (
    "Error code: 404 - {'error': {'message': 'Auth config not found', 'code': 302, "
    "'slug': 'Auth_Config_NotFound', 'status': 404, 'request_id': 'abc'}}"
)


@pytest.mark.asyncio
async def test_connect_failure_hides_provider_exception_text() -> None:
    resolved = MagicMock(source="platform", managed_by="composio")
    resolved.name = "Trello"
    resolved.platform_integration.available = True
    resolved.platform_integration.provider = "trello"
    with (
        patch.object(
            service.IntegrationResolver,
            "resolve",
            new_callable=AsyncMock,
            return_value=resolved,
        ),
        patch.object(
            service,
            "connect_composio_integration",
            new_callable=AsyncMock,
            side_effect=RuntimeError(COMPOSIO_DUMP),
        ),
    ):
        result = await service.initiate_integration_connection("u1", "trello")

    assert result is not None
    assert result.status == "error"
    assert "Auth config" not in (result.error or "")
    assert "Trello" in (result.error or "")


@pytest.mark.asyncio
async def test_mcp_connect_failure_hides_exception_text() -> None:
    target = MagicMock(is_platform=True, integration_id="x", integration_name="Acme", user_id="u1")
    result = await service._handle_connect_failure(target, RuntimeError(COMPOSIO_DUMP))

    assert result.status == "error"
    assert "Auth config" not in (result.error or "")
    assert "Acme" in (result.error or "")


@pytest.mark.asyncio
async def test_bearer_connect_failure_hides_exception_text() -> None:
    mcp_client = MagicMock()
    mcp_client.connect = AsyncMock(side_effect=RuntimeError(COMPOSIO_DUMP))
    with (
        patch.object(service, "MCPTokenStore") as token_store_cls,
        patch.object(service, "invalidate_user_integration_caches", new_callable=AsyncMock),
    ):
        token_store = token_store_cls.return_value
        token_store.store_bearer_token = AsyncMock()
        token_store.delete_credentials = AsyncMock()
        result = await service._connect_with_bearer_token("u1", "x", "Acme", "tok", mcp_client)

    assert result.status == "error"
    assert "Auth config" not in (result.error or "")
    assert "Acme" in (result.error or "")
    token_store.delete_credentials.assert_awaited_once_with("x")
