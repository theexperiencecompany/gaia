"""Tests for app/api/v1/endpoints/integrations/custom.py"""

from unittest.mock import AsyncMock, MagicMock, patch

from httpx import AsyncClient
import pytest

from app.models.integration_models import (
    CreateCustomIntegrationRequest,
    Integration,
    UpdateCustomIntegrationRequest,
)
from app.services.analytics_service import AnalyticsEvents
from app.services.integrations.publish_service import PublishError

# __init__.py: prefix="/integrations", custom.py router mounted at /custom
BASE = "/api/v1/integrations/custom"

_CUSTOM = "app.api.v1.endpoints.integrations.custom"

FAKE_USER_ID = "507f1f77bcf86cd799439011"


def _integration(integration_id: str = "i1", name: str = "My Tool") -> Integration:
    return Integration.model_validate(
        {
            "integration_id": integration_id,
            "name": name,
            "description": "A custom integration",
            "category": "custom",
            "managed_by": "mcp",
            "source": "custom",
            "is_public": True,
            "mcp_config": {
                "server_url": "https://mcp.example.com",
                "requires_auth": False,
                "auth_type": "none",
            },
        }
    )


def _create_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": "My Tool",
        "server_url": "https://mcp.example.com",
    }
    payload.update(overrides)
    return payload


class TestCreateCustomIntegration:
    """Tests for POST /api/v1/integrations/custom."""

    @pytest.mark.asyncio
    async def test_create_connected(self, client: AsyncClient) -> None:
        with (
            patch(f"{_CUSTOM}.get_mcp_client", new_callable=AsyncMock) as mock_mcp,
            patch(
                f"{_CUSTOM}.create_and_connect_custom_integration", new_callable=AsyncMock
            ) as mock_create,
            patch(f"{_CUSTOM}.capture_context_event") as mock_capture,
        ):
            mock_mcp.return_value = MagicMock()
            mock_create.return_value = (
                _integration(),
                {"status": "connected", "tools_count": 3},
            )
            resp = await client.post(BASE, json=_create_payload())

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "success"
        assert body["message"] == "Custom integration created"
        assert body["integrationId"] == "i1"
        assert body["name"] == "My Tool"
        assert body["connection"] == {
            "status": "connected",
            "toolsCount": 3,
            "oauthUrl": None,
            "error": None,
        }
        mock_capture.assert_called_once_with(
            AnalyticsEvents.INTEGRATION_CONNECTED,
            {"integration_id": "i1", "auth_type": "none"},
        )

    async def test_create_bearer_integration_captures_auth_type(self, client: AsyncClient) -> None:
        """A bearer-token connect reports auth_type=bearer."""
        with (
            patch(f"{_CUSTOM}.get_mcp_client", new_callable=AsyncMock) as mock_mcp,
            patch(
                f"{_CUSTOM}.create_and_connect_custom_integration", new_callable=AsyncMock
            ) as mock_create,
            patch(f"{_CUSTOM}.capture_context_event") as mock_capture,
        ):
            mock_mcp.return_value = MagicMock()
            mock_create.return_value = (
                _integration(),
                {"status": "connected", "tools_count": 3},
            )
            resp = await client.post(BASE, json=_create_payload(bearer_token="tok-123"))

        assert resp.status_code == 200
        mock_capture.assert_called_once_with(
            AnalyticsEvents.INTEGRATION_CONNECTED,
            {"integration_id": "i1", "auth_type": "bearer"},
        )

        mock_mcp.assert_awaited_once_with(user_id=FAKE_USER_ID)
        assert mock_create.await_count == 1
        user_id, request_model, mcp_client = mock_create.await_args.args
        assert user_id == FAKE_USER_ID
        assert isinstance(request_model, CreateCustomIntegrationRequest)
        assert request_model.name == "My Tool"
        assert request_model.server_url == "https://mcp.example.com"
        assert request_model.requires_auth is False
        assert request_model.is_public is False
        assert mcp_client is mock_mcp.return_value

    @pytest.mark.asyncio
    async def test_create_requires_oauth(self, client: AsyncClient) -> None:
        with (
            patch(f"{_CUSTOM}.get_mcp_client", new_callable=AsyncMock, return_value=MagicMock()),
            patch(
                f"{_CUSTOM}.create_and_connect_custom_integration", new_callable=AsyncMock
            ) as mock_create,
        ):
            mock_create.return_value = (
                _integration(),
                {"status": "requires_oauth", "oauth_url": "https://auth.example.com/start"},
            )
            resp = await client.post(BASE, json=_create_payload())

        assert resp.status_code == 200
        assert resp.json()["connection"] == {
            "status": "requires_oauth",
            "toolsCount": None,
            "oauthUrl": "https://auth.example.com/start",
            "error": None,
        }

    @pytest.mark.asyncio
    async def test_create_failed_connection(self, client: AsyncClient) -> None:
        with (
            patch(f"{_CUSTOM}.get_mcp_client", new_callable=AsyncMock, return_value=MagicMock()),
            patch(
                f"{_CUSTOM}.create_and_connect_custom_integration", new_callable=AsyncMock
            ) as mock_create,
        ):
            mock_create.return_value = (
                _integration(),
                {"status": "failed", "error": "connection refused"},
            )
            resp = await client.post(BASE, json=_create_payload())

        assert resp.status_code == 200
        assert resp.json()["connection"] == {
            "status": "failed",
            "toolsCount": None,
            "oauthUrl": None,
            "error": "connection refused",
        }

    @pytest.mark.asyncio
    async def test_value_error_returns_400(self, client: AsyncClient) -> None:
        with (
            patch(f"{_CUSTOM}.get_mcp_client", new_callable=AsyncMock, return_value=MagicMock()),
            patch(
                f"{_CUSTOM}.create_and_connect_custom_integration",
                new_callable=AsyncMock,
                side_effect=ValueError("bad request"),
            ),
        ):
            resp = await client.post(BASE, json=_create_payload())

        assert resp.status_code == 400
        assert resp.json()["detail"] == "bad request"

    @pytest.mark.asyncio
    async def test_unexpected_error_returns_500(self, client: AsyncClient) -> None:
        with (
            patch(f"{_CUSTOM}.get_mcp_client", new_callable=AsyncMock, return_value=MagicMock()),
            patch(
                f"{_CUSTOM}.create_and_connect_custom_integration",
                new_callable=AsyncMock,
                side_effect=RuntimeError("boom"),
            ),
        ):
            resp = await client.post(BASE, json=_create_payload())

        assert resp.status_code == 500
        assert resp.json()["detail"] == "Failed to create integration"

    @pytest.mark.asyncio
    async def test_requires_auth_without_auth_type_returns_422(self, client: AsyncClient) -> None:
        resp = await client.post(BASE, json=_create_payload(requires_auth=True))
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_non_http_server_url_returns_422(self, client: AsyncClient) -> None:
        resp = await client.post(BASE, json=_create_payload(server_url="ftp://example.com/x"))
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_private_ip_server_url_returns_422(self, client: AsyncClient) -> None:
        resp = await client.post(BASE, json=_create_payload(server_url="http://127.0.0.1:8000"))
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_missing_server_url_returns_422(self, client: AsyncClient) -> None:
        resp = await client.post(BASE, json={"name": "My Tool"})
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_empty_name_returns_422(self, client: AsyncClient) -> None:
        resp = await client.post(BASE, json=_create_payload(name=""))
        assert resp.status_code == 422


