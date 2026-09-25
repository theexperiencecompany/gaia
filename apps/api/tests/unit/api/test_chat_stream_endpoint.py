"""The chat stream endpoints: replaying a stream, and stopping one.

Regression: a completed stream whose Redis event log still exists must replay
that log, not short-circuit to a bare [DONE]. A HIL resume publishes its
frames (second approval card included) and closes within ~100ms — faster than
the client's websocket-to-fetch round trip — so the short-circuit dropped
every frame of nearly every resumed run.

Regression: a Stop must reach the background subagents the turn dispatched,
which run on their own streams and outlive the turn.
"""

import asyncio
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import AsyncClient
from prometheus_client import REGISTRY
import pytest

from app.agents.core.background.running_registry import RunningSubagents
from app.api.v1.endpoints.chat import _stream_from_redis
from app.core.stream_manager import stream_manager
from app.models.agent_models import RunningSubagent
from tests.conftest import FAKE_USER, FAKE_USER_2

pytestmark = pytest.mark.unit

STREAM_ID = "queued_regression-replay"

FRAMES = [
    'data: {"tool_data": {"tool_name": "approval_request", "data": {"approval_id": "a2"}}}\n\n',
    "data: [DONE]\n\n",
]


def _fake_subscribe(
    stream_id: str, keepalive_interval: float = 15, last_event_id: str | None = None
) -> AsyncGenerator[str, None]:
    async def _gen() -> AsyncGenerator[str, None]:
        for frame in FRAMES:
            yield frame

    return _gen()


class TestSubscribeExecutorStreamReplay:
    @pytest.mark.regression
    async def test_completed_stream_with_live_log_replays_frames(self, client) -> None:
        with (
            patch(
                "app.api.v1.endpoints.chat.stream_manager.get_progress",
                new=AsyncMock(
                    return_value={
                        "user_id": "507f1f77bcf86cd799439011",
                        "conversation_id": "conv-1",
                        "is_complete": True,
                    }
                ),
            ),
            patch(
                "app.api.v1.endpoints.chat.stream_manager.has_events",
                new=AsyncMock(return_value=True),
            ),
            patch(
                "app.api.v1.endpoints.chat.stream_manager.subscribe_stream",
                new=_fake_subscribe,
            ),
            # _stream_from_redis checks this singleton before subscribe_stream;
            # an xdist-shared client state could otherwise flip this test
            # between replay and [STREAM_ERROR]. Pinning isolates the assertion.
            patch("app.api.v1.endpoints.chat.redis_cache.redis", new=MagicMock()),
        ):
            async with client.stream("GET", f"/api/v1/stream/{STREAM_ID}") as response:
                assert response.status_code == 200
                body = "".join([chunk async for chunk in response.aiter_text()])

        assert "approval_request" in body
        assert "[DONE]" in body

    async def test_no_redis_client_reports_a_stream_error(self, client) -> None:
        """Without a Redis client there is no event log to follow, and the client must be told so rather than handed a bare [DONE]."""
        with (
            patch(
                "app.api.v1.endpoints.chat.stream_manager.get_progress",
                new=AsyncMock(
                    return_value={
                        "user_id": "507f1f77bcf86cd799439011",
                        "conversation_id": "conv-1",
                        "is_complete": True,
                    }
                ),
            ),
            patch(
                "app.api.v1.endpoints.chat.stream_manager.has_events",
                new=AsyncMock(return_value=True),
            ),
            patch("app.api.v1.endpoints.chat.redis_cache.redis", new=None),
        ):
            async with client.stream("GET", f"/api/v1/stream/{STREAM_ID}") as response:
                assert response.status_code == 200
                body = "".join([chunk async for chunk in response.aiter_text()])

        assert body == "data: [STREAM_ERROR]\n\n"

    @pytest.mark.regression
    async def test_the_log_lookup_names_the_requested_stream(self, client) -> None:
        """The expired-log check must ask about this stream; asking about another id answers for the wrong stream and reads a live log as expired."""
        events_by_stream = {STREAM_ID: True}

        async def _has_events(stream_id: str) -> bool:
            return events_by_stream.get(stream_id, False)

        with (
            patch(
                "app.api.v1.endpoints.chat.stream_manager.get_progress",
                new=AsyncMock(
                    return_value={
                        "user_id": "507f1f77bcf86cd799439011",
                        "conversation_id": "conv-1",
                        "is_complete": True,
                    }
                ),
            ),
            patch("app.api.v1.endpoints.chat.stream_manager.has_events", new=_has_events),
            patch(
                "app.api.v1.endpoints.chat.stream_manager.subscribe_stream",
                new=_fake_subscribe,
            ),
            patch("app.api.v1.endpoints.chat.redis_cache.redis", new=MagicMock()),
        ):
            async with client.stream("GET", f"/api/v1/stream/{STREAM_ID}") as response:
                assert response.status_code == 200
                body = "".join([chunk async for chunk in response.aiter_text()])

        assert body == "".join(FRAMES)

    async def test_completed_stream_with_expired_log_returns_done_only(self, client) -> None:
        # Both are pinned even though the short-circuit means neither should
        # be reached — if the guard stops short-circuiting, this fails fast
        # on unexpected frames instead of hanging on real keepalives.
        get_progress = AsyncMock(
            return_value={
                "user_id": "507f1f77bcf86cd799439011",
                "conversation_id": "conv-1",
                "is_complete": True,
            }
        )
        with (
            patch("app.api.v1.endpoints.chat.stream_manager.get_progress", new=get_progress),
            patch(
                "app.api.v1.endpoints.chat.stream_manager.has_events",
                new=AsyncMock(return_value=False),
            ),
            patch(
                "app.api.v1.endpoints.chat.stream_manager.subscribe_stream",
                new=_fake_subscribe,
            ),
            patch("app.api.v1.endpoints.chat.redis_cache.redis", new=MagicMock()),
        ):
            async with client.stream("GET", f"/api/v1/stream/{STREAM_ID}") as response:
                assert response.status_code == 200
                body = "".join([chunk async for chunk in response.aiter_text()])

        assert body == "data: [DONE]\n\n"
        get_progress.assert_awaited_once_with(STREAM_ID)

    @pytest.mark.parametrize("has_events", [True, False])
    async def test_a_live_stream_always_replays_whatever_the_log_says(
        self, client, has_events: bool
    ) -> None:
        """The expired-log short-circuit is gated on completion first; a still-running stream has more frames coming and must be followed regardless."""
        with (
            patch(
                "app.api.v1.endpoints.chat.stream_manager.get_progress",
                new=AsyncMock(
                    return_value={
                        "user_id": "507f1f77bcf86cd799439011",
                        "conversation_id": "conv-1",
                        "is_complete": False,
                    }
                ),
            ),
            patch(
                "app.api.v1.endpoints.chat.stream_manager.has_events",
                new=AsyncMock(return_value=has_events),
            ),
            patch(
                "app.api.v1.endpoints.chat.stream_manager.subscribe_stream",
                new=_fake_subscribe,
            ),
            patch("app.api.v1.endpoints.chat.redis_cache.redis", new=MagicMock()),
        ):
            async with client.stream("GET", f"/api/v1/stream/{STREAM_ID}") as response:
                assert response.status_code == 200
                body = "".join([chunk async for chunk in response.aiter_text()])

        assert body == "".join(FRAMES)


