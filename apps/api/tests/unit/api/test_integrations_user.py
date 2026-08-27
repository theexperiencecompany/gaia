"""Unit tests for app/api/v1/endpoints/integrations/user.py"""

from datetime import UTC, datetime
from typing import Literal
from unittest.mock import AsyncMock, patch

from httpx import AsyncClient

from app.models.integration_models import UserIntegration
from app.services.analytics_service import AnalyticsEvents

# __init__.py: prefix="/integrations", user.py router mounted at /users/me/integrations
BASE = "/api/v1/integrations/users/me/integrations"

_USER = "app.api.v1.endpoints.integrations.user"


def _user_integration(status: Literal["created", "connected"] = "connected") -> UserIntegration:
    return UserIntegration(
        user_id="507f1f77bcf86cd799439011",
        integration_id="integ-001",
        status=status,
        created_at=datetime(2025, 1, 1, tzinfo=UTC),
    )


class TestAddIntegrationToWorkspace:
    """POST /api/v1/integrations/users/me/integrations"""

    async def test_add_connected_captures_event(self, client: AsyncClient) -> None:
        with (
            patch(
                f"{_USER}.add_user_integration_service",
                new_callable=AsyncMock,
                return_value=_user_integration("connected"),
            ),
            patch(f"{_USER}.capture_context_event") as mock_capture,
        ):
            resp = await client.post(BASE, json={"integration_id": "integ-001"})

        assert resp.status_code == 200
        assert resp.json()["connectionStatus"] == "connected"
        mock_capture.assert_called_once_with(
            AnalyticsEvents.INTEGRATION_CONNECTED,
            {"integration_id": "integ-001", "source": "workspace"},
        )

    async def test_add_pending_does_not_capture(self, client: AsyncClient) -> None:
        with (
            patch(
                f"{_USER}.add_user_integration_service",
                new_callable=AsyncMock,
                return_value=_user_integration("created"),
            ),
            patch(f"{_USER}.capture_context_event") as mock_capture,
        ):
            resp = await client.post(BASE, json={"integration_id": "integ-001"})

        assert resp.status_code == 200
        assert resp.json()["connectionStatus"] == "created"
        mock_capture.assert_not_called()

    async def test_add_invalid_integration_is_400(self, client: AsyncClient) -> None:
        with (
            patch(
                f"{_USER}.add_user_integration_service",
                new_callable=AsyncMock,
                side_effect=ValueError("Integration 'nope' not found"),
            ),
            patch(f"{_USER}.capture_context_event") as mock_capture,
        ):
            resp = await client.post(BASE, json={"integration_id": "nope"})

        assert resp.status_code == 400
        mock_capture.assert_not_called()


class TestRemoveIntegrationFromWorkspace:
    """DELETE /api/v1/integrations/users/me/integrations/{integration_id}"""

    async def test_remove_connected_captures_event(self, client: AsyncClient) -> None:
        with (
            patch(f"{_USER}.user_integration_repository") as mock_repo,
            patch(
                f"{_USER}.remove_user_integration",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_remove,
            patch(f"{_USER}.capture_context_event") as mock_capture,
            patch(f"{_USER}.log") as mock_log,
        ):
            mock_repo.is_connected = AsyncMock(return_value=True)
            resp = await client.delete(f"{BASE}/integ-001")

        assert resp.status_code == 200
        mock_repo.is_connected.assert_awaited_once_with("507f1f77bcf86cd799439011", "integ-001")
        mock_remove.assert_awaited_once_with("507f1f77bcf86cd799439011", "integ-001")
        mock_log.set.assert_any_call(
            operation="remove_integration_from_workspace",
            integration_id="integ-001",
            user={"id": "507f1f77bcf86cd799439011"},
            integration={"id": "integ-001"},
        )
        mock_capture.assert_called_once_with(
            AnalyticsEvents.INTEGRATION_DISCONNECTED,
            {"integration_id": "integ-001"},
        )

    async def test_remove_never_connected_does_not_capture(self, client: AsyncClient) -> None:
        with (
            patch(f"{_USER}.user_integration_repository") as mock_repo,
            patch(
                f"{_USER}.remove_user_integration",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_remove,
            patch(f"{_USER}.capture_context_event") as mock_capture,
        ):
            mock_repo.is_connected = AsyncMock(return_value=False)
            resp = await client.delete(f"{BASE}/integ-001")

        assert resp.status_code == 200
        mock_remove.assert_awaited_once_with("507f1f77bcf86cd799439011", "integ-001")
        mock_capture.assert_not_called()

    async def test_remove_status_lookup_failure_keeps_removal(self, client: AsyncClient) -> None:
        """A failed connection-status read must not block the removal — it is
        an analytics-only read."""
        with (
            patch(f"{_USER}.user_integration_repository") as mock_repo,
            patch(
                f"{_USER}.remove_user_integration",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_remove,
            patch(f"{_USER}.capture_context_event") as mock_capture,
            patch(f"{_USER}.log") as mock_log,
        ):
            mock_repo.is_connected = AsyncMock(side_effect=RuntimeError("mongo down"))
            resp = await client.delete(f"{BASE}/integ-001")

        assert resp.status_code == 200
        mock_remove.assert_awaited_once_with("507f1f77bcf86cd799439011", "integ-001")
        mock_capture.assert_not_called()
        mock_log.warning.assert_called_once()
        assert "Failed to read connection status" in mock_log.warning.call_args.args[0]
        assert mock_log.warning.call_args.kwargs["integration_id"] == "integ-001"
        assert mock_log.warning.call_args.kwargs["user_id"] == "507f1f77bcf86cd799439011"
        assert mock_log.warning.call_args.kwargs["error_type"] == "RuntimeError"
        assert mock_log.warning.call_args.kwargs["error"] == "mongo down"

    async def test_remove_not_found_is_404(self, client: AsyncClient) -> None:
        with (
            patch(f"{_USER}.user_integration_repository") as mock_repo,
            patch(
                f"{_USER}.remove_user_integration",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(f"{_USER}.capture_context_event") as mock_capture,
        ):
            mock_repo.is_connected = AsyncMock(return_value=True)
            resp = await client.delete(f"{BASE}/missing")

        assert resp.status_code == 404
        assert resp.json()["detail"] == "Integration not found in workspace"
        mock_capture.assert_not_called()
