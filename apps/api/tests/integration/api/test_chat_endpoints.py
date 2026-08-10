"""Integration tests for chat API endpoints.

Covers POST /api/v1/chat-stream, POST /api/v1/cancel-stream/{stream_id} and
GET /api/v1/stream/{stream_id} with mocked service seams — verifying routing,
auth enforcement, exact response shapes, exact service-call arguments and SSE
framing through the full FastAPI request lifecycle — plus the module's pure
helpers (_build_chat_context, _resolve_source, _stream_from_redis) whose logic
the endpoint path exercises only indirectly.
"""

import asyncio
import inspect
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

from fastapi import HTTPException
from httpx import AsyncClient
import pytest

from app.api.v1.endpoints.chat import (
    _build_chat_context,
    _resolve_source,
    _stream_from_redis,
    chat_stream_endpoint,
    subscribe_executor_stream,
)
from app.constants.cache import STREAM_TURN_DEDUP_PREFIX, STREAM_TURN_DEDUP_TTL
from app.constants.log_tags import LogTag
from app.models.message_models import MessageRequestWithHistory
from shared.py.wide_events import log

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_BODY = {
    "message": "Hello, world!",
    "messages": [],
    "conversation_id": "conv-test-123",
}


class _FakeRequest:
    """Minimal Request stand-in: a headers dict and is_disconnected()."""

    def __init__(self, headers: dict | None = None) -> None:
        self.headers = headers or {}

    async def is_disconnected(self) -> bool:
        return False


async def _collect(agen):
    """Drain an async generator into a list."""
    return [chunk async for chunk in agen]


async def _empty_subscribe_stream(*args, **kwargs):
    """Async generator that yields nothing — simulates an ended SSE stream.

    stream_manager.subscribe_stream is an async generator.  Without this mock
    the SSE generator in chat.py would try to subscribe to a real Redis channel
    and fail with ConnectionError in tests.
    """
    return
    yield  # pragma: no cover – makes this a generator function  # NOSONAR


def _make_mock_task() -> MagicMock:
    t = MagicMock()
    t.add_done_callback = MagicMock()
    return t


def _make_subscription_mock():
    from app.models.payment_models import PlanType

    sub = MagicMock()
    sub.plan_type = PlanType.FREE
    return sub


def _make_log_context_mock() -> MagicMock:
    """MagicMock CM whose __aenter__/__aexit__ are async and never suppress."""
    cm = MagicMock()
    cm.return_value.__aenter__ = AsyncMock(return_value=cm.return_value)
    cm.return_value.__aexit__ = AsyncMock(return_value=False)
    return cm


# ---------------------------------------------------------------------------
# _build_chat_context
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestBuildChatContext:
    """_build_chat_context: exact wide-event chat context from a request body."""

    def test_populated_body_maps_every_field(self) -> None:
        body = MessageRequestWithHistory(
            message="hello",
            conversation_id="conv-1",
            messages=[{"role": "user", "content": "hi"}],
            fileIds=["f-1", "f-2"],
            fileData=[{"fileId": "f-3", "url": "u", "filename": "n"}],
            selectedTool="web_search",
            toolCategory="search",
            selectedWorkflow={
                "id": "wf-1",
                "title": "t",
                "description": "d",
                "steps": [],
            },
            selectedCalendarEvent={
                "id": "ev-1",
                "summary": "s",
                "description": "d",
                "start": {},
                "end": {},
            },
            replyToMessage={"id": "m-1", "content": "c", "role": "user"},
        )

        assert _build_chat_context(body, "conv-1", "stream-1") == {
            "conversation_id": "conv-1",
            "stream_id": "stream-1",
            "is_new_conversation": False,
            "message_count": 1,
            "has_files": True,
            "file_count": 3,
            "tool_category": "search",
            "has_reply": True,
            "has_calendar_event": True,
            "selected_workflow_id": "wf-1",
        }

    def test_sparse_body_maps_defaults(self) -> None:
        body = MessageRequestWithHistory(message="hello", messages=[])

        assert _build_chat_context(body, "conv-1", "stream-1") == {
            "conversation_id": "conv-1",
            "stream_id": "stream-1",
            "is_new_conversation": True,
            "message_count": 0,
            "has_files": False,
            "file_count": 0,
            "tool_category": None,
            "has_reply": False,
            "has_calendar_event": False,
            "selected_workflow_id": None,
        }

    def test_file_ids_alone_imply_files(self) -> None:
        body = MessageRequestWithHistory(message="hello", messages=[], fileIds=["f-1"])

        ctx = _build_chat_context(body, "conv-1", "stream-1")

        assert ctx["has_files"] is True
        assert ctx["file_count"] == 1


