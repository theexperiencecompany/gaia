"""Integration tests for chat API endpoints.

Tests POST /api/v1/chat-stream and POST /api/v1/cancel-stream/{stream_id}
with mocked service layer to verify routing, auth enforcement, response
structure, and SSE format through the full FastAPI request lifecycle.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_BODY = {
    "message": "Hello, world!",
    "messages": [],
    "conversation_id": "conv-test-123",
}


# ---------------------------------------------------------------------------
# Test classes
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestChatStreamEndpoint:
    """Tests for POST /api/v1/chat-stream."""

    @patch(
        "app.api.v1.endpoints.chat.stream_manager.start_stream",
        new_callable=AsyncMock,
    )
    @patch(
        "app.api.v1.endpoints.chat.run_chat_stream_background",
        new_callable=AsyncMock,
    )
    @patch(
        "app.api.v1.endpoints.chat.asyncio.create_task",
    )
    @patch(
        "app.api.v1.endpoints.chat.redis_cache",
    )
    @patch(
        "app.decorators.rate_limiting.payment_service.get_user_subscription_status",
        new_callable=AsyncMock,
    )
    async def test_chat_stream_returns_200(
        self,
        mock_subscription,
        mock_redis_cache,
        mock_create_task,
        mock_bg,
        mock_start_stream,
        test_client,
    ):
        """POST /api/v1/chat-stream should return 200 with SSE media type."""
        from app.models.payment_models import PlanType

        subscription = MagicMock()
        subscription.plan_type = PlanType.FREE
        mock_subscription.return_value = subscription

        # Redis is "available" so the stream generator runs
        mock_redis_cache.redis = MagicMock()

        # create_task must return a real asyncio.Task-like mock
        mock_task = MagicMock()
        mock_task.add_done_callback = MagicMock()
        mock_create_task.return_value = mock_task

        response = await test_client.post(
            "/api/v1/chat-stream",
            json=_VALID_BODY,
        )

        assert response.status_code == 200

    @patch(
        "app.api.v1.endpoints.chat.stream_manager.start_stream",
        new_callable=AsyncMock,
    )
    @patch(
        "app.api.v1.endpoints.chat.run_chat_stream_background",
        new_callable=AsyncMock,
    )
    @patch(
        "app.api.v1.endpoints.chat.asyncio.create_task",
    )
    @patch(
        "app.api.v1.endpoints.chat.redis_cache",
    )
    @patch(
        "app.decorators.rate_limiting.payment_service.get_user_subscription_status",
        new_callable=AsyncMock,
    )
    async def test_chat_stream_sse_content_type(
        self,
        mock_subscription,
        mock_redis_cache,
        mock_create_task,
        mock_bg,
        mock_start_stream,
        test_client,
    ):
        """POST /api/v1/chat-stream should respond with text/event-stream content type."""
        from app.models.payment_models import PlanType

        subscription = MagicMock()
        subscription.plan_type = PlanType.FREE
        mock_subscription.return_value = subscription

        mock_redis_cache.redis = MagicMock()

        mock_task = MagicMock()
        mock_task.add_done_callback = MagicMock()
        mock_create_task.return_value = mock_task

        response = await test_client.post(
            "/api/v1/chat-stream",
            json=_VALID_BODY,
        )

        assert response.status_code == 200
        content_type = response.headers.get("content-type", "")
        assert "text/event-stream" in content_type

    @patch(
        "app.api.v1.endpoints.chat.stream_manager.start_stream",
        new_callable=AsyncMock,
    )
    @patch(
        "app.api.v1.endpoints.chat.run_chat_stream_background",
        new_callable=AsyncMock,
    )
    @patch(
        "app.api.v1.endpoints.chat.asyncio.create_task",
    )
    @patch(
        "app.api.v1.endpoints.chat.redis_cache",
    )
    @patch(
        "app.decorators.rate_limiting.payment_service.get_user_subscription_status",
        new_callable=AsyncMock,
    )
    async def test_chat_stream_response_headers(
        self,
        mock_subscription,
        mock_redis_cache,
        mock_create_task,
        mock_bg,
        mock_start_stream,
        test_client,
    ):
        """POST /api/v1/chat-stream should include required SSE and stream headers."""
        from app.models.payment_models import PlanType

        subscription = MagicMock()
        subscription.plan_type = PlanType.FREE
        mock_subscription.return_value = subscription

        mock_redis_cache.redis = MagicMock()

        mock_task = MagicMock()
        mock_task.add_done_callback = MagicMock()
        mock_create_task.return_value = mock_task

        response = await test_client.post(
            "/api/v1/chat-stream",
            json=_VALID_BODY,
        )

        assert response.status_code == 200
        # The endpoint sets X-Stream-Id so the client can call cancel-stream
        assert "x-stream-id" in response.headers
        assert response.headers.get("cache-control") == "no-cache"

    @patch(
        "app.api.v1.endpoints.chat.stream_manager.start_stream",
        new_callable=AsyncMock,
    )
    @patch(
        "app.api.v1.endpoints.chat.run_chat_stream_background",
        new_callable=AsyncMock,
    )
    @patch(
        "app.api.v1.endpoints.chat.asyncio.create_task",
    )
    @patch(
        "app.api.v1.endpoints.chat.redis_cache",
    )
    @patch(
        "app.decorators.rate_limiting.payment_service.get_user_subscription_status",
        new_callable=AsyncMock,
    )
    async def test_chat_stream_creates_background_task(
        self,
        mock_subscription,
        mock_redis_cache,
        mock_create_task,
        mock_bg,
        mock_start_stream,
        test_client,
    ):
        """POST /api/v1/chat-stream must kick off a background asyncio Task."""
        from app.models.payment_models import PlanType

        subscription = MagicMock()
        subscription.plan_type = PlanType.FREE
        mock_subscription.return_value = subscription

        mock_redis_cache.redis = MagicMock()

        mock_task = MagicMock()
        mock_task.add_done_callback = MagicMock()
        mock_create_task.return_value = mock_task

        response = await test_client.post(
            "/api/v1/chat-stream",
            json=_VALID_BODY,
        )

        assert response.status_code == 200
        # asyncio.create_task must have been called once to launch background work
        mock_create_task.assert_called_once()

    @patch(
        "app.api.v1.endpoints.chat.stream_manager.start_stream",
        new_callable=AsyncMock,
    )
    @patch(
        "app.api.v1.endpoints.chat.run_chat_stream_background",
        new_callable=AsyncMock,
    )
    @patch(
        "app.api.v1.endpoints.chat.asyncio.create_task",
    )
    @patch(
        "app.api.v1.endpoints.chat.redis_cache",
    )
    @patch(
        "app.decorators.rate_limiting.payment_service.get_user_subscription_status",
        new_callable=AsyncMock,
    )
    async def test_chat_stream_initialises_stream_in_redis(
        self,
        mock_subscription,
        mock_redis_cache,
        mock_create_task,
        mock_bg,
        mock_start_stream,
        test_client,
    ):
        """start_stream must be called with matching conversation and user IDs."""
        from app.models.payment_models import PlanType

        subscription = MagicMock()
        subscription.plan_type = PlanType.FREE
        mock_subscription.return_value = subscription

        mock_redis_cache.redis = MagicMock()

        mock_task = MagicMock()
        mock_task.add_done_callback = MagicMock()
        mock_create_task.return_value = mock_task

        await test_client.post("/api/v1/chat-stream", json=_VALID_BODY)

        mock_start_stream.assert_called_once()
        call_kwargs = mock_start_stream.call_args.kwargs
        assert "stream_id" in call_kwargs
        assert call_kwargs["conversation_id"] == "conv-test-123"
        # user_id comes from the injected test_user fixture (integration-test-user-1)
        assert call_kwargs["user_id"] == "integration-test-user-1"

    @patch(
        "app.api.v1.endpoints.chat.stream_manager.start_stream",
        new_callable=AsyncMock,
    )
    @patch(
        "app.api.v1.endpoints.chat.run_chat_stream_background",
        new_callable=AsyncMock,
    )
    @patch(
        "app.api.v1.endpoints.chat.asyncio.create_task",
    )
    @patch(
        "app.api.v1.endpoints.chat.redis_cache",
    )
    @patch(
        "app.decorators.rate_limiting.payment_service.get_user_subscription_status",
        new_callable=AsyncMock,
    )
    async def test_chat_stream_auto_generates_conversation_id(
        self,
        mock_subscription,
        mock_redis_cache,
        mock_create_task,
        mock_bg,
        mock_start_stream,
        test_client,
    ):
        """When conversation_id is omitted the endpoint generates a fresh UUID."""
        from app.models.payment_models import PlanType

        subscription = MagicMock()
        subscription.plan_type = PlanType.FREE
        mock_subscription.return_value = subscription

        mock_redis_cache.redis = MagicMock()

        mock_task = MagicMock()
        mock_task.add_done_callback = MagicMock()
        mock_create_task.return_value = mock_task

        body_no_conv = {"message": "Hi!", "messages": []}
        await test_client.post("/api/v1/chat-stream", json=body_no_conv)

        mock_start_stream.assert_called_once()
        call_kwargs = mock_start_stream.call_args.kwargs
        # conversation_id should be a non-empty string even without one supplied
        assert call_kwargs["conversation_id"]

    @patch(
        "app.api.v1.endpoints.chat.stream_manager.start_stream",
        new_callable=AsyncMock,
    )
    @patch(
        "app.api.v1.endpoints.chat.redis_cache",
    )
    @patch(
        "app.decorators.rate_limiting.payment_service.get_user_subscription_status",
        new_callable=AsyncMock,
    )
    async def test_chat_stream_sse_error_when_redis_unavailable(
        self,
        mock_subscription,
        mock_redis_cache,
        mock_start_stream,
        test_client,
    ):
        """When Redis is unavailable the SSE body should contain [STREAM_ERROR]."""
        import asyncio
        from app.models.payment_models import PlanType

        subscription = MagicMock()
        subscription.plan_type = PlanType.FREE
        mock_subscription.return_value = subscription

        # Simulate Redis being unavailable
        mock_redis_cache.redis = None

        with patch(
            "app.api.v1.endpoints.chat.asyncio.create_task",
        ) as mock_create_task:
            mock_task = MagicMock()
            mock_task.add_done_callback = MagicMock()
            mock_create_task.return_value = mock_task

            response = await test_client.post(
                "/api/v1/chat-stream",
                json=_VALID_BODY,
            )

        assert response.status_code == 200
        assert "[STREAM_ERROR]" in response.text

    async def test_chat_stream_requires_auth(self, unauthenticated_client):
        """POST /api/v1/chat-stream without auth must return 401."""
        response = await unauthenticated_client.post(
            "/api/v1/chat-stream",
            json=_VALID_BODY,
        )
        assert response.status_code == 401

    async def test_chat_stream_rejects_invalid_body(self, test_client):
        """POST /api/v1/chat-stream with a missing required field returns 422."""
        # 'message' field is required; omitting it should trigger validation error
        response = await test_client.post(
            "/api/v1/chat-stream",
            json={"messages": []},  # no 'message' key
        )
        assert response.status_code == 422


@pytest.mark.integration
class TestCancelStreamEndpoint:
    """Tests for POST /api/v1/cancel-stream/{stream_id}."""

    @patch(
        "app.api.v1.endpoints.chat.stream_manager.get_progress",
        new_callable=AsyncMock,
    )
    @patch(
        "app.api.v1.endpoints.chat.stream_manager.cancel_stream",
        new_callable=AsyncMock,
    )
    async def test_cancel_stream_returns_success(
        self,
        mock_cancel,
        mock_get_progress,
        test_client,
        test_user,
    ):
        """POST /api/v1/cancel-stream/{id} should return 200 with success=True."""
        mock_get_progress.return_value = {
            "user_id": test_user["user_id"],
            "conversation_id": "conv-abc",
        }
        mock_cancel.return_value = True

        response = await test_client.post("/api/v1/cancel-stream/stream-xyz")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["stream_id"] == "stream-xyz"

    @patch(
        "app.api.v1.endpoints.chat.stream_manager.get_progress",
        new_callable=AsyncMock,
    )
    async def test_cancel_stream_not_found(
        self,
        mock_get_progress,
        test_client,
    ):
        """POST /api/v1/cancel-stream/{id} for unknown stream returns success=False."""
        mock_get_progress.return_value = None

        response = await test_client.post("/api/v1/cancel-stream/nonexistent-stream")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "error" in data

    @patch(
        "app.api.v1.endpoints.chat.stream_manager.get_progress",
        new_callable=AsyncMock,
    )
    async def test_cancel_stream_forbidden_for_other_user(
        self,
        mock_get_progress,
        test_client,
    ):
        """A user must not be able to cancel another user's stream (403)."""
        # Progress records a different user_id than the authenticated test user
        mock_get_progress.return_value = {
            "user_id": "different-user-id",
            "conversation_id": "conv-other",
        }

        response = await test_client.post("/api/v1/cancel-stream/stream-owned-by-other")

        assert response.status_code == 403

    async def test_cancel_stream_requires_auth(self, unauthenticated_client):
        """POST /api/v1/cancel-stream/{id} without auth must return 401."""
        response = await unauthenticated_client.post(
            "/api/v1/cancel-stream/some-stream-id"
        )
        assert response.status_code == 401
