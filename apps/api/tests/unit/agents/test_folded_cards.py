"""A detached run's cards reach the message they fold into, whichever is saved first.

A fast background job can end before the turn that started it has saved its
message; the cards must not depend on that order. Real code over fakeredis, the
conversation store doubled with Mongo's matched-or-not semantics.
"""

from collections.abc import Mapping, Sequence
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.core.background import folded_stream
from app.constants.cache import FOLDED_CARDS_PREFIX, FOLDED_CARDS_TTL
from app.constants.log_tags import LogTag
from app.db.repositories.conversations import conversation_repository
from app.models.chat_models import MessageModel, SavedSubagentGroup, UpdateMessagesRequest
from app.models.user_models import AuthenticatedUser
from app.services.conversation_service import update_messages
from app.services.folded_cards import fold_waiting_cards
from tests.helpers import captured_wide_event

pytestmark = [pytest.mark.unit, pytest.mark.usefixtures("fake_redis")]

CARD: dict[str, Any] = {"tool_name": "browser_result", "data": {"summary": "Booked."}}


class _Conversation:
    """Saved messages' tool_data; a write onto a message not saved yet matches nothing."""

    def __init__(self) -> None:
        self.tool_data: dict[str, list[dict[str, Any]]] = {}

    async def get_message(
        self, conversation_id: str, message_id: str, *, user_id: str
    ) -> MessageModel | None:
        if message_id not in self.tool_data:
            return None
        return MessageModel(type="bot", response="", tool_data=list(self.tool_data[message_id]))

    async def append_message_tool_data(
        self,
        conversation_id: str,
        *,
        user_id: str,
        message_id: str,
        entries: Sequence[Mapping[str, object]],
    ) -> bool:
        if message_id not in self.tool_data:
            return False
        self.tool_data[message_id].extend(dict(entry) for entry in entries)
        return True

    async def extend_subagent_group(
        self, conversation_id: str, *, user_id: str, message_id: str, group: SavedSubagentGroup
    ) -> bool:
        return False

    async def append_messages(
        self,
        conversation_id: str,
        *,
        user_id: str,
        messages: list[MessageModel],
        max_messages: int | None = None,
    ) -> list[str]:
        for message in messages:
            self.tool_data[str(message.message_id)] = list(message.tool_data or [])
        return [str(message.message_id) for message in messages]


@pytest.fixture
def conversation() -> Any:
    fake = _Conversation()
    with (
        patch.object(conversation_repository, "get_message", fake.get_message),
        patch.object(
            conversation_repository, "append_message_tool_data", fake.append_message_tool_data
        ),
        patch.object(conversation_repository, "extend_subagent_group", fake.extend_subagent_group),
        patch.object(conversation_repository, "append_messages", fake.append_messages),
        patch.object(folded_stream, "close_detached_stream", AsyncMock()),
        patch.object(folded_stream.stream_manager, "is_cancelled", AsyncMock(return_value=False)),
    ):
        yield fake


async def _close_with_cards() -> None:
    with patch.object(folded_stream, "drain_executor_tool_data", return_value=[CARD]):
        await folded_stream.close_folded_stream(
            "stream-1", conversation_id="conv-1", user_id="u1", message_id="msg-1"
        )


async def _save_the_turns_message() -> None:
    bot = MessageModel(type="bot", response="On it.")
    bot.message_id = "msg-1"
    await update_messages(
        UpdateMessagesRequest(conversation_id="conv-1", messages=[bot]),
        user=AuthenticatedUser(user_id="u1"),
    )


@pytest.mark.parametrize("cards_first", [True, False], ids=["job-ends-first", "turn-saves-first"])
async def test_the_cards_land_on_the_message_whichever_is_saved_first(
    conversation: _Conversation, cards_first: bool
) -> None:
    if cards_first:
        await _close_with_cards()
        await _save_the_turns_message()
    else:
        await _save_the_turns_message()
        await _close_with_cards()

    assert conversation.tool_data["msg-1"] == [CARD]


async def test_cards_waiting_for_their_message_are_saved_once(
    conversation: _Conversation,
) -> None:
    await _close_with_cards()
    await _save_the_turns_message()
    await fold_waiting_cards("conv-1", "u1", "msg-1")

    assert conversation.tool_data["msg-1"] == [CARD]


async def test_a_close_that_read_before_the_save_still_lands_its_cards(
    conversation: _Conversation,
) -> None:
    """The close reads "not saved", the turn saves and looks for cards before the close leaves any."""
    real_get = conversation.get_message
    reads: list[str] = []

    async def _read_then_the_turn_saves(
        conversation_id: str, message_id: str, *, user_id: str
    ) -> MessageModel | None:
        reads.append(message_id)
        if len(reads) == 1:
            await _save_the_turns_message()
            return None
        return await real_get(conversation_id, message_id, user_id=user_id)

    with patch.object(conversation_repository, "get_message", _read_then_the_turn_saves):
        await _close_with_cards()

    assert conversation.tool_data["msg-1"] == [CARD]


async def test_every_waiting_card_is_kept_a_day_and_saved_in_order(
    conversation: _Conversation, fake_redis: Any
) -> None:
    cards = [{"tool_name": "step", "data": {"n": n}} for n in range(3)]
    with patch.object(folded_stream, "drain_executor_tool_data", return_value=cards):
        await folded_stream.close_folded_stream(
            "stream-1", conversation_id="conv-1", user_id="u1", message_id="msg-1"
        )
    waiting = f"{FOLDED_CARDS_PREFIX}conv-1:msg-1:cards"
    assert FOLDED_CARDS_TTL - 5 < await fake_redis.ttl(waiting) <= FOLDED_CARDS_TTL

    await _save_the_turns_message()

    assert conversation.tool_data["msg-1"] == cards
    saved_mark = f"{FOLDED_CARDS_PREFIX}conv-1:msg-1:saved"
    assert FOLDED_CARDS_TTL - 5 < await fake_redis.ttl(saved_mark) <= FOLDED_CARDS_TTL
    assert await fake_redis.exists(waiting) == 0


async def test_cards_whose_message_is_gone_when_taken_are_dropped_and_said(
    conversation: _Conversation,
) -> None:
    await _close_with_cards()

    async with captured_wide_event() as event:
        await fold_waiting_cards("conv-1", "u1", "msg-1")

    assert "msg-1" not in conversation.tool_data
    [error] = event["errors"]
    assert error["msg"] == f"{LogTag.AGENT} Detached stream cards matched no message; not saved"
    assert (error["conversation_id"], error["message_id"], error["entries"]) == (
        "conv-1",
        "msg-1",
        1,
    )
