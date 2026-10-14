"""POST /chat-stream runs a turn only in a conversation the caller owns, checked against real MongoDB."""

from __future__ import annotations

from collections.abc import AsyncGenerator, Iterator
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import AsyncClient
import pytest

from tests.conftest import FAKE_USER, FAKE_USER_2

pytestmark = pytest.mark.service


async def _no_frames(*_: object, **__: object) -> AsyncGenerator[str, None]:
    return
    yield  # pragma: no cover


@pytest.fixture
def turn_runner() -> Iterator[AsyncMock]:
    """Clear the rate and cost gates and stand in for the background run the route spawns."""
    run = AsyncMock()
    with (
        patch(
            "app.api.v1.middleware.tiered_rate_limiter.tiered_limiter.check_and_increment",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch("app.api.v1.endpoints.chat.enforce_daily_cost_budget", new_callable=AsyncMock),
        patch("app.api.v1.endpoints.chat.stream_manager.start_stream", new_callable=AsyncMock),
        patch("app.api.v1.endpoints.chat.stream_manager.subscribe_stream", new=_no_frames),
        patch("app.api.v1.endpoints.chat.redis_cache.redis", new=MagicMock()),
        patch("app.api.v1.endpoints.chat.run_chat_stream_background", new=run),
        patch(
            "app.api.v1.endpoints.chat.spawn_background_task",
            side_effect=lambda coro, **_: coro.close(),
        ),
        patch("app.api.v1.endpoints.chat.capture"),
    ):
        yield run


def _turn(conversation_id: str | None) -> dict[str, object]:
    return {"message": "hi", "messages": [], "conversation_id": conversation_id}


class TestChatStreamConversationOwnership:
    async def test_a_turn_in_your_own_conversation_runs(
        self, client: AsyncClient, turn_runner: AsyncMock, make_conversation
    ) -> None:
        conversation_id = await make_conversation(FAKE_USER.user_id)

        response = await client.post("/api/v1/chat-stream", json=_turn(conversation_id))

        assert response.status_code == 200, response.text
        assert turn_runner.call_args.kwargs["conversation_id"] == conversation_id

    async def test_a_new_conversation_runs_under_a_server_minted_id(
        self, client: AsyncClient, turn_runner: AsyncMock, conversations_collection
    ) -> None:
        response = await client.post("/api/v1/chat-stream", json=_turn(None))

        assert response.status_code == 200, response.text
        assert turn_runner.call_args.kwargs["conversation_id"]

    async def test_a_conversation_that_does_not_exist_is_not_found(
        self, client: AsyncClient, turn_runner: AsyncMock, conversations_collection
    ) -> None:
        response = await client.post("/api/v1/chat-stream", json=_turn("conv_never_created"))

        assert response.status_code == 404
        assert response.json()["code"] == "CONVERSATION_NOT_FOUND"
        turn_runner.assert_not_called()

    async def test_another_users_conversation_is_indistinguishable_from_a_missing_one(
        self, client: AsyncClient, turn_runner: AsyncMock, make_conversation
    ) -> None:
        foreign_id = await make_conversation(FAKE_USER_2.user_id)

        foreign = await client.post("/api/v1/chat-stream", json=_turn(foreign_id))
        missing = await client.post("/api/v1/chat-stream", json=_turn("conv_never_created"))

        assert foreign.status_code == 404
        assert foreign.json() == missing.json()
        turn_runner.assert_not_called()
