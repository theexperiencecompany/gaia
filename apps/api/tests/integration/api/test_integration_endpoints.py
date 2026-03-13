"""Integration tests for user integration management API endpoints.

Tests the /api/v1/integrations/users/me/integrations endpoints with mocked
service layer to verify routing, auth enforcement, and response codes.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.models.integration_models import (
    IntegrationResponse,
    UserIntegration,
    UserIntegrationResponse,
    UserIntegrationsListResponse,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BASE = "/api/v1/integrations/users/me/integrations"


def _make_integration_response(**overrides) -> IntegrationResponse:
    defaults = {
        "integration_id": "gmail",
        "name": "Gmail",
        "description": "Google Mail integration",
        "category": "email",
        "managed_by": "composio",
        "source": "platform",
        "is_featured": True,
        "display_priority": 10,
        "requires_auth": True,
        "auth_type": "oauth",
        "tools": [],
    }
    defaults.update(overrides)
    return IntegrationResponse(**defaults)


def _make_user_integration_response(**overrides) -> UserIntegrationResponse:
    defaults = {
        "integration_id": "gmail",
        "status": "connected",
        "created_at": datetime.now(timezone.utc),
        "connected_at": datetime.now(timezone.utc),
        "integration": _make_integration_response(),
    }
    defaults.update(overrides)
    return UserIntegrationResponse(**defaults)


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestUserIntegrationEndpoints:
    """Test user integration REST endpoints."""

    # ------------------------------------------------------------------
    # GET /integrations/users/me/integrations
    # ------------------------------------------------------------------

    @patch(
        "app.api.v1.endpoints.integrations.user.get_user_integrations",
        new_callable=AsyncMock,
    )
    async def test_list_user_integrations_returns_200(self, mock_get, test_client):
        """GET user integrations should return 200 with correct response structure."""
        mock_get.return_value = UserIntegrationsListResponse(
            integrations=[_make_user_integration_response()],
            total=1,
        )

        response = await test_client.get(_BASE)

        assert response.status_code == 200
        data = response.json()
        assert "integrations" in data
        assert "total" in data
        assert data["total"] == 1
        assert len(data["integrations"]) == 1

    @patch(
        "app.api.v1.endpoints.integrations.user.get_user_integrations",
        new_callable=AsyncMock,
    )
    async def test_list_user_integrations_empty_returns_200(
        self, mock_get, test_client
    ):
        """GET user integrations with no items should return 200 and empty list."""
        mock_get.return_value = UserIntegrationsListResponse(
            integrations=[],
            total=0,
        )

        response = await test_client.get(_BASE)

        assert response.status_code == 200
        data = response.json()
        assert data["integrations"] == []
        assert data["total"] == 0

    @patch(
        "app.api.v1.endpoints.integrations.user.get_user_integrations",
        new_callable=AsyncMock,
    )
    async def test_list_user_integrations_response_shape(self, mock_get, test_client):
        """GET user integrations response should include nested integration fields."""
        mock_get.return_value = UserIntegrationsListResponse(
            integrations=[_make_user_integration_response()],
            total=1,
        )

        response = await test_client.get(_BASE)
        data = response.json()
        item = data["integrations"][0]

        # CamelCase aliases are used in JSON output
        assert "integrationId" in item
        assert "status" in item
        assert "createdAt" in item
        assert "integration" in item
        integration = item["integration"]
        assert "integrationId" in integration
        assert "name" in integration
        assert "category" in integration

    @patch(
        "app.api.v1.endpoints.integrations.user.get_user_integrations",
        new_callable=AsyncMock,
    )
    async def test_list_user_integrations_service_error_returns_500(
        self, mock_get, test_client
    ):
        """GET user integrations should return 500 when service raises."""
        mock_get.side_effect = RuntimeError("DB connection lost")

        response = await test_client.get(_BASE)

        assert response.status_code == 500
        assert "Failed to fetch user integrations" in response.json()["detail"]

    async def test_list_user_integrations_requires_auth(self, unauthenticated_client):
        """GET user integrations without auth should return 401."""
        response = await unauthenticated_client.get(_BASE)
        assert response.status_code == 401

    # ------------------------------------------------------------------
    # POST /integrations/users/me/integrations
    # ------------------------------------------------------------------

    @patch(
        "app.api.v1.endpoints.integrations.user.add_user_integration_service",
        new_callable=AsyncMock,
    )
    async def test_add_integration_returns_200(self, mock_add, test_client):
        """POST to add integration should return 200 with correct response."""
        mock_add.return_value = UserIntegration(
            user_id="integration-test-user-1",
            integration_id="gmail",
            status="created",
            created_at=datetime.now(timezone.utc),
        )

        response = await test_client.post(
            _BASE,
            json={"integration_id": "gmail"},
        )

        assert response.status_code == 200
        data = response.json()
        assert "message" in data
        assert data["message"] == "Integration added to workspace"
        assert "integrationId" in data
        assert data["integrationId"] == "gmail"
        assert "connectionStatus" in data

    @patch(
        "app.api.v1.endpoints.integrations.user.add_user_integration_service",
        new_callable=AsyncMock,
    )
    async def test_add_integration_already_exists_returns_400(
        self, mock_add, test_client
    ):
        """POST to add duplicate integration should return 400."""
        mock_add.side_effect = ValueError(
            "Integration 'gmail' already added to workspace"
        )

        response = await test_client.post(
            _BASE,
            json={"integration_id": "gmail"},
        )

        assert response.status_code == 400
        assert "already added" in response.json()["detail"]

    @patch(
        "app.api.v1.endpoints.integrations.user.add_user_integration_service",
        new_callable=AsyncMock,
    )
    async def test_add_integration_not_found_returns_400(self, mock_add, test_client):
        """POST with unknown integration_id should return 400."""
        mock_add.side_effect = ValueError("Integration 'unknown' not found")

        response = await test_client.post(
            _BASE,
            json={"integration_id": "unknown"},
        )

        assert response.status_code == 400

    @patch(
        "app.api.v1.endpoints.integrations.user.add_user_integration_service",
        new_callable=AsyncMock,
    )
    async def test_add_integration_service_error_returns_500(
        self, mock_add, test_client
    ):
        """POST should return 500 when service raises unexpected error."""
        mock_add.side_effect = RuntimeError("Unexpected DB error")

        response = await test_client.post(
            _BASE,
            json={"integration_id": "gmail"},
        )

        assert response.status_code == 500
        assert "Failed to add integration" in response.json()["detail"]

    async def test_add_integration_requires_auth(self, unauthenticated_client):
        """POST without auth should return 401."""
        response = await unauthenticated_client.post(
            _BASE,
            json={"integration_id": "gmail"},
        )
        assert response.status_code == 401

    @patch(
        "app.api.v1.endpoints.integrations.user.add_user_integration_service",
        new_callable=AsyncMock,
    )
    async def test_add_integration_status_connected(self, mock_add, test_client):
        """POST should return connectionStatus='connected' for non-auth integrations."""
        mock_add.return_value = UserIntegration(
            user_id="integration-test-user-1",
            integration_id="gcal",
            status="connected",
            created_at=datetime.now(timezone.utc),
            connected_at=datetime.now(timezone.utc),
        )

        response = await test_client.post(
            _BASE,
            json={"integration_id": "gcal"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["connectionStatus"] == "connected"

    # ------------------------------------------------------------------
    # DELETE /integrations/users/me/integrations/{integration_id}
    # ------------------------------------------------------------------

    @patch(
        "app.api.v1.endpoints.integrations.user.remove_user_integration",
        new_callable=AsyncMock,
    )
    async def test_remove_integration_returns_200(self, mock_remove, test_client):
        """DELETE integration should return 200 with success message."""
        mock_remove.return_value = True

        response = await test_client.delete(f"{_BASE}/gmail")

        assert response.status_code == 200
        data = response.json()
        assert "message" in data
        assert data["message"] == "Integration removed from workspace"
        assert "integrationId" in data
        assert data["integrationId"] == "gmail"

    @patch(
        "app.api.v1.endpoints.integrations.user.remove_user_integration",
        new_callable=AsyncMock,
    )
    async def test_remove_integration_not_found_returns_404(
        self, mock_remove, test_client
    ):
        """DELETE non-existent integration should return 404."""
        mock_remove.return_value = False

        response = await test_client.delete(f"{_BASE}/nonexistent")

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    @patch(
        "app.api.v1.endpoints.integrations.user.remove_user_integration",
        new_callable=AsyncMock,
    )
    async def test_remove_integration_service_error_returns_500(
        self, mock_remove, test_client
    ):
        """DELETE should return 500 when service raises unexpected error."""
        mock_remove.side_effect = RuntimeError("DB write failed")

        response = await test_client.delete(f"{_BASE}/gmail")

        assert response.status_code == 500
        assert "Failed to remove integration" in response.json()["detail"]

    async def test_remove_integration_requires_auth(self, unauthenticated_client):
        """DELETE without auth should return 401."""
        response = await unauthenticated_client.delete(f"{_BASE}/gmail")
        assert response.status_code == 401

    @patch(
        "app.api.v1.endpoints.integrations.user.remove_user_integration",
        new_callable=AsyncMock,
    )
    async def test_remove_integration_passes_correct_id(self, mock_remove, test_client):
        """DELETE should call service with the integration_id from the path."""
        mock_remove.return_value = True

        await test_client.delete(f"{_BASE}/slack")

        mock_remove.assert_called_once()
        call_args = mock_remove.call_args
        # second positional arg is integration_id
        assert call_args.args[1] == "slack"


# ---------------------------------------------------------------------------
# Auth enforcement tests
# These tests verify that ALL endpoints reject unauthenticated requests with
# 401. If auth enforcement is removed, these tests MUST fail.
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestIntegrationEndpointAuthEnforcement:
    """Verify all integration endpoints enforce authentication.

    These tests use the unauthenticated_client fixture which does NOT inject
    a user into the request state. If the Depends(get_user_id) guard is removed
    from any endpoint, the corresponding test will fail.
    """

    async def test_list_integrations_unauthenticated_returns_401(
        self, unauthenticated_client
    ):
        """GET /integrations/users/me/integrations without auth must return 401."""
        response = await unauthenticated_client.get(_BASE)
        assert response.status_code == 401

    async def test_add_integration_unauthenticated_returns_401(
        self, unauthenticated_client
    ):
        """POST /integrations/users/me/integrations without auth must return 401."""
        response = await unauthenticated_client.post(
            _BASE, json={"integration_id": "gmail"}
        )
        assert response.status_code == 401

    async def test_remove_integration_unauthenticated_returns_401(
        self, unauthenticated_client
    ):
        """DELETE /integrations/users/me/integrations/{id} without auth must return 401."""
        response = await unauthenticated_client.delete(f"{_BASE}/gmail")
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# Endpoint logic tests – mock at the immediate dependency boundary
# These test that the endpoint's OWN branching logic (not just service results)
# produces the correct HTTP status codes. The service is mocked at the point
# where the endpoint calls it so the endpoint's error mapping is exercised.
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestIntegrationEndpointLogic:
    """Test endpoint-level decision logic for integration routes.

    Mocking is done at the service function level (the outermost function the
    endpoint directly awaits). This ensures the endpoint's own try/except blocks,
    ValueError → 400 mapping, and False-return → 404 mapping are tested and
    would fail if that logic were deleted.
    """

    @patch(
        "app.api.v1.endpoints.integrations.user.add_user_integration_service",
        new_callable=AsyncMock,
    )
    async def test_add_already_connected_integration_returns_400(
        self, mock_add, test_client
    ):
        """POST with an already-connected integration must return 400.

        The endpoint maps ValueError to 400. If that mapping is removed,
        this test fails.
        """
        mock_add.side_effect = ValueError(
            "Integration 'gmail' already added to workspace"
        )

        response = await test_client.post(_BASE, json={"integration_id": "gmail"})

        assert response.status_code == 400
        detail = response.json()["detail"]
        assert "already" in detail.lower()

    @patch(
        "app.api.v1.endpoints.integrations.user.remove_user_integration",
        new_callable=AsyncMock,
    )
    async def test_remove_nonexistent_integration_returns_404(
        self, mock_remove, test_client
    ):
        """DELETE a non-existent integration must return 404.

        The endpoint checks the bool return value of remove_user_integration
        and raises HTTPException(404) when False. If that check is removed,
        this test fails because a 200 would be returned instead.
        """
        mock_remove.return_value = False

        response = await test_client.delete(f"{_BASE}/does-not-exist")

        assert response.status_code == 404
        detail = response.json()["detail"].lower()
        assert "not found" in detail

    @patch(
        "app.api.v1.endpoints.integrations.user.remove_user_integration",
        new_callable=AsyncMock,
    )
    async def test_remove_existing_integration_does_not_return_404(
        self, mock_remove, test_client
    ):
        """DELETE an existing integration must NOT return 404.

        Complements test_remove_nonexistent_integration_returns_404 – ensures
        the 404 is only raised when remove returns False, not on success.
        """
        mock_remove.return_value = True

        response = await test_client.delete(f"{_BASE}/gmail")

        assert response.status_code == 200

    @patch(
        "app.api.v1.endpoints.integrations.user.add_user_integration_service",
        new_callable=AsyncMock,
    )
    async def test_add_integration_unknown_id_returns_400(self, mock_add, test_client):
        """POST with unknown integration_id must return 400, not 404 or 500.

        The service raises ValueError for unknown IDs; the endpoint must map
        this to a 400 response.
        """
        mock_add.side_effect = ValueError("Integration 'unknown-xyz' not found")

        response = await test_client.post(_BASE, json={"integration_id": "unknown-xyz"})

        assert response.status_code == 400
