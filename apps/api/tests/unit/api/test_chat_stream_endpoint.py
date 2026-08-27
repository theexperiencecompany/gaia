"""GET /stream/{stream_id} — replay semantics of the executor-stream endpoint.

Regression: a completed stream whose Redis event log still exists must replay
that log, not short-circuit to a bare [DONE]. A HIL resume publishes its
frames (second approval card included) and closes within ~100ms — faster than
the client's websocket-to-fetch round trip — so the short-circuit dropped
every frame of nearly every resumed run.
"""

from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

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
            # `_stream_from_redis` checks this singleton before it ever reaches
            # the patched `subscribe_stream`, and nothing in a unit run owns its
            # state — whether a previous test in the same xdist worker left the
            # client connected decided whether this one replayed frames or
            # emitted [STREAM_ERROR]. Pinning it makes the replay assertion
            # depend on the replay logic and nothing else; the unavailable
            # branch is covered separately below.
            patch("app.api.v1.endpoints.chat.redis_cache.redis", new=MagicMock()),
        ):
            async with client.stream("GET", f"/api/v1/stream/{STREAM_ID}") as response:
                assert response.status_code == 200
                body = "".join([chunk async for chunk in response.aiter_text()])

        assert "approval_request" in body
        assert "[DONE]" in body

    async def test_no_redis_client_reports_a_stream_error(self, client) -> None:
        """The branch the flake was silently taking. Without a Redis client there
        is no event log to follow, and the client must be told so rather than
        handed a bare [DONE] it would read as "the turn produced nothing"."""
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
            patch("app.api.v1.endpoints.chat.redis_cache.redis", new=None),
        ):
            async with client.stream("GET", f"/api/v1/stream/{STREAM_ID}") as response:
                assert response.status_code == 200
                body = "".join([chunk async for chunk in response.aiter_text()])

        assert body == "data: [STREAM_ERROR]\n\n"

    @pytest.mark.regression
    async def test_the_log_lookup_names_the_requested_stream(self, client) -> None:
        """The expired-log check must ask about THIS stream. Asking about any
        other id answers for the wrong stream, and a live log reads as expired —
        exactly the bare-[DONE] regression above, back by another door."""
        events_by_stream = {STREAM_ID: True}

        async def _has_events(stream_id: str) -> bool:
            return events_by_stream.get(stream_id, False)

        with (
            patch(
                "app.api.v1.endpoints.chat.stream_manager.get_progress",
                new=AsyncMock(
                    return_value={"user_id": "507f1f77bcf86cd799439011", "is_complete": True}
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
        # subscribe_stream and the Redis singleton are pinned even though the
        # short-circuit means neither should be reached. That is the point: if
        # the guard ever stops short-circuiting, this test fails on the frames
        # it did not expect, instead of idling on real keepalives until the
        # runner kills it. A wrong branch must be a fast red, not a hang.
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

    @pytest.mark.parametrize("has_events", [True, False])
    async def test_a_live_stream_always_replays_whatever_the_log_says(
        self, client, has_events: bool
    ) -> None:
        """The expired-log short-circuit is gated on completion first. A stream
        still running has more frames coming by definition, so it must be
        followed regardless of what the log lookup answers."""
        with (
            patch(
                "app.api.v1.endpoints.chat.stream_manager.get_progress",
                new=AsyncMock(
                    return_value={"user_id": "507f1f77bcf86cd799439011", "is_complete": False}
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