class TestUpdateCustomIntegration:
    """Tests for PATCH /api/v1/integrations/custom/{integration_id}."""

    @pytest.mark.asyncio
    async def test_happy_path(self, client: AsyncClient) -> None:
        with patch(f"{_CUSTOM}.update_custom_integration", new_callable=AsyncMock) as mock_update:
            mock_update.return_value = _integration()
            resp = await client.patch(
                f"{BASE}/i1", json={"name": "Renamed Tool", "is_public": True}
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "success"
        assert body["message"] == "Integration updated"
        assert body["integrationId"] == "i1"

        assert mock_update.await_count == 1
        user_id, integration_id, request_model = mock_update.await_args.args
        assert user_id == FAKE_USER_ID
        assert integration_id == "i1"
        assert isinstance(request_model, UpdateCustomIntegrationRequest)
        assert request_model.name == "Renamed Tool"
        assert request_model.is_public is True

    @pytest.mark.asyncio
    async def test_not_owner_returns_404(self, client: AsyncClient) -> None:
        with patch(f"{_CUSTOM}.update_custom_integration", new_callable=AsyncMock) as mock_update:
            mock_update.return_value = None
            resp = await client.patch(f"{BASE}/i1", json={"name": "Renamed"})

        assert resp.status_code == 404
        assert resp.json()["detail"] == "Integration not found or you are not the owner"

    @pytest.mark.asyncio
    async def test_unexpected_error_returns_500(self, client: AsyncClient) -> None:
        with patch(
            f"{_CUSTOM}.update_custom_integration",
            new_callable=AsyncMock,
            side_effect=RuntimeError("boom"),
        ):
            resp = await client.patch(f"{BASE}/i1", json={"name": "Renamed"})

        assert resp.status_code == 500
        assert resp.json()["detail"] == "Failed to update integration"

    @pytest.mark.asyncio
    async def test_private_ip_server_url_returns_422(self, client: AsyncClient) -> None:
        resp = await client.patch(f"{BASE}/i1", json={"server_url": "http://10.0.0.5:8000"})
        assert resp.status_code == 422


class TestDeleteCustomIntegration:
    """Tests for DELETE /api/v1/integrations/custom/{integration_id}."""

    @pytest.mark.asyncio
    async def test_happy_path(self, client: AsyncClient) -> None:
        with patch(f"{_CUSTOM}.delete_custom_integration", new_callable=AsyncMock) as mock_delete:
            mock_delete.return_value = True
            resp = await client.delete(f"{BASE}/i1")

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "success"
        assert body["message"] == "Integration deleted"
        assert body["integrationId"] == "i1"
        mock_delete.assert_awaited_once_with(FAKE_USER_ID, "i1")

    @pytest.mark.asyncio
    async def test_not_owner_returns_404(self, client: AsyncClient) -> None:
        with patch(f"{_CUSTOM}.delete_custom_integration", new_callable=AsyncMock) as mock_delete:
            mock_delete.return_value = False
            resp = await client.delete(f"{BASE}/i1")

        assert resp.status_code == 404
        assert resp.json()["detail"] == "Integration not found or you are not the owner"

    @pytest.mark.asyncio
    async def test_unexpected_error_returns_500(self, client: AsyncClient) -> None:
        with patch(
            f"{_CUSTOM}.delete_custom_integration",
            new_callable=AsyncMock,
            side_effect=RuntimeError("boom"),
        ):
            resp = await client.delete(f"{BASE}/i1")

        assert resp.status_code == 500
        assert resp.json()["detail"] == "Failed to delete integration"


class TestPublishIntegration:
    """Tests for POST /api/v1/integrations/custom/{integration_id}/publish."""

    @pytest.mark.asyncio
    async def test_happy_path(self, client: AsyncClient) -> None:
        with patch(f"{_CUSTOM}.publish_custom_integration", new_callable=AsyncMock) as mock_publish:
            mock_publish.return_value = {
                "integration_id": "i1",
                "public_url": "/marketplace/my-tool",
            }
            resp = await client.post(f"{BASE}/i1/publish")

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "success"
        assert body["message"] == "Integration published successfully"
        assert body["integrationId"] == "i1"
        assert body["publicUrl"] == "/marketplace/my-tool"
        mock_publish.assert_awaited_once_with("i1", FAKE_USER_ID)

    @pytest.mark.asyncio
    async def test_publish_error_not_found_returns_404(self, client: AsyncClient) -> None:
        with patch(
            f"{_CUSTOM}.publish_custom_integration",
            new_callable=AsyncMock,
            side_effect=PublishError("Integration not found", 404),
        ):
            resp = await client.post(f"{BASE}/i1/publish")

        assert resp.status_code == 404
        assert resp.json()["detail"] == "Integration not found"

    @pytest.mark.asyncio
    async def test_publish_error_forbidden_returns_403(self, client: AsyncClient) -> None:
        with patch(
            f"{_CUSTOM}.publish_custom_integration",
            new_callable=AsyncMock,
            side_effect=PublishError("You can only publish integrations you created", 403),
        ):
            resp = await client.post(f"{BASE}/i1/publish")

        assert resp.status_code == 403
        assert resp.json()["detail"] == "You can only publish integrations you created"

    @pytest.mark.asyncio
    async def test_unexpected_error_returns_500(self, client: AsyncClient) -> None:
        with patch(
            f"{_CUSTOM}.publish_custom_integration",
            new_callable=AsyncMock,
            side_effect=RuntimeError("boom"),
        ):
            resp = await client.post(f"{BASE}/i1/publish")

        assert resp.status_code == 500
        assert resp.json()["detail"] == "Failed to publish integration"


class TestUnpublishIntegration:
    """Tests for POST /api/v1/integrations/custom/{integration_id}/unpublish."""

    @pytest.mark.asyncio
    async def test_happy_path(self, client: AsyncClient) -> None:
        with patch(
            f"{_CUSTOM}.unpublish_custom_integration", new_callable=AsyncMock
        ) as mock_unpublish:
            mock_unpublish.return_value = {"integration_id": "i1"}
            resp = await client.post(f"{BASE}/i1/unpublish")

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "success"
        assert body["message"] == "Integration unpublished successfully"
        assert body["integrationId"] == "i1"
        mock_unpublish.assert_awaited_once_with("i1", FAKE_USER_ID)

    @pytest.mark.asyncio
    async def test_unpublish_error_returns_404(self, client: AsyncClient) -> None:
        with patch(
            f"{_CUSTOM}.unpublish_custom_integration",
            new_callable=AsyncMock,
            side_effect=PublishError("Integration not found", 404),
        ):
            resp = await client.post(f"{BASE}/i1/unpublish")

        assert resp.status_code == 404
        assert resp.json()["detail"] == "Integration not found"

    @pytest.mark.asyncio
    async def test_unpublish_error_not_published_returns_400(self, client: AsyncClient) -> None:
        with patch(
            f"{_CUSTOM}.unpublish_custom_integration",
            new_callable=AsyncMock,
            side_effect=PublishError("Integration is not currently published"),
        ):
            resp = await client.post(f"{BASE}/i1/unpublish")

        assert resp.status_code == 400
        assert resp.json()["detail"] == "Integration is not currently published"

    @pytest.mark.asyncio
    async def test_unexpected_error_returns_500(self, client: AsyncClient) -> None:
        with patch(
            f"{_CUSTOM}.unpublish_custom_integration",
            new_callable=AsyncMock,
            side_effect=RuntimeError("boom"),
        ):
            resp = await client.post(f"{BASE}/i1/unpublish")

        assert resp.status_code == 500
        assert resp.json()["detail"] == "Failed to unpublish integration"
