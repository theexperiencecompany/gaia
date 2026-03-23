"""Unit tests for the support API endpoints.

Tests cover:
- POST /api/v1/support/requests
- POST /api/v1/support/requests/with-attachments
- GET  /api/v1/support/requests/my
- GET  /api/v1/support/rate-limit-status
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

SUBMIT_URL = "/api/v1/support/requests"
SUBMIT_WITH_ATTACHMENTS_URL = "/api/v1/support/requests/with-attachments"
MY_REQUESTS_URL = "/api/v1/support/requests/my"
RATE_LIMIT_STATUS_URL = "/api/v1/support/rate-limit-status"

# Patch targets
_CREATE_SUPPORT_REQUEST = "app.api.v1.endpoints.support.create_support_request"
_CREATE_WITH_ATTACHMENTS = (
    "app.api.v1.endpoints.support.create_support_request_with_attachments"
)
_GET_USER_REQUESTS = "app.api.v1.endpoints.support.get_user_support_requests"


def _make_submission_response(**overrides) -> MagicMock:
    base = {
        "success": True,
        "message": "Support request submitted successfully",
        "ticket_id": "GAIA-12345",
        "support_request": None,
    }
    base.update(overrides)
    return MagicMock(**base)


# ---------------------------------------------------------------------------
# POST /support/requests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSubmitSupportRequest:
    """Tests for the submit support request endpoint."""

    async def test_submit_support_request_returns_200(self, client: AsyncClient):
        mock_result = _make_submission_response()
        with patch(
            _CREATE_SUPPORT_REQUEST,
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            response = await client.post(
                SUBMIT_URL,
                json={
                    "type": "support",
                    "title": "Help needed",
                    "description": "I have an issue with the application that needs fixing.",
                },
            )

        assert response.status_code == 200

    async def test_submit_support_request_feature_type(self, client: AsyncClient):
        mock_result = _make_submission_response()
        with patch(
            _CREATE_SUPPORT_REQUEST,
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            response = await client.post(
                SUBMIT_URL,
                json={
                    "type": "feature",
                    "title": "Feature request",
                    "description": "I would like a new feature added to the platform.",
                },
            )

        assert response.status_code == 200

    async def test_submit_support_request_invalid_type_returns_422(
        self, client: AsyncClient
    ):
        response = await client.post(
            SUBMIT_URL,
            json={
                "type": "invalid_type",
                "title": "Test",
                "description": "Some description that is long enough.",
            },
        )
        assert response.status_code == 422

    async def test_submit_support_request_missing_title_returns_422(
        self, client: AsyncClient
    ):
        response = await client.post(
            SUBMIT_URL,
            json={
                "type": "support",
                "description": "Some description that is long enough.",
            },
        )
        assert response.status_code == 422

    async def test_submit_support_request_missing_description_returns_422(
        self, client: AsyncClient
    ):
        response = await client.post(
            SUBMIT_URL,
            json={"type": "support", "title": "Help needed"},
        )
        assert response.status_code == 422

    async def test_submit_support_request_description_too_short_returns_422(
        self, client: AsyncClient
    ):
        response = await client.post(
            SUBMIT_URL,
            json={
                "type": "support",
                "title": "Help",
                "description": "Short",
            },
        )
        assert response.status_code == 422

    async def test_submit_support_request_title_too_long_returns_422(
        self, client: AsyncClient
    ):
        response = await client.post(
            SUBMIT_URL,
            json={
                "type": "support",
                "title": "x" * 201,
                "description": "Valid description that is long enough.",
            },
        )
        assert response.status_code == 422

    async def test_submit_support_request_service_passes_user_info(
        self, client: AsyncClient
    ):
        mock_result = _make_submission_response()
        with patch(
            _CREATE_SUPPORT_REQUEST,
            new_callable=AsyncMock,
            return_value=mock_result,
        ) as mock_create:
            await client.post(
                SUBMIT_URL,
                json={
                    "type": "support",
                    "title": "Help needed",
                    "description": "I have an issue that needs to be looked at.",
                },
            )

        mock_create.assert_awaited_once()
        call_kwargs = mock_create.call_args.kwargs
        assert call_kwargs["user_id"] == "507f1f77bcf86cd799439011"
        assert call_kwargs["user_email"] == "test@example.com"

    async def test_submit_support_request_service_error_returns_500(
        self, client: AsyncClient
    ):
        with patch(
            _CREATE_SUPPORT_REQUEST,
            new_callable=AsyncMock,
            side_effect=RuntimeError("Email service down"),
        ):
            response = await client.post(
                SUBMIT_URL,
                json={
                    "type": "support",
                    "title": "Help needed",
                    "description": "I have an issue that needs to be looked at.",
                },
            )

        assert response.status_code == 500


# ---------------------------------------------------------------------------
# POST /support/requests/with-attachments (multipart form)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSubmitSupportRequestWithAttachments:
    """Tests for the submit support request with attachments endpoint."""

    async def test_submit_with_attachments_returns_200(self, client: AsyncClient):
        mock_result = _make_submission_response()
        with patch(
            _CREATE_WITH_ATTACHMENTS,
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            response = await client.post(
                SUBMIT_WITH_ATTACHMENTS_URL,
                data={
                    "type": "support",
                    "title": "Bug report",
                    "description": "Something is broken in the application.",
                },
            )

        assert response.status_code == 200

    async def test_submit_with_attachments_invalid_type_returns_400(
        self, client: AsyncClient
    ):
        response = await client.post(
            SUBMIT_WITH_ATTACHMENTS_URL,
            data={
                "type": "invalid",
                "title": "Bug report",
                "description": "Something is broken in the application.",
            },
        )
        assert response.status_code == 400

    async def test_submit_with_attachments_missing_title_returns_422(
        self, client: AsyncClient
    ):
        response = await client.post(
            SUBMIT_WITH_ATTACHMENTS_URL,
            data={
                "type": "support",
                "description": "Something is broken in the application.",
            },
        )
        assert response.status_code == 422

    async def test_submit_with_attachments_service_error_returns_500(
        self, client: AsyncClient
    ):
        with patch(
            _CREATE_WITH_ATTACHMENTS,
            new_callable=AsyncMock,
            side_effect=RuntimeError("Storage error"),
        ):
            response = await client.post(
                SUBMIT_WITH_ATTACHMENTS_URL,
                data={
                    "type": "support",
                    "title": "Bug report",
                    "description": "Something is broken in the application.",
                },
            )

        assert response.status_code == 500


# ---------------------------------------------------------------------------
# GET /support/requests/my
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetMySupportRequests:
    """Tests for the get user support requests endpoint."""

    async def test_get_my_requests_returns_200(self, client: AsyncClient):
        mock_result = {
            "requests": [],
            "total": 0,
            "page": 1,
            "per_page": 10,
        }
        with patch(
            _GET_USER_REQUESTS,
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            response = await client.get(MY_REQUESTS_URL)

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0

    async def test_get_my_requests_with_pagination(self, client: AsyncClient):
        mock_result = {
            "requests": [{"ticket_id": "GAIA-001"}],
            "total": 1,
            "page": 2,
            "per_page": 5,
        }
        with patch(
            _GET_USER_REQUESTS,
            new_callable=AsyncMock,
            return_value=mock_result,
        ) as mock_get:
            response = await client.get(
                MY_REQUESTS_URL, params={"page": 2, "per_page": 5}
            )

        assert response.status_code == 200
        mock_get.assert_awaited_once_with(
            user_id="507f1f77bcf86cd799439011",
            page=2,
            per_page=5,
            status_filter=None,
        )

    async def test_get_my_requests_with_status_filter(self, client: AsyncClient):
        with patch(
            _GET_USER_REQUESTS,
            new_callable=AsyncMock,
            return_value={"requests": [], "total": 0, "page": 1, "per_page": 10},
        ) as mock_get:
            await client.get(MY_REQUESTS_URL, params={"status": "open"})

        call_kwargs = mock_get.call_args.kwargs
        assert call_kwargs["status_filter"] == "open"

    async def test_get_my_requests_invalid_page_returns_422(self, client: AsyncClient):
        response = await client.get(MY_REQUESTS_URL, params={"page": 0})
        assert response.status_code == 422

    async def test_get_my_requests_per_page_exceeds_max_returns_422(
        self, client: AsyncClient
    ):
        response = await client.get(MY_REQUESTS_URL, params={"per_page": 51})
        assert response.status_code == 422

    async def test_get_my_requests_service_error_returns_500(self, client: AsyncClient):
        with patch(
            _GET_USER_REQUESTS,
            new_callable=AsyncMock,
            side_effect=RuntimeError("DB error"),
        ):
            response = await client.get(MY_REQUESTS_URL)

        assert response.status_code == 500


# ---------------------------------------------------------------------------
# GET /support/rate-limit-status
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetRateLimitStatus:
    """Tests for the rate limit status endpoint."""

    async def test_rate_limit_status_returns_200(self, client: AsyncClient):
        response = await client.get(RATE_LIMIT_STATUS_URL)

        assert response.status_code == 200
        data = response.json()
        assert "limits" in data
        assert data["limits"]["hourly"]["limit"] == 5
        assert data["limits"]["daily"]["limit"] == 10

    async def test_rate_limit_status_contains_note(self, client: AsyncClient):
        response = await client.get(RATE_LIMIT_STATUS_URL)

        data = response.json()
        assert "note" in data
