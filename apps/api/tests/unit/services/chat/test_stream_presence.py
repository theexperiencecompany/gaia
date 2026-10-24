"""A chat turn the user sent stamps their presence on its surface; agent-driven turns never do."""

import asyncio
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, patch

import pytest

from app.models.chat_models import ConversationSource
from app.models.message_models import MessageRequestWithHistory
from app.models.user_models import AuthenticatedUser
from app.services.chat import stream
from shared.py.analytics.catalog.attribution import Actor, Attribution, EntrySurface, Trigger
from shared.py.analytics.context import AnalyticsContext, analytics_context

USER_ID = "6812f0b3c9a14e2b7d5a91cc"
USER = AuthenticatedUser(user_id=USER_ID, email="tester@example.com")
BODY = MessageRequestWithHistory(
    message="keep me posted",
    messages=[{"role": "user", "content": "keep me posted"}],
    conversation_id="conv-1",
)


def _context(actor: Actor, trigger: Trigger, surface: EntrySurface) -> AnalyticsContext:
    return AnalyticsContext(attribution=Attribution(actor=actor, trigger=trigger, surface=surface))


@pytest.fixture
async def record() -> AsyncIterator[AsyncMock]:
    """Stub the turn and yield the presence-write seam below it."""
    with (
        patch.object(stream, "_run_chat_stream", AsyncMock()),
        patch.object(stream, "record_inbound_activity", AsyncMock()) as seam,
    ):
        yield seam


async def _run_turn(context: AnalyticsContext, source: str | None) -> None:
    with analytics_context(context):
        await stream.run_chat_stream_background(
            stream_id="stream-1", body=BODY, user=USER, conversation_id="conv-1", source=source
        )
    # The write is fire-and-forget: let the spawned task run to completion.
    for _ in range(5):
        await asyncio.sleep(0)


USER_TURN_ON_BOT = _context(Actor.USER, Trigger.INTERACTIVE, EntrySurface.BOT)
USER_TURN_ON_WEB = _context(Actor.USER, Trigger.INTERACTIVE, EntrySurface.WEB)


class TestPresenceIsRecordedForTheUsersOwnTurns:
    async def test_a_telegram_message_stamps_telegram(self, record: AsyncMock) -> None:
        await _run_turn(USER_TURN_ON_BOT, "telegram")

        record.assert_awaited_once_with(USER_ID, ConversationSource.TELEGRAM)

    async def test_a_web_message_stamps_web(self, record: AsyncMock) -> None:
        await _run_turn(USER_TURN_ON_WEB, "web")

        record.assert_awaited_once_with(USER_ID, ConversationSource.WEB)


class TestPresenceIsNotRecordedForAgentWork:
    async def test_an_automatic_client_request_records_nothing(self, record: AsyncMock) -> None:
        await _run_turn(_context(Actor.AGENT, Trigger.SYSTEM, EntrySurface.WEB), "web")

        record.assert_not_called()

    async def test_a_scheduled_turn_records_nothing(self, record: AsyncMock) -> None:
        await _run_turn(_context(Actor.AGENT, Trigger.SCHEDULE, EntrySurface.WORKER), "telegram")

        record.assert_not_called()

    async def test_a_background_source_records_nothing(self, record: AsyncMock) -> None:
        await _run_turn(USER_TURN_ON_WEB, ConversationSource.BACKGROUND.value)

        record.assert_not_called()

    async def test_an_unknown_source_records_nothing(self, record: AsyncMock) -> None:
        await _run_turn(USER_TURN_ON_WEB, None)

        record.assert_not_called()
