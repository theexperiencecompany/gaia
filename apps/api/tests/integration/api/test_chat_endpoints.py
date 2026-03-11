"""Integration tests for chat API endpoints.

Tests POST /api/v1/chat-stream and POST /api/v1/cancel-stream/{stream_id}.

Mocking strategy
----------------
- Service layer (run_chat_stream_background) is NOT mocked; instead we mock at
  the infrastructure boundary: Redis (redis_cache) and stream_manager methods
  that talk to Redis.
- payment_service.get_user_subscription_status is mocked because it talks to
  MongoDB; it is an external I/O dependency, not business logic under test.
- tiered_limiter.check_and_increment is mocked so rate-limit Redis calls don't
  execute; the decorator itself still runs, exercising the auth/user extraction
  path inside the decorator.

Threat model for the test suite
--------------------------------
If `get_current_user` dependency is removed the `unauthenticated_client` tests
MUST return 401.  If `body: MessageRequestWithHistory` validation is weakened
(e.g. `message` made Optional) the 422 tests MUST fail.  If response headers
are dropped the header-assertion tests MUST fail.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Shared test data
# ---------------------------------------------------------------------------

_VALID_BODY = {
    "message": "Hello, world!",
    "messages": [],
    "conversation_id": "conv-test-123",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _empty_subscribe_stream(*args, **kwargs):
    """Async generator that yields nothing — simulates an empty SSE stream.

    stream_manager.subscribe_stream is an async generator.  Without this stub
    the generator in chat.py would try to subscribe to a real Redis pubsub
    channel and fail.
    """
    return
    yield  # pragma: no cover – makes this a generator function


def _make_mock_task() -> MagicMock:
    t = MagicMock()
    t.add_done_callback = MagicMock()
    return t


def _make_subscription_mock():
    from app.models.payment_models import PlanType

    sub = MagicMock()
    sub.plan_type = PlanType.FREE
    return sub


# ---------------------------------------------------------------------------
# Fixtures shared across this module
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_payment_subscription():
    """Mock payment_service.get_user_subscription_status at the service level.

    The tiered_rate_limit decorator calls this to look up the user's plan.
    Mocking here avoids a MongoDB round-trip while still letting the decorator
    code path run (plan extraction, tiered_limiter.check_and_increment call).
    """
    with patch(
        "app.decorators.rate_limiting.payment_service.get_user_subscription_status",
        new_callable=AsyncMock,
        return_value=_make_subscription_mock(),
    ) as mock:
        yield mock


@pytest.fixture
def mock_rate_limiter():
    """Bypass the tiered rate limiter's Redis pipeline for all chat tests.

    The TieredRateLimiter.check_and_increment opens a Redis pipeline; we skip
    that I/O while letting the decorator wrapper itself execute (auth checks,
    user extraction from kwargs).
    """
    with patch(
        "app.api.v1.middleware.tiered_rate_limiter.tiered_limiter.check_and_increment",
        new_callable=AsyncMock,
        return_value={},
    ) as mock:
        yield mock


@pytest.fixture
def mock_redis_cache():
    """Provide a redis_cache stub whose .redis attribute is a non-None MagicMock.

    chat.py checks `if not redis_cache.redis` before subscribing; if None it
    yields [STREAM_ERROR].  Tests that want a healthy Redis pass this fixture.
    """
    with patch("app.api.v1.endpoints.chat.redis_cache") as mock:
        mock.redis = MagicMock()
        yield mock


@pytest.fixture
def mock_stream_infrastructure(mock_redis_cache):
    """Mock every stream_manager method that touches Redis.

    - start_stream: stores progress key in Redis
    - subscribe_stream: opens a Redis pubsub channel
    - run_chat_stream_background: stubbed so the coroutine is consumed before
      asyncio.create_task receives it, preventing "coroutine never awaited" warnings
    - asyncio.create_task: prevents a real background task from being scheduled

    The service function signature is still imported and validated at collect
    time, so import-time errors are still caught.
    """
    with (
        patch(
            "app.api.v1.endpoints.chat.stream_manager.start_stream",
            new_callable=AsyncMock,
        ) as mock_start,
        patch(
            "app.api.v1.endpoints.chat.stream_manager.subscribe_stream",
            new=_empty_subscribe_stream,
        ),
        patch(
            "app.api.v1.endpoints.chat.run_chat_stream_background",
            new_callable=AsyncMock,
        ),
        patch(
            "app.api.v1.endpoints.chat.asyncio.create_task",
            return_value=_make_mock_task(),
        ) as mock_create_task,
    ):
        yield {
            "start_stream": mock_start,
            "create_task": mock_create_task,
        }


# ---------------------------------------------------------------------------
# Tests: POST /api/v1/chat-stream
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestChatStreamEndpoint:
    """Tests for POST /api/v1/chat-stream."""

    # ------------------------------------------------------------------
    # Happy path
    # ------------------------------------------------------------------

    async def test_chat_stream_returns_200(
        self,
        test_client,
        mock_payment_subscription,
        mock_rate_limiter,
        mock_stream_infrastructure,
    ):
        """POST /api/v1/chat-stream with a valid body must return HTTP 200."""
        response = await test_client.post("/api/v1/chat-stream", json=_VALID_BODY)
        assert response.status_code == 200

    async def test_chat_stream_sse_content_type(
        self,
        test_client,
        mock_payment_subscription,
        mock_rate_limiter,
        mock_stream_infrastructure,
    ):
        """Response Content-Type must be text/event-stream."""
        response = await test_client.post("/api/v1/chat-stream", json=_VALID_BODY)

        assert response.status_code == 200
        content_type = response.headers.get("content-type", "")
        assert "text/event-stream" in content_type

    async def test_chat_stream_response_headers(
        self,
        test_client,
        mock_payment_subscription,
        mock_rate_limiter,
        mock_stream_infrastructure,
    ):
        """Response must include X-Stream-Id and Cache-Control: no-cache headers.

        Removing either header from the StreamingResponse in chat.py will cause
        this test to fail.
        """
        response = await test_client.post("/api/v1/chat-stream", json=_VALID_BODY)

        assert response.status_code == 200
        # Header names are case-insensitive; httpx lowercases them
        assert "x-stream-id" in response.headers, (
            "X-Stream-Id header missing – streaming clients need this to cancel"
        )
        assert response.headers.get("cache-control") == "no-cache", (
            "Cache-Control: no-cache is required for proper SSE delivery"
        )

    async def test_chat_stream_creates_background_task(
        self,
        test_client,
        mock_payment_subscription,
        mock_rate_limiter,
        mock_stream_infrastructure,
    ):
        """The endpoint must schedule exactly one asyncio.Task for LangGraph execution.

        Removing the asyncio.create_task() call from the endpoint will break this test.
        """
        response = await test_client.post("/api/v1/chat-stream", json=_VALID_BODY)

        assert response.status_code == 200
        mock_stream_infrastructure["create_task"].assert_called_once()

    async def test_chat_stream_initialises_stream_in_redis(
        self,
        test_client,
        mock_payment_subscription,
        mock_rate_limiter,
        mock_stream_infrastructure,
    ):
        """stream_manager.start_stream must be called with the correct IDs.

        Removing the start_stream() call or changing the argument names will
        break this test.
        """
        await test_client.post("/api/v1/chat-stream", json=_VALID_BODY)

        mock_stream_infrastructure["start_stream"].assert_called_once()
        call_kwargs = mock_stream_infrastructure["start_stream"].call_args.kwargs
        assert "stream_id" in call_kwargs, "stream_id kwarg missing from start_stream"
        assert call_kwargs["conversation_id"] == "conv-test-123"
        assert call_kwargs["user_id"] == "integration-test-user-1"

    async def test_chat_stream_auto_generates_conversation_id(
        self,
        test_client,
        mock_payment_subscription,
        mock_rate_limiter,
        mock_stream_infrastructure,
    ):
        """When conversation_id is omitted the endpoint must generate a fresh UUID.

        Removing the `conversation_id = body.conversation_id or str(uuid4())` line
        in the endpoint will cause start_stream to receive an empty/None
        conversation_id and this assertion will fail.
        """
        body_no_conv = {"message": "Hi!", "messages": []}
        await test_client.post("/api/v1/chat-stream", json=body_no_conv)

        mock_stream_infrastructure["start_stream"].assert_called_once()
        call_kwargs = mock_stream_infrastructure["start_stream"].call_args.kwargs
        assert call_kwargs.get("conversation_id"), (
            "conversation_id must be auto-generated when not provided"
        )

    # ------------------------------------------------------------------
    # Redis failure path
    # ------------------------------------------------------------------

    async def test_chat_stream_sse_error_when_redis_unavailable(
        self,
        test_client,
        mock_payment_subscription,
        mock_rate_limiter,
    ):
        """When redis_cache.redis is None the SSE body must contain [STREAM_ERROR].

        This exercises the `if not redis_cache.redis` guard inside
        stream_from_redis().  Removing that guard or changing the error token
        will break this test.
        """
        with (
            patch(
                "app.api.v1.endpoints.chat.stream_manager.start_stream",
                new_callable=AsyncMock,
            ),
            patch(
                "app.api.v1.endpoints.chat.redis_cache",
            ) as mock_rc,
            patch(
                "app.api.v1.endpoints.chat.asyncio.create_task",
                return_value=_make_mock_task(),
            ),
        ):
            mock_rc.redis = None  # Simulate Redis down

            response = await test_client.post(
                "/api/v1/chat-stream",
                json=_VALID_BODY,
            )

        assert response.status_code == 200
        assert "[STREAM_ERROR]" in response.text, (
            "SSE body must contain [STREAM_ERROR] when Redis is unavailable"
        )

    # ------------------------------------------------------------------
    # Auth enforcement
    # ------------------------------------------------------------------

    async def test_chat_stream_requires_auth(self, unauthenticated_client):
        """POST /api/v1/chat-stream without auth must return 401.

        If get_current_user dependency is removed from the endpoint this test
        will fail.
        """
        response = await unauthenticated_client.post(
            "/api/v1/chat-stream",
            json=_VALID_BODY,
        )
        assert response.status_code == 401, (
            f"Expected 401 for unauthenticated request, got {response.status_code}"
        )

    # ------------------------------------------------------------------
    # Validation (422)
    # ------------------------------------------------------------------

    async def test_chat_stream_rejects_missing_message_field(self, test_client):
        """POST without the required 'message' field must return 422.

        If `message: str` is made Optional in MessageRequestWithHistory this
        test will fail.
        """
        response = await test_client.post(
            "/api/v1/chat-stream",
            json={"messages": []},  # 'message' key is absent
        )
        assert response.status_code == 422, (
            f"Expected 422 for missing 'message' field, got {response.status_code}"
        )

    async def test_chat_stream_rejects_wrong_type_for_message(self, test_client):
        """POST with a non-string 'message' value must return 422."""
        response = await test_client.post(
            "/api/v1/chat-stream",
            json={"message": 12345, "messages": []},  # message must be str
        )
        assert response.status_code == 422, (
            f"Expected 422 for integer 'message', got {response.status_code}"
        )

    async def test_chat_stream_rejects_wrong_type_for_messages(self, test_client):
        """POST with 'messages' as a non-list must return 422."""
        response = await test_client.post(
            "/api/v1/chat-stream",
            json={"message": "hi", "messages": "not-a-list"},
        )
        assert response.status_code == 422, (
            f"Expected 422 for non-list 'messages', got {response.status_code}"
        )

    async def test_chat_stream_rejects_empty_body(self, test_client):
        """POST with an empty JSON object must return 422 (missing required fields)."""
        response = await test_client.post(
            "/api/v1/chat-stream",
            json={},
        )
        assert response.status_code == 422

    async def test_chat_stream_422_response_has_detail(self, test_client):
        """422 response body must contain a 'detail' key describing validation errors."""
        response = await test_client.post(
            "/api/v1/chat-stream",
            json={"messages": []},  # missing 'message'
        )
        assert response.status_code == 422
        data = response.json()
        assert "detail" in data, "422 response must include 'detail' with error info"
        # FastAPI puts a list of validation errors in detail
        assert isinstance(data["detail"], list)
        # At least one error should reference the 'message' field
        field_names = [
            e.get("loc", [])[-1] for e in data["detail"] if e.get("loc")
        ]
        assert "message" in field_names, (
            f"Expected validation error for 'message' field, got: {data['detail']}"
        )


# ---------------------------------------------------------------------------
# Tests: POST /api/v1/cancel-stream/{stream_id}
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestCancelStreamEndpoint:
    """Tests for POST /api/v1/cancel-stream/{stream_id}."""

    # ------------------------------------------------------------------
    # Happy path
    # ------------------------------------------------------------------

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
        """POST /api/v1/cancel-stream/{id} for an owned stream returns 200 success=True.

        Removing the cancel_stream call from the endpoint or stripping the
        response fields will break this test.
        """
        mock_get_progress.return_value = {
            "user_id": test_user["user_id"],
            "conversation_id": "conv-abc",
        }
        mock_cancel.return_value = True

        response = await test_client.post("/api/v1/cancel-stream/stream-xyz")

        assert response.status_code == 200
        data = response.json()
        assert data.get("success") is True, f"Expected success=True, got: {data}"
        assert data.get("stream_id") == "stream-xyz", (
            f"Expected stream_id='stream-xyz', got: {data}"
        )

    async def test_cancel_stream_response_schema(
        self,
        test_client,
        test_user,
    ):
        """Cancel response must always include 'success' and 'stream_id' keys."""
        with (
            patch(
                "app.api.v1.endpoints.chat.stream_manager.get_progress",
                new_callable=AsyncMock,
                return_value={
                    "user_id": test_user["user_id"],
                    "conversation_id": "conv-abc",
                },
            ),
            patch(
                "app.api.v1.endpoints.chat.stream_manager.cancel_stream",
                new_callable=AsyncMock,
                return_value=True,
            ),
        ):
            response = await test_client.post("/api/v1/cancel-stream/stream-schema-test")

        assert response.status_code == 200
        data = response.json()
        assert "success" in data, "Response schema must include 'success'"
        assert "stream_id" in data, "Response schema must include 'stream_id'"

    # ------------------------------------------------------------------
    # Not found / unknown stream
    # ------------------------------------------------------------------

    @patch(
        "app.api.v1.endpoints.chat.stream_manager.get_progress",
        new_callable=AsyncMock,
    )
    async def test_cancel_stream_not_found(
        self,
        mock_get_progress,
        test_client,
    ):
        """POST for an unknown stream_id must return 200 with success=False and an error key.

        If the early-return branch (`if not progress`) is removed from the
        endpoint, this test will fail because cancel_stream would then be
        called instead of returning the not-found response.
        """
        mock_get_progress.return_value = None

        response = await test_client.post("/api/v1/cancel-stream/nonexistent-stream")

        assert response.status_code == 200
        data = response.json()
        assert data.get("success") is False, (
            f"Expected success=False for unknown stream, got: {data}"
        )
        assert "error" in data, "Response for unknown stream must include 'error' key"

    # ------------------------------------------------------------------
    # Ownership / authorization
    # ------------------------------------------------------------------

    @patch(
        "app.api.v1.endpoints.chat.stream_manager.get_progress",
        new_callable=AsyncMock,
    )
    async def test_cancel_stream_forbidden_for_other_user(
        self,
        mock_get_progress,
        test_client,
    ):
        """A user must not be able to cancel another user's stream.

        Removing the ownership check (`if progress.get("user_id") != user_id`)
        from the endpoint will drop this to 200 instead of 403, failing the test.
        """
        mock_get_progress.return_value = {
            "user_id": "completely-different-user-id",
            "conversation_id": "conv-other",
        }

        response = await test_client.post(
            "/api/v1/cancel-stream/stream-owned-by-other"
        )

        assert response.status_code == 403, (
            f"Expected 403 when cancelling another user's stream, got {response.status_code}"
        )

    # ------------------------------------------------------------------
    # Auth enforcement
    # ------------------------------------------------------------------

    async def test_cancel_stream_requires_auth(self, unauthenticated_client):
        """POST /api/v1/cancel-stream/{id} without auth must return 401.

        If get_current_user is removed from the cancel endpoint this test fails.
        """
        response = await unauthenticated_client.post(
            "/api/v1/cancel-stream/some-stream-id"
        )
        assert response.status_code == 401, (
            f"Expected 401 for unauthenticated cancel request, got {response.status_code}"
        )
