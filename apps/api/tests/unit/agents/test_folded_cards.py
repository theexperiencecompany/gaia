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
from app.db.repositories.conversations import conversation_repository
from app.models.chat_models import MessageModel, SavedSubagentGroup, UpdateMessagesRequest
from app.models.user_models import AuthenticatedUser
from app.services.conversation_service import update_messages
from app.services.folded_cards import fold_waiting_cards

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
