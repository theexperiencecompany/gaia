"""Endpoint tests for /api/v1/support.

Covers the MAX_PAGE_NUMBER page bound on the my-requests list and the
happy path with the service faked.
"""

from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.v1.dependencies.oauth_dependencies import (
    get_current_user,
    get_current_user as _get_current_user_dep,
)
from app.api.v1.endpoints.support import router
from app.constants.general import MAX_PAGE_NUMBER
from app.models.support_models import (
    SupportRequestSubmissionResponse,
    SupportRequestType,
)
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

    async def test_submit_with_attachments_invalid_type_returns_400_exact_detail(
        self, client: AsyncClient
    ) -> None:
        """An unrecognized multipart type is rejected with every valid option named."""
        resp = await client.post(
            "/api/v1/support/requests/with-attachments",
            data={"type": "bogus", "title": "T", "description": "Something broke badly"},
        )

        assert resp.status_code == 400
        assert resp.json()["detail"] == "Invalid request type. Must be one of: support, feature"

    async def test_submit_with_attachments_passes_exact_kwargs_to_service(
        self, client: AsyncClient
    ) -> None:
        """The service receives the validated type plus the caller's identity."""
        result = SupportRequestSubmissionResponse(
            success=True, message="Submitted", ticket_id="T-125"
        )
        with (
            patch(
                f"{SUPPORT_ENDPOINT}.create_support_request_with_attachments",
                new_callable=AsyncMock,
                return_value=result,
            ) as create,
            patch(f"{SUPPORT_ENDPOINT}.log"),
        ):
            resp = await client.post(
                "/api/v1/support/requests/with-attachments",
                data={
                    "type": "feature",
                    "title": "New idea",
                    "description": "Add a thing",
                },
                files=[("attachments", ("a.png", b"png", "image/png"))],
            )

        assert resp.status_code == 200
        create.assert_awaited_once()
        kwargs = create.await_args.kwargs
        assert kwargs["request_data"].type is SupportRequestType.FEATURE
        assert kwargs["request_data"].title == "New idea"
        assert kwargs["request_data"].description == "Add a thing"
        assert kwargs["user_id"] == "507f1f77bcf86cd799439011"
        assert isinstance(kwargs["attachments"], list) and len(kwargs["attachments"]) == 1

    async def test_submit_with_attachments_service_error_wraps_as_500_exact_detail(
        self, client: AsyncClient
    ) -> None:
        """A non-HTTP failure from the service becomes a 500 with the cause appended."""
        with (
            patch(
                f"{SUPPORT_ENDPOINT}.create_support_request_with_attachments",
                new_callable=AsyncMock,
                side_effect=RuntimeError("cloudinary down"),
            ),
            patch(f"{SUPPORT_ENDPOINT}.log"),
        ):
            resp = await client.post(
                "/api/v1/support/requests/with-attachments",
                data={"type": "support", "title": "T", "description": "Something broke badly"},
            )

        assert resp.status_code == 500
        assert resp.json()["detail"] == "Failed to submit support request: cloudinary down"

    async def test_attachments_endpoint_requires_user_id_and_email(self, test_app: FastAPI) -> None:
        """Missing user_id OR email each yield 401 with the exact detail string."""
        for current_user in ({}, {"user_id": "u1"}, {"email": "a@b.c"}):
            original = test_app.dependency_overrides.get(get_current_user)
            test_app.dependency_overrides[get_current_user] = lambda cu=current_user: cu
            try:
                transport = ASGITransport(app=test_app, raise_app_exceptions=False)
                async with AsyncClient(
                    transport=transport, base_url="http://test"
                ) as ac:  # NOSONAR
                    resp = await ac.post(
                        "/api/v1/support/requests/with-attachments",
                        data={"type": "support", "title": "T", "description": "Something broke"},
                    )
            finally:
                if original is None:
                    test_app.dependency_overrides.pop(get_current_user, None)
                else:
                    test_app.dependency_overrides[get_current_user] = original

            assert resp.status_code == 401
            assert resp.json()["detail"] == "User authentication required"


class TestSubmitSupportRequestLogPins:
    async def test_success_log_calls_are_exact(self, client: AsyncClient) -> None:
        result = SupportRequestSubmissionResponse(
            success=True, message="Submitted", ticket_id="T-126"
        )
        with (
            patch(
                f"{SUPPORT_ENDPOINT}.create_support_request_with_attachments",
                new_callable=AsyncMock,
                return_value=result,
            ),
            patch(f"{SUPPORT_ENDPOINT}.log") as mock_log,
        ):
            resp = await client.post(
                "/api/v1/support/requests/with-attachments",
                data={"type": "support", "title": "T", "description": "Something broke badly"},
            )

        assert resp.status_code == 200
        mock_log.set.assert_any_call(
            operation="submit_support_request_with_attachments", category="support"
        )
        mock_log.set.assert_any_call(ticket_id="T-126")
        mock_log.set.assert_any_call(outcome="success")

    async def test_missing_email_returns_exact_401_detail(self, test_app: FastAPI) -> None:
        """A user without an email address is rejected before anything runs."""
        from fastapi.testclient import TestClient

        app = FastAPI()
        app.include_router(router, prefix="/api/v1")

        app.dependency_overrides[_get_current_user_dep] = lambda: {"user_id": "u1"}
        try:
            with patch(f"{SUPPORT_ENDPOINT}.log"):
                with TestClient(app, raise_server_exceptions=False) as c:
                    resp = c.post(
                        "/api/v1/support/requests/with-attachments",
                        data={"type": "support", "title": "T", "description": "Enough text"},
                    )
        finally:
            app.dependency_overrides.clear()

        assert resp.status_code == 401
        assert resp.json()["detail"] == "User authentication required"
        _ = test_app