# ---------------------------------------------------------------------------
# _resolve_source
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestResolveSource:
    """_resolve_source: only the desktop client-type claims a non-web source."""

    def test_desktop_header_resolves_to_desktop(self) -> None:
        request = _FakeRequest(headers={"X-Client-Type": "desktop"})

        assert _resolve_source(request) == "desktop"

    def test_desktop_header_is_case_and_whitespace_insensitive(self) -> None:
        request = _FakeRequest(headers={"X-Client-Type": "  Desktop  "})

        assert _resolve_source(request) == "desktop"

    def test_other_client_types_fall_back_to_web(self) -> None:
        request = _FakeRequest(headers={"X-Client-Type": "mobile"})

        assert _resolve_source(request) == "web"

    def test_missing_header_falls_back_to_web(self) -> None:
        assert _resolve_source(_FakeRequest(headers={})) == "web"


# ---------------------------------------------------------------------------
# _stream_from_redis
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestStreamFromRedis:
    """_stream_from_redis: SSE frames from Redis, disconnect/error handling."""

    @pytest.fixture
    def trace_id(self) -> str:
        # A real trace id distinguishes the `get_trace_id() or None` value from
        # a hardcoded None in the log_context call. Reset on teardown so the
        # ambient trace never leaks into neighbouring tests.
        log.set(trace_id="trace-abc")
        yield "trace-abc"
        log.set(trace_id="")

    async def test_redis_down_yields_stream_error(
        self, trace_id: str
    ) -> None:
        log_error = MagicMock()
        with (
            patch("app.api.v1.endpoints.chat.redis_cache") as redis_mock,
            patch(
                "app.api.v1.endpoints.chat.stream_manager.subscribe_stream",
                new=_empty_subscribe_stream,
            ),
            patch("app.api.v1.endpoints.chat.log_context", new=_make_log_context_mock()) as log_ctx,
            patch.object(log, "error", log_error),
        ):
            redis_mock.redis = None

            chunks = await _collect(_stream_from_redis("s-1", _FakeRequest(), None))

        assert chunks == ["data: [STREAM_ERROR]\n\n"]
        log_error.assert_called_once_with(
            f"{LogTag.CHAT} Redis unavailable for stream", stream_id="s-1"
        )
        log_ctx.assert_called_once_with(
            "sse_delivery", trace_id="trace-abc", stream_id="s-1"
        )

    async def test_forwards_chunks_and_passes_last_event_id(
        self, trace_id: str
    ) -> None:
        calls: list[tuple[str, str | None]] = []

        async def _subscribe(stream_id, last_event_id=None):
            calls.append((stream_id, last_event_id))
            yield "data: one\n\n"
            yield "data: two\n\n"

        with (
            patch("app.api.v1.endpoints.chat.redis_cache") as redis_mock,
            patch(
                "app.api.v1.endpoints.chat.stream_manager.subscribe_stream", new=_subscribe
            ),
            patch("app.api.v1.endpoints.chat.log_context", new=_make_log_context_mock()),
        ):
            redis_mock.redis = MagicMock()

            chunks = await _collect(
                _stream_from_redis("s-1", _FakeRequest(), last_event_id="evt-5")
            )

        assert chunks == ["data: one\n\n", "data: two\n\n"]
        assert calls == [("s-1", "evt-5")]

    async def test_client_disconnect_stops_forwarding(self, trace_id: str) -> None:
        async def _subscribe(stream_id, last_event_id=None):
            yield "data: one\n\n"
            yield "data: two\n\n"

        class _DisconnectedRequest(_FakeRequest):
            async def is_disconnected(self) -> bool:
                return True

        log_set = MagicMock()
        log_info = MagicMock()
        with (
            patch("app.api.v1.endpoints.chat.redis_cache") as redis_mock,
            patch(
                "app.api.v1.endpoints.chat.stream_manager.subscribe_stream", new=_subscribe
            ),
            patch("app.api.v1.endpoints.chat.log_context", new=_make_log_context_mock()),
            patch.object(log, "set", log_set),
            patch.object(log, "info", log_info),
        ):
            redis_mock.redis = MagicMock()

            chunks = await _collect(_stream_from_redis("s-1", _DisconnectedRequest(), None))

        assert chunks == []
        log_set.assert_called_once_with(client_disconnected=True)
        log_info.assert_called_once_with(
            f"{LogTag.CHAT} Client disconnected, stream continues in background",
            stream_id="s-1",
        )

    async def test_cancelled_error_is_logged_and_reraises(self, trace_id: str) -> None:
        async def _subscribe(stream_id, last_event_id=None):
            yield "data: one\n\n"
            raise asyncio.CancelledError()

        log_set = MagicMock()
        log_info = MagicMock()
        with (
            patch("app.api.v1.endpoints.chat.redis_cache") as redis_mock,
            patch(
                "app.api.v1.endpoints.chat.stream_manager.subscribe_stream", new=_subscribe
            ),
            patch("app.api.v1.endpoints.chat.log_context", new=_make_log_context_mock()),
            patch.object(log, "set", log_set),
            patch.object(log, "info", log_info),
        ):
            redis_mock.redis = MagicMock()

            with pytest.raises(asyncio.CancelledError):
                await _collect(_stream_from_redis("s-1", _FakeRequest(), None))

        log_set.assert_called_once_with(client_disconnected=True)
        log_info.assert_called_once_with(
            f"{LogTag.CHAT} Client connection cancelled", stream_id="s-1"
        )

    async def test_subscribe_error_is_logged_and_swallowed(self, trace_id: str) -> None:
        async def _subscribe(stream_id, last_event_id=None):
            yield "data: one\n\n"
            raise ValueError("boom")

        log_error = MagicMock()
        with (
            patch("app.api.v1.endpoints.chat.redis_cache") as redis_mock,
            patch(
                "app.api.v1.endpoints.chat.stream_manager.subscribe_stream", new=_subscribe
            ),
            patch("app.api.v1.endpoints.chat.log_context", new=_make_log_context_mock()),
            patch.object(log, "error", log_error),
        ):
            redis_mock.redis = MagicMock()

            chunks = await _collect(_stream_from_redis("s-1", _FakeRequest(), None))

        assert chunks == ["data: one\n\n"]
        log_error.assert_called_once_with(
            f"{LogTag.CHAT} Error streaming to client",
            stream_id="s-1",
            error_type="ValueError",
            error="boom",
        )