def _delivery_count(status: str) -> float:
    return REGISTRY.get_sample_value("sse_delivery_seconds_count", {"status": status}) or 0.0


def _connected_request() -> MagicMock:
    request = MagicMock()
    request.is_disconnected = AsyncMock(return_value=False)
    return request


def _dropped_request() -> MagicMock:
    request = MagicMock()
    request.is_disconnected = AsyncMock(return_value=True)
    return request


class TestSSEDeliveryLatency:
    async def test_completed_delivery_observes_span(self) -> None:
        before = _delivery_count("completed")
        with (
            patch(
                "app.api.v1.endpoints.chat.stream_manager.subscribe_stream",
                new=_fake_subscribe,
            ),
            patch("app.api.v1.endpoints.chat.redis_cache.redis", new=MagicMock()),
        ):
            frames = [chunk async for chunk in _stream_from_redis("s-lat", _connected_request())]

        assert frames == FRAMES
        assert _delivery_count("completed") == before + 1

    async def test_disconnect_observes_disconnected_span(self) -> None:
        before = _delivery_count("disconnected")
        with (
            patch(
                "app.api.v1.endpoints.chat.stream_manager.subscribe_stream",
                new=_fake_subscribe,
            ),
            patch("app.api.v1.endpoints.chat.redis_cache.redis", new=MagicMock()),
        ):
            frames = [chunk async for chunk in _stream_from_redis("s-lat", _dropped_request())]

        assert frames == []
        assert _delivery_count("disconnected") == before + 1

    async def test_abandoned_delivery_observes_abandoned_span(self) -> None:
        before = _delivery_count("abandoned")
        with (
            patch(
                "app.api.v1.endpoints.chat.stream_manager.subscribe_stream",
                new=_fake_subscribe,
            ),
            patch("app.api.v1.endpoints.chat.redis_cache.redis", new=MagicMock()),
        ):
            stream = _stream_from_redis("s-lat-abandoned", _connected_request())
            first = await stream.__anext__()
            await stream.aclose()

        assert first == FRAMES[0]
        assert _delivery_count("abandoned") == before + 1

    async def test_error_delivery_observes_error_span(self) -> None:
        async def _boom(*_args: object, **_kwargs: object) -> AsyncGenerator[str, None]:
            raise RuntimeError("subscribe failed")
            yield ""  # pragma: no cover — makes this an async generator

        before = _delivery_count("error")
        with (
            patch("app.api.v1.endpoints.chat.stream_manager.subscribe_stream", new=_boom),
            patch("app.api.v1.endpoints.chat.redis_cache.redis", new=MagicMock()),
        ):
            [chunk async for chunk in _stream_from_redis("s-lat-error", _connected_request())]

        assert _delivery_count("error") == before + 1

    async def test_delivery_span_uses_exact_elapsed_seconds(self) -> None:
        labels = {"status": "completed"}
        before = REGISTRY.get_sample_value("sse_delivery_seconds_sum", labels) or 0.0
        fake_time = MagicMock()
        fake_time.perf_counter.side_effect = [100.0, 100.5]
        with (
            patch(
                "app.api.v1.endpoints.chat.stream_manager.subscribe_stream",
                new=_fake_subscribe,
            ),
            patch("app.api.v1.endpoints.chat.redis_cache.redis", new=MagicMock()),
            patch("app.api.v1.endpoints.chat.time", new=fake_time),
        ):
            [chunk async for chunk in _stream_from_redis("s-lat-exact", _connected_request())]

        elapsed = (REGISTRY.get_sample_value("sse_delivery_seconds_sum", labels) or 0.0) - before
        assert elapsed == pytest.approx(0.5)

    async def test_cancelled_delivery_observes_disconnected_span(self) -> None:
        """Cancellation mid-stream is a disconnect, not an error, so it stays out of that series."""
        before = _delivery_count("disconnected")
        with (
            patch(
                "app.api.v1.endpoints.chat.stream_manager.subscribe_stream",
                new=_fake_subscribe,
            ),
            patch("app.api.v1.endpoints.chat.redis_cache.redis", new=MagicMock()),
        ):
            stream = _stream_from_redis("s-lat-cancelled", _connected_request())
            await stream.__anext__()
            with pytest.raises(asyncio.CancelledError):
                await stream.athrow(asyncio.CancelledError)

        assert _delivery_count("disconnected") == before + 1


