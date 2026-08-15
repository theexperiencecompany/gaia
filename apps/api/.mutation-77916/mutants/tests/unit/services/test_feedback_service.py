"""Unit tests for per-message chat feedback (feedback_service)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.feedback_models import MessageFeedbackResponse
from app.services.feedback_service import create_message_feedback_service
from app.utils.errors import AppError

USER_ID = "507f1f77bcf86cd799439011"
MESSAGE_ID = "msg-123"
CONVERSATION_ID = "conv-456"

_MOD = "app.services.feedback_service"


@pytest.fixture
def mock_deps():
    """The two domain seams: message-ownership lookup and the Langfuse client.

    ``create_score`` is Langfuse's sync call — the service never awaits it.
    """
    with (
        patch(
            f"{_MOD}.conversation_repository.find_owner_of_message", new_callable=AsyncMock
        ) as m_find,
        patch(f"{_MOD}.trace_id_for_message", return_value="trace-abc") as m_trace,
        patch(f"{_MOD}.get_client") as m_get_client,
    ):
        m_get_client.return_value = MagicMock()
        yield m_find, m_trace, m_get_client


class TestCreateMessageFeedback:
    async def test_positive_feedback_scores_plus_one(self, mock_deps):
        m_find, m_trace, m_get_client = mock_deps
        m_find.return_value = CONVERSATION_ID

        response = await create_message_feedback_service(
            user_id=USER_ID, message_id=MESSAGE_ID, is_positive=True
        )

        assert response.scored is True
        assert response.trace_id == "trace-abc"
        score = m_get_client.return_value.create_score.call_args
        assert score.kwargs["trace_id"] == "trace-abc"
        assert score.kwargs["name"] == "user_feedback"
        assert score.kwargs["value"] == 1
        assert score.kwargs["data_type"] == "NUMERIC"
        assert score.kwargs["metadata"] == {
            "message_id": MESSAGE_ID,
            "conversation_id": CONVERSATION_ID,
            "user_id": USER_ID,
            "source": "chat_ui_thumbs",
        }

    async def test_negative_feedback_scores_minus_one(self, mock_deps):
        m_find, _m_trace, m_get_client = mock_deps
        m_find.return_value = CONVERSATION_ID

        await create_message_feedback_service(
            user_id=USER_ID, message_id=MESSAGE_ID, is_positive=False
        )

        assert m_get_client.return_value.create_score.call_args.kwargs["value"] == -1

    async def test_raises_404_when_message_not_owned(self, mock_deps):
        m_find, m_trace, m_get_client = mock_deps
        m_find.return_value = None

        with pytest.raises(AppError) as exc_info:
            await create_message_feedback_service(
                user_id=USER_ID, message_id=MESSAGE_ID, is_positive=True
            )

        assert exc_info.value.status_code == 404
        assert exc_info.value.message == "Message not found"
        m_get_client.return_value.create_score.assert_not_called()

    async def test_returns_ack_when_langfuse_disabled(self, mock_deps):
        m_find, m_trace, m_get_client = mock_deps
        m_find.return_value = CONVERSATION_ID
        m_trace.return_value = None

        response = await create_message_feedback_service(
            user_id=USER_ID, message_id=MESSAGE_ID, is_positive=True
        )

        assert isinstance(response, MessageFeedbackResponse)
        assert response.scored is False
        assert response.reason == "langfuse_disabled"
        assert response.status == "ok"
        m_get_client.return_value.create_score.assert_not_called()

    async def test_score_failure_propagates(self, mock_deps):
        """The langfuse call is not wrapped — a provider failure must surface."""
        m_find, _m_trace, m_get_client = mock_deps
        m_find.return_value = CONVERSATION_ID
        m_get_client.return_value.create_score = MagicMock(
            side_effect=RuntimeError("langfuse down")
        )

        with pytest.raises(RuntimeError, match="langfuse down"):
            await create_message_feedback_service(
                user_id=USER_ID, message_id=MESSAGE_ID, is_positive=True
            )
