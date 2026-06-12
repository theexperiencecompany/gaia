"""Unit tests for background-executor message delivery routing.

The key invariant: a background result is delivered over EXACTLY ONE transport,
chosen by the conversation's own source — bot conversations to their platform,
everything else over WebSocket — and the message is always persisted.
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.agents.core.background import result_delivery as rd
from app.agents.core.background.session import ExecutorRun, RunKind
from app.models.chat_models import ConversationSource


def _run() -> ExecutorRun:
    """A live (non-queued, non-workflow) run context for delivery tests."""
    return ExecutorRun(
        stream_id="",
        conversation_id="conv-1",
        user={"user_id": "user-1"},
        kind=RunKind.LIVE,
        task_id=None,
        user_message_id=None,
    )


async def _deliver(conv_source, *, comms_text="result text", result_text="raw"):
    """Run deliver_result with all I/O boundaries mocked.

    Returns (save_mock, platform_mock, ws_mock) for assertions. The real
    is_bot_platform routing logic runs unmocked against ``conv_source``.
    """
    with (
        patch.object(
            rd, "narrate_executor_result", new_callable=AsyncMock, return_value=comms_text
        ),
        patch.object(rd, "generate_follow_up_actions", new_callable=AsyncMock, return_value=[]),
        patch.object(rd, "update_messages", new_callable=AsyncMock) as save,
        patch.object(
            rd, "_get_conversation_source", new_callable=AsyncMock, return_value=conv_source
        ),
        patch.object(
            rd, "deliver_message_to_platform", new_callable=AsyncMock, return_value=True
        ) as platform,
        patch.object(rd, "_broadcast_message", new_callable=AsyncMock) as ws,
    ):
        await rd.deliver_result(
            _run(),
            result_text=result_text,
            result_type="final",
        )
    return save, platform, ws


@pytest.mark.unit
class TestDeliverResultRouting:
    @pytest.mark.parametrize(
        "src",
        [
            ConversationSource.WHATSAPP,
            ConversationSource.SLACK,
            ConversationSource.DISCORD,
            ConversationSource.TELEGRAM,
        ],
    )
    async def test_bot_conversation_delivers_to_platform_only(self, src) -> None:
        save, platform, ws = await _deliver(src)

        platform.assert_awaited_once()
        assert platform.await_args.args[0] == src  # routed to the conversation's platform
        assert platform.await_args.args[2] == "result text"  # the comms-generated text
        ws.assert_not_awaited()  # exclusive: no WebSocket fan-out for bots
        save.assert_awaited_once()  # always persisted to history

    @pytest.mark.parametrize("src", [ConversationSource.WEB, ConversationSource.MOBILE, None])
    async def test_non_bot_conversation_broadcasts_over_websocket_only(self, src) -> None:
        save, platform, ws = await _deliver(src)

        ws.assert_awaited_once()
        platform.assert_not_awaited()  # exclusive: no platform send for web/mobile/system
        save.assert_awaited_once()

    async def test_websocket_payload_carries_conversation_and_message(self) -> None:
        _save, _platform, ws = await _deliver(ConversationSource.WEB)
        event = ws.await_args.args[1]
        assert event["type"] == "conversation.new_message"
        assert event["conversation_id"] == "conv-1"
        assert event["message"]["response"] == "result text"

    async def test_falls_back_to_raw_executor_text_when_comms_unavailable(self) -> None:
        # comms returns "" → the raw executor text must still be delivered.
        _save, platform, _ws = await _deliver(
            ConversationSource.WHATSAPP, comms_text="", result_text="raw executor output"
        )
        assert platform.await_args.args[2] == "raw executor output"


@pytest.mark.unit
class TestGetConversationSource:
    """The authoritative routing key: the conversation's persisted source."""

    async def test_returns_coerced_enum_from_stored_string(self) -> None:
        with patch.object(rd, "conversations_collection") as col:
            col.find_one = AsyncMock(return_value={"source": "whatsapp"})
            src = await rd._get_conversation_source("conv-1", "user-1")
        assert src is ConversationSource.WHATSAPP  # coerced to the enum, not a raw str

    async def test_query_is_scoped_to_conversation_and_owner(self) -> None:
        with patch.object(rd, "conversations_collection") as col:
            col.find_one = AsyncMock(return_value={"source": "web"})
            await rd._get_conversation_source("conv-1", "user-1")
        # must be scoped by BOTH conversation_id and user_id (no cross-user read)
        assert col.find_one.await_args.args[0] == {
            "conversation_id": "conv-1",
            "user_id": "user-1",
        }

    async def test_missing_conversation_returns_none(self) -> None:
        with patch.object(rd, "conversations_collection") as col:
            col.find_one = AsyncMock(return_value=None)
            assert await rd._get_conversation_source("conv-1", "user-1") is None

    async def test_unknown_stored_value_coerces_to_none(self) -> None:
        with patch.object(rd, "conversations_collection") as col:
            col.find_one = AsyncMock(return_value={"source": "legacy_garbage"})
            assert await rd._get_conversation_source("conv-1", "user-1") is None

    async def test_db_error_returns_none(self) -> None:
        with patch.object(rd, "conversations_collection") as col:
            col.find_one = AsyncMock(side_effect=RuntimeError("mongo down"))
            assert await rd._get_conversation_source("conv-1", "user-1") is None