CONVERSATION = "conv-cancel"
TURN = "turn-stream"


async def _dispatched_by_turn() -> str:
    stream_id = "subagent_s1"
    claimed = await RunningSubagents(CONVERSATION).claim(
        RunningSubagent(
            subagent_id="s1",
            subagent_thread_id=f"spawn_{CONVERSATION}_s1",
            integration_id="ticker",
            agent_name="ticker_agent",
            task_summary="tick",
            started_at="2026-09-25T00:00:00Z",
            stream_id=stream_id,
            dispatched_by=TURN,
        )
    )
    assert claimed
    return stream_id


@pytest.mark.usefixtures("fake_redis")
class TestCancelStream:
    @pytest.mark.regression
    async def test_stopping_a_turn_stops_the_background_subagents_it_dispatched(
        self, client: AsyncClient
    ) -> None:
        await stream_manager.start_stream(TURN, CONVERSATION, FAKE_USER.user_id)
        subagent_stream = await _dispatched_by_turn()

        response = await client.post(f"/api/v1/cancel-stream/{TURN}")

        assert response.json() == {"success": True, "stream_id": TURN, "error": None}
        assert await stream_manager.is_cancelled(TURN)
        assert await stream_manager.is_cancelled(subagent_stream)

    async def test_another_users_stream_is_refused_and_nothing_stops(
        self, client: AsyncClient
    ) -> None:
        await stream_manager.start_stream(TURN, CONVERSATION, FAKE_USER_2.user_id)
        subagent_stream = await _dispatched_by_turn()

        response = await client.post(f"/api/v1/cancel-stream/{TURN}")

        assert response.status_code == 403
        assert not await stream_manager.is_cancelled(TURN)
        assert not await stream_manager.is_cancelled(subagent_stream)

    async def test_an_unknown_stream_is_reported_not_found(self, client: AsyncClient) -> None:
        response = await client.post("/api/v1/cancel-stream/no-such-stream")

        assert response.json() == {
            "success": False,
            "stream_id": "no-such-stream",
            "error": "Stream not found",
        }