# ---------------------------------------------------------------------------
# POST /api/v1/chat-stream
# ---------------------------------------------------------------------------


@pytest.fixture
def chat_stream_mocks():
    """Patch every seam the chat-stream endpoint touches and return the mocks.

    The tiered rate limiter, the daily cost budget, the stream manager and the
    background-task spawner are all mocked so the endpoint's own logic — the
    idempotency claim, argument threading, response shape — is what the tests
    exercise.
    """
    subscription = AsyncMock()
    subscription.return_value = _make_subscription_mock()

    def _spawn_side_effect(coro, **kwargs):
        coro.close()
        return _make_mock_task()

    subscribe_calls: list[tuple[str, str | None]] = []

    async def _one_chunk_subscribe(stream_id, last_event_id=None):
        subscribe_calls.append((stream_id, last_event_id))
        yield "data: hello\n\n"

    with (
        patch(
            "app.api.v1.middleware.tiered_rate_limiter.tiered_limiter.check_and_increment",
            new_callable=AsyncMock,
        ) as rate_check,
        patch(
            "app.decorators.rate_limiting.payment_service.get_user_subscription_status",
            new=subscription,
        ),
        patch(
            "app.api.v1.endpoints.chat.enforce_daily_cost_budget",
            new_callable=AsyncMock,
        ) as budget,
        patch(
            "app.api.v1.endpoints.chat.stream_manager.start_stream",
            new_callable=AsyncMock,
        ) as start_stream,
        patch(
            "app.api.v1.endpoints.chat.stream_manager.subscribe_stream",
            new=_one_chunk_subscribe,
        ),
        patch(
            "app.api.v1.endpoints.chat.run_chat_stream_background",
            new_callable=AsyncMock,
        ) as background,
        patch(
            "app.api.v1.endpoints.chat.spawn_background_task",
            side_effect=_spawn_side_effect,
        ) as spawn,
        patch("app.api.v1.endpoints.chat.redis_cache") as redis_cache,
        patch(
            "app.api.v1.endpoints.chat.log_context", new=_make_log_context_mock()
        ) as log_context,
        patch.object(log, "set") as log_set,
    ):
        yield {
            "rate_check": rate_check,
            "subscription": subscription,
            "budget": budget,
            "start_stream": start_stream,
            "background": background,
            "spawn": spawn,
            "redis_cache": redis_cache,
            "log_set": log_set,
            "log_context": log_context,
            "subscribe_calls": subscribe_calls,
        }


