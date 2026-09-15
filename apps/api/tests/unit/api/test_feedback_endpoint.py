"""Unit tests for the per-message feedback endpoint (POST /api/v1/messages/{id}/feedback)."""

from unittest.mock import AsyncMock, patch

from httpx import AsyncClient

from app.models.feedback_models import MessageFeedbackResponse
from app.services.analytics_service import AnalyticsEvents
from tests.conftest import FAKE_USER

_MOD = "app.api.v1.endpoints.feedback"


class TestSubmitMessageFeedback:
    async def test_scored_feedback_is_recorded_for_the_caller_and_captured(
        self, client: AsyncClient
    ) -> None:
        result = MessageFeedbackResponse(scored=True, trace_id="trace-1")
        with (
            patch(
                f"{_MOD}.create_message_feedback_service",
                new_callable=AsyncMock,
                return_value=result,
            ) as mock_service,
            patch(f"{_MOD}.capture_context_event") as mock_capture,
        ):
            resp = await client.post("/api/v1/messages/msg-1/feedback", json={"is_positive": False})

        assert resp.status_code == 202
        assert resp.json()["trace_id"] == "trace-1"
        mock_service.assert_awaited_once_with(
            user_id=FAKE_USER.user_id, message_id="msg-1", is_positive=False
        )
        mock_capture.assert_called_once_with(
            AnalyticsEvents.FEEDBACK_MESSAGE_SUBMITTED, {"is_positive": False}
        )

    async def test_unscored_feedback_is_acknowledged_without_an_event(
        self, client: AsyncClient
    ) -> None:
        result = MessageFeedbackResponse(scored=False, reason="langfuse_disabled")
        with (
            patch(
                f"{_MOD}.create_message_feedback_service",
                new_callable=AsyncMock,
                return_value=result,
            ),
            patch(f"{_MOD}.capture_context_event") as mock_capture,
        ):
            resp = await client.post("/api/v1/messages/msg-1/feedback", json={"is_positive": True})

        assert resp.status_code == 202
        assert resp.json()["scored"] is False
        mock_capture.assert_not_called()
