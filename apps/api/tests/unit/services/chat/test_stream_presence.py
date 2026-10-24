"""A chat turn the user sent stamps their presence on its surface and hands the run the state before it; agent-driven turns never do."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from unittest.mock import AsyncMock, patch

import pytest

from app.models.chat_models import ConversationSource
from app.models.message_models import MessageRequestWithHistory
from app.models.presence_models import PresenceSnapshot
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
BEFORE_THIS_TURN: PresenceSnapshot = {"captured_at": 1_800_000_000, "last_seen": {"web": 1}}


def _context(actor: Actor, trigger: Trigger, surface: EntrySurface) -> AnalyticsContext:
    return AnalyticsContext(attribution=Attribution(actor=actor, trigger=trigger, surface=surface))


@dataclass(frozen=True)
class _Seams:
    record: AsyncMock
    run: AsyncMock


@pytest.fixture
async def seams() -> AsyncIterator[_Seams]:
    """Stub the turn and the presence write below it."""
    with (
        patch.object(stream, "_run_chat_stream", AsyncMock()) as run,
        patch.object(
            stream, "record_turn_presence", AsyncMock(return_value=BEFORE_THIS_TURN)
        ) as record,
    ):
        yield _Seams(record=record, run=run)


async def _run_turn(context: AnalyticsContext, source: str | None) -> None:
    with analytics_context(context):
        await stream.run_chat_stream_background(
            stream_id="stream-1", body=BODY, user=USER, conversation_id="conv-1", source=source
        )


USER_TURN_ON_BOT = _context(Actor.USER, Trigger.INTERACTIVE, EntrySurface.BOT)
USER_TURN_ON_WEB = _context(Actor.USER, Trigger.INTERACTIVE, EntrySurface.WEB)


class TestPresenceIsRecordedForTheUsersOwnTurns:
    async def test_a_telegram_message_stamps_telegram(self, seams: _Seams) -> None:
        await _run_turn(USER_TURN_ON_BOT, "telegram")

        seams.record.assert_awaited_once_with(USER_ID, ConversationSource.TELEGRAM)

    async def test_a_web_message_stamps_web(self, seams: _Seams) -> None:
        await _run_turn(USER_TURN_ON_WEB, "web")

        seams.record.assert_awaited_once_with(USER_ID, ConversationSource.WEB)

    async def test_the_run_gets_the_state_before_this_turn(self, seams: _Seams) -> None:
        await _run_turn(USER_TURN_ON_BOT, "telegram")

        assert seams.run.await_args.kwargs["presence"] == BEFORE_THIS_TURN

    async def test_a_failed_presence_write_fails_the_turn(self, seams: _Seams) -> None:
        """Not swallowed: the turn depends on Redis anyway, and a silent miss would hide where the user is."""
        seams.record.side_effect = ConnectionError("redis down")

        with pytest.raises(ConnectionError):
            await _run_turn(USER_TURN_ON_BOT, "telegram")

        seams.run.assert_not_awaited()


class TestPresenceIsNotRecordedForAgentWork:
    @pytest.mark.parametrize(
        ("context", "source"),
        [
            (_context(Actor.AGENT, Trigger.SYSTEM, EntrySurface.WEB), "web"),
            (_context(Actor.AGENT, Trigger.SCHEDULE, EntrySurface.WORKER), "telegram"),
            (USER_TURN_ON_WEB, ConversationSource.BACKGROUND.value),
            (USER_TURN_ON_WEB, None),
        ],
        ids=["automatic_client_request", "scheduled_turn", "background_source", "unknown_source"],
    )
    async def test_records_nothing_and_passes_no_presence(
        self, seams: _Seams, context: AnalyticsContext, source: str | None
    ) -> None:
        await _run_turn(context, source)

        seams.record.assert_not_called()
        assert seams.run.await_args.kwargs["presence"] is None
