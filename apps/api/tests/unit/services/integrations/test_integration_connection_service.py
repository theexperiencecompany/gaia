"""Regression: a connect failure must reach the toast as plain copy, not a provider exception dump."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from tests.helpers import captured_wide_event

from app.services.integrations import integration_connection_service as service

COMPOSIO_DUMP = (
    "Error code: 404 - {'error': {'message': 'Auth config not found', 'code': 302, "
    "'slug': 'Auth_Config_NotFound', 'status': 404, 'request_id': 'abc'}}"
)


@pytest.mark.regression
@pytest.mark.asyncio
async def test_connect_failure_hides_provider_exception_text() -> None:
    resolved = MagicMock(source="platform", managed_by="composio")
    resolved.name = "Trello"
    resolved.platform_integration.available = True
    resolved.platform_integration.provider = "trello"
    resolved.integration_id = "trello"
    with patch.object(
        service,
        "connect_composio_integration",
        new_callable=AsyncMock,
        side_effect=RuntimeError(COMPOSIO_DUMP),
    ):
        result = await service.initiate_integration_connection("u1", resolved)

    assert result.status == "error"
    assert "Auth config" not in (result.error or "")
    assert "Trello" in (result.error or "")


@pytest.mark.regression
@pytest.mark.asyncio
async def test_mcp_connect_failure_hides_exception_text() -> None:
    target = MagicMock(is_platform=True, integration_id="x", integration_name="Acme", user_id="u1")
    result = await service._handle_connect_failure(target, RuntimeError(COMPOSIO_DUMP))

    assert result.status == "error"
    assert "Auth config" not in (result.error or "")
    assert "Acme" in (result.error or "")


@pytest.mark.regression
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
        target = service._McpConnectTarget(
            user_id="u1",
            integration_id="x",
            integration_name="Acme",
            redirect_path="/integrations",
            is_platform=True,
        )
        result = await service._connect_with_bearer_token(target, "tok", mcp_client)

    assert result.status == "error"
    assert "Auth config" not in (result.error or "")
    assert "Acme" in (result.error or "")
    token_store.delete_credentials.assert_awaited_once_with("x")


@pytest.mark.regression
@pytest.mark.asyncio
async def test_bearer_connect_failure_is_logged() -> None:
    mcp_client = MagicMock()
    mcp_client.connect = AsyncMock(side_effect=RuntimeError(COMPOSIO_DUMP))
    with (
        patch.object(service, "get_mcp_client", new_callable=AsyncMock, return_value=mcp_client),
        patch.object(service, "MCPTokenStore") as token_store_cls,
        patch.object(
            service, "invalidate_user_integration_caches", new_callable=AsyncMock
        ) as invalidate,
        patch.object(service, "update_user_integration_status", new_callable=AsyncMock),
    ):
        token_store = token_store_cls.return_value
        token_store.store_bearer_token = AsyncMock()
        token_store.delete_credentials = AsyncMock()
        async with captured_wide_event() as event:
            result = await service.connect_mcp_integration(
                "u1", "x", "Acme", False, "/integrations", bearer_token="tok"
            )

    assert result.status == "error"
    assert [str(w.get("error")) for w in event.get("warnings", [])] == [COMPOSIO_DUMP]
    assert event["integration"]["auth_type"] == "bearer"
    invalidate.assert_awaited_once_with("u1")


@pytest.mark.parametrize(("tools", "tools_count"), [(["tool-a", "tool-b"], 2), ([], 0)])
async def test_bearer_connect_stores_the_token_and_reports_what_it_connected(
    tools: list[str], tools_count: int
) -> None:
    mcp_client = MagicMock()
    mcp_client.connect = AsyncMock(return_value=tools)
    with (
        patch.object(service, "get_mcp_client", new_callable=AsyncMock, return_value=mcp_client),
        patch.object(service, "MCPTokenStore") as token_store_cls,
        patch.object(service, "invalidate_user_integration_caches", new_callable=AsyncMock),
        patch.object(
            service, "update_user_integration_status", new_callable=AsyncMock
        ) as update_status,
    ):
        token_store = token_store_cls.return_value
        token_store.store_bearer_token = AsyncMock()
        async with captured_wide_event() as event:
            result = await service.connect_mcp_integration(
                "u1", "x", "Acme", False, "/integrations", bearer_token="tok"
            )

    token_store_cls.assert_called_once_with("u1")
    token_store.store_bearer_token.assert_awaited_once_with("x", "tok")
    mcp_client.connect.assert_awaited_once_with("x")
    update_status.assert_awaited_once_with("u1", "x", "connected")
    assert result.status == "connected"
    assert result.integration_id == "x"
    assert result.name == "Acme"
    assert result.tools_count == tools_count
    assert result.message == "Integration connected successfully"
    assert event["integration"] == {
        "provider": "Acme",
        "action": "connect_mcp",
        "status": "connected",
        "auth_type": "bearer",
        "tools_count": tools_count,
    }


def test_config_gives_native_integrations_kebab_case_slugs() -> None:
    slugs = {item.id: item.slug for item in service.build_integrations_config().integrations}

    assert slugs["google_maps"] == "google-maps"
    assert slugs["microsoft_teams"] == "microsoft-teams"
    assert slugs["gmail"] == "gmail"
    assert all("_" not in slug for slug in slugs.values())
