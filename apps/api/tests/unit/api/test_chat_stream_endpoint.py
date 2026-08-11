"""GET /stream/{stream_id} — replay semantics of the executor-stream endpoint.

Regression: a completed stream whose Redis event log still exists must replay
that log, not short-circuit to a bare [DONE]. A HIL resume publishes its
frames (second approval card included) and closes within ~100ms — faster than
the client's websocket-to-fetch round trip — so the short-circuit dropped
every frame of nearly every resumed run.
"""

from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, patch

import pytest

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
                    return_value={"user_id": "507f1f77bcf86cd799439011", "is_complete": True}
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
        ):
            async with client.stream("GET", f"/api/v1/stream/{STREAM_ID}") as response:
                assert response.status_code == 200
                body = "".join([chunk async for chunk in response.aiter_text()])

        assert "approval_request" in body
        assert "[DONE]" in body

    async def test_completed_stream_with_expired_log_returns_done_only(self, client) -> None:
        with (
            patch(
                "app.api.v1.endpoints.chat.stream_manager.get_progress",
                new=AsyncMock(
                    return_value={"user_id": "507f1f77bcf86cd799439011", "is_complete": True}
                ),
            ),
            patch(
                "app.api.v1.endpoints.chat.stream_manager.has_events",
                new=AsyncMock(return_value=False),
            ),
        ):
            async with client.stream("GET", f"/api/v1/stream/{STREAM_ID}") as response:
                assert response.status_code == 200
                body = "".join([chunk async for chunk in response.aiter_text()])

        assert body == "data: [DONE]\n\n"
