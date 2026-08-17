"""Endpoint tests for /api/v1/support.

Covers the MAX_PAGE_NUMBER page bound on the my-requests list and the
happy path with the service faked.
"""

from unittest.mock import AsyncMock, patch

from httpx import AsyncClient

from app.constants.general import MAX_PAGE_NUMBER
from app.models.support_models import SupportRequestSubmissionResponse
from app.services.analytics_service import AnalyticsEvents

SUPPORT_ENDPOINT = "app.api.v1.endpoints.support"


class TestGetMySupportRequests:
    """GET /api/v1/support/requests/my"""

    async def test_page_over_max_returns_422(self, client: AsyncClient) -> None:
        resp = await client.get(f"/api/v1/support/requests/my?page={MAX_PAGE_NUMBER + 1}")

        assert resp.status_code == 422

    async def test_list_returns_requests(self, client: AsyncClient) -> None:
        with patch(
            f"{SUPPORT_ENDPOINT}.get_user_support_requests",
            new_callable=AsyncMock,
            return_value={
                "requests": [],
                "pagination": {"page": 1, "per_page": 10, "total": 0, "pages": 0},
            },
        ) as fetch:
            resp = await client.get("/api/v1/support/requests/my?page=1&per_page=10")

        assert resp.status_code == 200
        body = resp.json()
        assert body["requests"] == []
        assert body["pagination"]["page"] == 1
        fetch.assert_awaited_once_with(
            user_id="507f1f77bcf86cd799439011", page=1, per_page=10, status_filter=None
        )


class TestSubmitSupportRequest:
    """POST /api/v1/support/requests (+ attachments variant)."""

    async def test_submit_captures_analytics(self, client: AsyncClient) -> None:
        result = SupportRequestSubmissionResponse(
            success=True, message="Submitted", ticket_id="T-123"
        )
        with (
            patch(
                f"{SUPPORT_ENDPOINT}.create_support_request",
                new_callable=AsyncMock,
                return_value=result,
            ),
            patch(f"{SUPPORT_ENDPOINT}.capture_context_event") as mock_capture,
        ):
            resp = await client.post(
                "/api/v1/support/requests",
                json={
                    "type": "support",
                    "title": "Need help",
                    "description": "It broke completely",
                },
            )

        assert resp.status_code == 200
        mock_capture.assert_called_once_with(
            AnalyticsEvents.SUPPORT_TICKET_SUBMITTED,
            {
                "request_type": "support",
                "title_length": len("Need help"),
                "description_length": len("It broke completely"),
                "attachment_count": 0,
            },
        )

    async def test_submit_with_attachments_captures_analytics(self, client: AsyncClient) -> None:
        result = SupportRequestSubmissionResponse(
            success=True, message="Submitted", ticket_id="T-124"
        )
        with (
            patch(
                f"{SUPPORT_ENDPOINT}.create_support_request_with_attachments",
                new_callable=AsyncMock,
                return_value=result,
            ),
            patch(f"{SUPPORT_ENDPOINT}.capture_context_event") as mock_capture,
        ):
            resp = await client.post(
                "/api/v1/support/requests/with-attachments",
                data={"type": "feature", "title": "New idea", "description": "Add a thing"},
                files=[("attachments", ("a.png", b"png", "image/png"))],
            )

        assert resp.status_code == 200
        mock_capture.assert_called_once_with(
            AnalyticsEvents.SUPPORT_TICKET_SUBMITTED,
            {
                "request_type": "feature",
                "title_length": len("New idea"),
                "description_length": len("Add a thing"),
                "attachment_count": 1,
            },
        )