@pytest.mark.integration
class TestChatStreamEndpoint:
    """Tests for POST /api/v1/chat-stream."""

    async def test_happy_path_exact_contract(
        self,
        chat_stream_mocks,
        test_client: AsyncClient,
        test_user: dict,
    ) -> None:
        """POST /api/v1/chat-stream: status, SSE headers, and exact service args."""
        mocks = chat_stream_mocks
        mocks["redis_cache"].redis = MagicMock()

        response = await test_client.post(
            "/api/v1/chat-stream",
            json={**_VALID_BODY, "selectedTool": "web_search"},
        )

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        stream_id = response.headers["x-stream-id"]
        UUID(stream_id)
        assert response.headers["cache-control"] == "no-cache"
        assert response.headers["connection"] == "keep-alive"
        assert response.headers["x-accel-buffering"] == "no"
        assert response.text == "data: hello\n\n"

        mocks["budget"].assert_awaited_once_with(
            "integration-test-user-1", feature_key="chat_messages"
        )
        mocks["start_stream"].assert_awaited_once_with(
            stream_id=stream_id,
            conversation_id="conv-test-123",
            user_id="integration-test-user-1",
        )
        assert mocks["background"].call_args.kwargs == {
            "stream_id": stream_id,
            "body": MessageRequestWithHistory(**_VALID_BODY, selectedTool="web_search"),
            "user": {**test_user, "timezone": "UTC"},
            "conversation_id": "conv-test-123",
            "source": "web",
        }
        mocks["spawn"].assert_called_once()
        assert inspect.iscoroutine(mocks["spawn"].call_args.args[0])
        mocks["redis_cache"].redis.set.assert_not_called()
        assert mocks["subscribe_calls"] == [(stream_id, None)]
        log_context_call = mocks["log_context"].call_args
        assert log_context_call.args == ("sse_delivery",)
        assert log_context_call.kwargs["stream_id"] == stream_id
        mocks["log_set"].assert_any_call(
            user={"id": "integration-test-user-1"},
            chat={
                "conversation_id": "conv-test-123",
                "stream_id": stream_id,
                "is_new_conversation": False,
                "message_count": 0,
                "has_files": False,
                "file_count": 0,
                "tool_category": None,
                "has_reply": False,
                "has_calendar_event": False,
                "selected_workflow_id": None,
            },
            user_message_length=0,
            selected_tool="web_search",
        )

    async def test_turn_id_claims_dedup_key(
        self,
        chat_stream_mocks,
        test_client: AsyncClient,
    ) -> None:
        """With a turn_id the idempotency key is claimed in Redis, atomically."""
        mocks = chat_stream_mocks
        redis = MagicMock()
        redis.set = AsyncMock(return_value=True)
        mocks["redis_cache"].redis = redis

        response = await test_client.post(
            "/api/v1/chat-stream",
            json={**_VALID_BODY, "turn_id": "turn-1"},
        )

        assert response.status_code == 200
        stream_id = response.headers["x-stream-id"]
        mocks["redis_cache"].redis.set.assert_awaited_once_with(
            f"{STREAM_TURN_DEDUP_PREFIX}integration-test-user-1:turn-1",
            stream_id,
            nx=True,
            ex=STREAM_TURN_DEDUP_TTL,
        )

    async def test_duplicate_turn_id_returns_409(
        self,
        chat_stream_mocks,
        test_client: AsyncClient,
    ) -> None:
        """A turn_id whose key is already claimed is rejected with 409."""
        mocks = chat_stream_mocks
        redis = MagicMock()
        redis.set = AsyncMock(return_value=None)
        mocks["redis_cache"].redis = redis

        response = await test_client.post(
            "/api/v1/chat-stream",
            json={**_VALID_BODY, "turn_id": "turn-1"},
        )

        assert response.status_code == 409
        assert response.json()["detail"] == (
            "duplicate turn_id: this send was already accepted"
        )
        mocks["budget"].assert_awaited_once()
        mocks["start_stream"].assert_not_awaited()
        mocks["spawn"].assert_not_called()

    async def test_turn_id_with_redis_down_skips_dedup_and_streams_error(
        self,
        chat_stream_mocks,
        test_client: AsyncClient,
    ) -> None:
        """With Redis down the idempotency claim is skipped, not fatal."""
        mocks = chat_stream_mocks
        mocks["redis_cache"].redis = None

        response = await test_client.post(
            "/api/v1/chat-stream",
            json={**_VALID_BODY, "turn_id": "turn-1"},
        )

        assert response.status_code == 200
        assert response.text == "data: [STREAM_ERROR]\n\n"

    async def test_missing_conversation_id_generates_uuid(
        self,
        chat_stream_mocks,
        test_client: AsyncClient,
    ) -> None:
        """When conversation_id is omitted the endpoint generates a fresh UUID."""
        mocks = chat_stream_mocks
        mocks["redis_cache"].redis = MagicMock()

        response = await test_client.post(
            "/api/v1/chat-stream",
            json={"message": "Hi!", "messages": []},
        )

        assert response.status_code == 200
        conversation_id = mocks["start_stream"].await_args.kwargs["conversation_id"]
        UUID(conversation_id)

    async def test_desktop_client_type_forwards_source(
        self,
        chat_stream_mocks,
        test_client: AsyncClient,
    ) -> None:
        """The X-Client-Type header is forwarded as the conversation source."""
        mocks = chat_stream_mocks
        mocks["redis_cache"].redis = MagicMock()

        response = await test_client.post(
            "/api/v1/chat-stream",
            json=_VALID_BODY,
            headers={"X-Client-Type": "desktop"},
        )

        assert response.status_code == 200
        assert mocks["background"].call_args.kwargs["source"] == "desktop"

    async def test_missing_user_id_raises_400(self, chat_stream_mocks) -> None:
        """A user without user_id fails with 400 before any stream work."""
        with pytest.raises(HTTPException) as exc_info:
            await chat_stream_endpoint.__wrapped__(
                request=_FakeRequest(),
                body=MessageRequestWithHistory(message="hi", messages=[]),
                user={"email": "no-id@example.com"},
                home_timezone="UTC",
            )

        assert exc_info.value.status_code == 400
        assert exc_info.value.detail == "user_id is required"

    async def test_requires_auth(self, unauthenticated_client: AsyncClient) -> None:
        """POST /api/v1/chat-stream without auth must return 401."""
        response = await unauthenticated_client.post(
            "/api/v1/chat-stream",
            json=_VALID_BODY,
        )
        assert response.status_code == 401

    async def test_rejects_invalid_body(self, test_client: AsyncClient) -> None:
        """POST /api/v1/chat-stream with a missing required field returns 422."""
        response = await test_client.post(
            "/api/v1/chat-stream",
            json={"messages": []},  # no 'message' key
        )
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/v1/stream/{stream_id}
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestSubscribeExecutorStream:
    """Tests for GET /api/v1/stream/{stream_id}."""

    @staticmethod
    def _progress(user_id: str, *, is_complete: bool = False) -> dict:
        return {"user_id": user_id, "conversation_id": "conv-abc", "is_complete": is_complete}

    async def test_live_stream_exact_contract(
        self,
        test_client: AsyncClient,
        test_user: dict,
    ) -> None:
        """A running stream is forwarded, honouring Last-Event-ID, with exact headers."""
        calls: list[tuple[str, str | None]] = []

        async def _subscribe(stream_id, last_event_id=None):
            calls.append((stream_id, last_event_id))
            yield "data: hello\n\n"

        with (
            patch(
                "app.api.v1.endpoints.chat.stream_manager.get_progress",
                new_callable=AsyncMock,
            ) as progress,
            patch(
                "app.api.v1.endpoints.chat.stream_manager.subscribe_stream",
                new=_subscribe,
            ),
            patch("app.api.v1.endpoints.chat.redis_cache") as redis_mock,
            patch("app.api.v1.endpoints.chat.log_context", new=_make_log_context_mock()),
            patch.object(log, "set") as log_set,
            patch.object(log, "info") as log_info,
        ):
            progress.return_value = self._progress(test_user["user_id"])
            redis_mock.redis = MagicMock()

            response = await test_client.get(
                "/api/v1/stream/stream-abc",
                headers={"Last-Event-ID": "evt-9"},
            )

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.headers["cache-control"] == "no-cache"
        assert response.headers["connection"] == "keep-alive"
        assert response.headers["x-accel-buffering"] == "no"
        assert response.headers["access-control-allow-origin"] == "*"
        assert response.text == "data: hello\n\n"
        assert calls == [("stream-abc", "evt-9")]
        progress.assert_awaited_once_with("stream-abc")
        log_info.assert_called_once_with(
            f"{LogTag.CHAT} Client subscribed to executor stream", stream_id="stream-abc"
        )
        log_set.assert_any_call(
            user={"id": test_user["user_id"]}, chat={"stream_id": "stream-abc"}
        )

    async def test_completed_stream_returns_done_frame(
        self,
        test_client: AsyncClient,
        test_user: dict,
    ) -> None:
        """A stream that already finished returns an immediate [DONE] frame."""
        with (
            patch(
                "app.api.v1.endpoints.chat.stream_manager.get_progress",
                new_callable=AsyncMock,
            ) as progress,
            patch(
                "app.api.v1.endpoints.chat.stream_manager.subscribe_stream",
                new=_empty_subscribe_stream,
            ),
            patch("app.api.v1.endpoints.chat.redis_cache") as redis_mock,
            patch.object(log, "info") as log_info,
        ):
            progress.return_value = self._progress(
                test_user["user_id"], is_complete=True
            )
            redis_mock.redis = MagicMock()

            response = await test_client.get("/api/v1/stream/stream-abc")

        assert response.status_code == 200
        assert response.text == "data: [DONE]\n\n"
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.headers["cache-control"] == "no-cache"
        assert response.headers["connection"] == "keep-alive"
        assert response.headers["x-accel-buffering"] == "no"
        assert response.headers["access-control-allow-origin"] == "*"
        log_info.assert_called_once_with(
            f"{LogTag.CHAT} Executor stream already complete, returning [DONE]",
            stream_id="stream-abc",
        )

    async def test_unknown_stream_returns_404(self, test_client: AsyncClient) -> None:
        """Subscribing to a stream that never started returns 404."""
        with patch(
            "app.api.v1.endpoints.chat.stream_manager.get_progress",
            new_callable=AsyncMock,
        ) as progress:
            progress.return_value = None

            response = await test_client.get("/api/v1/stream/stream-abc")

        assert response.status_code == 404
        assert response.json()["detail"] == "Stream not found"

    async def test_other_users_stream_returns_403(
        self,
        test_client: AsyncClient,
        test_user: dict,
    ) -> None:
        """A user cannot subscribe to another user's stream (403)."""
        with (
            patch(
                "app.api.v1.endpoints.chat.stream_manager.get_progress",
                new_callable=AsyncMock,
            ) as progress,
            patch(
                "app.api.v1.endpoints.chat.stream_manager.subscribe_stream",
                new=_empty_subscribe_stream,
            ),
            patch("app.api.v1.endpoints.chat.redis_cache") as redis_mock,
        ):
            progress.return_value = self._progress("someone-else")
            redis_mock.redis = MagicMock()

            response = await test_client.get("/api/v1/stream/stream-abc")

        assert response.status_code == 403
        assert response.json()["detail"] == "Not authorized to subscribe to this stream"

    async def test_missing_user_id_raises_400(self) -> None:
        """A user without user_id fails with 400 before any lookup."""
        with patch(
            "app.api.v1.endpoints.chat.stream_manager.get_progress",
            new_callable=AsyncMock,
        ):
            with pytest.raises(HTTPException) as exc_info:
                await subscribe_executor_stream(
                    stream_id="stream-abc",
                    request=_FakeRequest(),
                    user={"email": "no-id@example.com"},
                )

        assert exc_info.value.status_code == 400
        assert exc_info.value.detail == "user_id is required"

    async def test_requires_auth(self, unauthenticated_client: AsyncClient) -> None:
        """GET /api/v1/stream/{id} without auth must return 401."""
        response = await unauthenticated_client.get("/api/v1/stream/stream-abc")
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# POST /api/v1/cancel-stream/{stream_id}
# ---------------------------------------------------------------------------


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
    @patch.object(log, "set")
    @patch.object(log, "info")
    async def test_cancel_stream_returns_success(
        self,
        log_info,
        log_set,
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
        assert response.json() == {
            "success": True,
            "stream_id": "stream-xyz",
            "error": None,
        }
        mock_get_progress.assert_awaited_once_with("stream-xyz")
        mock_cancel.assert_awaited_once_with("stream-xyz")
        log_info.assert_called_once_with(
            f"{LogTag.CHAT} Cancel stream request",
            stream_id="stream-xyz",
            success=True,
        )
        log_set.assert_any_call(
            user={"id": test_user["user_id"]}, chat={"stream_id": "stream-xyz"}
        )

    @patch(
        "app.api.v1.endpoints.chat.stream_manager.get_progress",
        new_callable=AsyncMock,
    )
    @patch(
        "app.api.v1.endpoints.chat.stream_manager.cancel_stream",
        new_callable=AsyncMock,
    )
    async def test_cancel_stream_reports_cancel_failure(
        self,
        mock_cancel,
        mock_get_progress,
        test_client,
        test_user,
    ):
        """When the underlying cancel fails the response says so."""
        mock_get_progress.return_value = {
            "user_id": test_user["user_id"],
            "conversation_id": "conv-abc",
        }
        mock_cancel.return_value = False

        response = await test_client.post("/api/v1/cancel-stream/stream-xyz")

        assert response.status_code == 200
        assert response.json() == {
            "success": False,
            "stream_id": "stream-xyz",
            "error": None,
        }
        mock_cancel.assert_awaited_once_with("stream-xyz")

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
        assert response.json() == {
            "success": False,
            "stream_id": "nonexistent-stream",
            "error": "Stream not found",
        }

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
        mock_get_progress.return_value = {
            "user_id": "different-user-id",
            "conversation_id": "conv-other",
        }

        response = await test_client.post("/api/v1/cancel-stream/stream-owned-by-other")

        assert response.status_code == 403
        assert response.json()["detail"] == "Not authorized to cancel this stream"

    async def test_cancel_stream_requires_auth(self, unauthenticated_client):
        """POST /api/v1/cancel-stream/{id} without auth must return 401."""
        response = await unauthenticated_client.post("/api/v1/cancel-stream/some-stream-id")
        assert response.status_code == 401
