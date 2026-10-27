"""A chat turn the user sent stamps their presence on its surface and hands the run the state before it; agent-driven and voice turns never do."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from unittest.mock import AsyncMock, patch

import pytest

from app.models.chat_models import ConversationSource
from app.models.message_models import MessageRequestWithHistory
from app.models.presence_models import PresenceSnapshot
from app.models.user_models import AuthenticatedUser
from app.services.chat import stream
from app.services.chat.stream import _TurnContext
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
    consume: AsyncMock
    publish_init: AsyncMock
    handle_error: AsyncMock
    finalize: AsyncMock

    @property
    def presence_the_run_got(self) -> PresenceSnapshot | None:
        turn: _TurnContext = self.consume.await_args.args[2]
        return turn.presence


@pytest.fixture
async def seams() -> AsyncIterator[_Seams]:
    """Run the real stream orchestrator with the presence write and everything past it stubbed."""
    with (
        patch.object(
            stream, "record_turn_presence", AsyncMock(return_value=BEFORE_THIS_TURN)
        ) as record,
        patch.object(stream, "stream_manager", AsyncMock()),
        patch.object(stream, "register_executor_capture"),
        patch.object(stream, "_set_stream_log_context"),
        patch.object(stream, "_publish_init_chunk", AsyncMock()) as publish_init,
        patch.object(stream, "_resolve_pending_approval_turn", AsyncMock(return_value=False)),
        patch.object(stream, "schedule_last_active_touch"),
        patch.object(stream, "forward_artifact_events", AsyncMock()),
        patch.object(stream, "_start_description_task", return_value=None),
        patch.object(stream, "_consume_agent_stream", AsyncMock(return_value=None)) as consume,
        patch.object(stream, "_log_usage_summary"),
        patch.object(stream, "_persist_turn", AsyncMock()),
        patch.object(stream, "_attach_executor_tool_data", AsyncMock()),
        patch.object(stream, "_note_cancellation", AsyncMock()),
        patch.object(stream, "_finalize_description", AsyncMock()),
        patch.object(stream, "capture"),
        patch.object(stream, "_handle_stream_error", AsyncMock(return_value="failed")) as handled,
        patch.object(stream, "_close_turn_timings"),
        patch.object(stream, "_finalize_stream", AsyncMock()) as finalize,
    ):
        yield _Seams(
            record=record,
            consume=consume,
            publish_init=publish_init,
            handle_error=handled,
            finalize=finalize,
        )


async def _run_turn(context: AnalyticsContext, source: str | None) -> None:
    with analytics_context(context):
        await stream.run_chat_stream_background(
            stream_id="stream-1", body=BODY, user=USER, conversation_id="conv-1", source=source
        )


USER_TURN_ON_BOT = _context(Actor.USER, Trigger.INTERACTIVE, EntrySurface.BOT)
USER_TURN_ON_WEB = _context(Actor.USER, Trigger.INTERACTIVE, EntrySurface.WEB)
USER_TURN_ON_VOICE = _context(Actor.USER, Trigger.INTERACTIVE, EntrySurface.VOICE)


class TestPresenceIsRecordedForTheUsersOwnTurns:
    async def test_a_telegram_message_stamps_telegram(self, seams: _Seams) -> None:
        await _run_turn(USER_TURN_ON_BOT, "telegram")

        seams.record.assert_awaited_once_with(USER_ID, ConversationSource.TELEGRAM)

    async def test_a_web_message_stamps_web(self, seams: _Seams) -> None:
        await _run_turn(USER_TURN_ON_WEB, "web")

        seams.record.assert_awaited_once_with(USER_ID, ConversationSource.WEB)

    async def test_the_run_gets_the_state_before_this_turn(self, seams: _Seams) -> None:
        await _run_turn(USER_TURN_ON_BOT, "telegram")

        assert seams.presence_the_run_got == BEFORE_THIS_TURN


class TestAFailedPresenceWriteTakesTheStreamsErrorPath:
    async def test_it_publishes_the_error_and_finalizes_without_starting_the_turn(
        self, seams: _Seams
    ) -> None:
        """Not swallowed and not silent: the client gets the error frame and the stream is closed."""
        failure = ConnectionError("redis down")
        seams.record.side_effect = failure

        await _run_turn(USER_TURN_ON_BOT, "telegram")

        seams.handle_error.assert_awaited_once_with("stream-1", failure)
        seams.finalize.assert_awaited_once()
        seams.publish_init.assert_not_awaited()
        seams.consume.assert_not_awaited()


class TestPresenceIsNotRecordedForAgentWork:
    @pytest.mark.parametrize(
        ("context", "source"),
        [
            (_context(Actor.AGENT, Trigger.SYSTEM, EntrySurface.WEB), "web"),
            (_context(Actor.AGENT, Trigger.SCHEDULE, EntrySurface.WORKER), "telegram"),
            (USER_TURN_ON_WEB, ConversationSource.BACKGROUND.value),
            (USER_TURN_ON_WEB, None),
            (_context(Actor.USER, Trigger.SCHEDULE, EntrySurface.WEB), "web"),
            (_context(Actor.AGENT, Trigger.INTERACTIVE, EntrySurface.WEB), "web"),
        ],
        ids=[
            "automatic_client_request",
            "scheduled_turn",
            "background_source",
            "unknown_source",
            "user_actor_on_a_schedule",
            "agent_actor_on_an_interactive_trigger",
        ],
    )
    async def test_records_nothing_and_passes_no_presence(
        self, seams: _Seams, context: AnalyticsContext, source: str | None
    ) -> None:
        await _run_turn(context, source)

        seams.record.assert_not_called()
        assert seams.presence_the_run_got is None


class TestAVoiceCallIsNotASurfaceTheUserTypesOn:
    async def test_a_voice_turn_arriving_as_web_records_nothing(self, seams: _Seams) -> None:
        """The voice worker sends no client type, so its turns read as web; the entry surface says otherwise."""
        await _run_turn(USER_TURN_ON_VOICE, "web")

        seams.record.assert_not_called()
        assert seams.presence_the_run_got is None
