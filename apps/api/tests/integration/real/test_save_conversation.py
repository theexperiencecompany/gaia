"""
Service tests: call real save_user_message() / save_bot_reply() against real MongoDB.

Tests the message construction logic (user content extraction, tool_data
application, message_id assignment) with real MongoDB writes.
"""

from __future__ import annotations

import pytest

from app.models.message_models import MessageRequestWithHistory
from app.services.chat.persistence import save_bot_reply, save_user_message
from tests.factories import make_authenticated_user


@pytest.mark.service
class TestSaveTurnReal:
    """Call the real turn writers against real MongoDB."""

    async def test_user_content_from_last_message(
        self, real_redis, conversations_collection, make_conversation
    ):
        """User content must come from body.messages[-1], not [0]."""
        conv_id = await make_conversation("save-user-1")

        body = MessageRequestWithHistory(
            message="Fallback text",
            messages=[
                {"role": "user", "content": "First turn"},
                {"role": "user", "content": "Last turn"},
            ],
            conversation_id=conv_id,
        )

        await save_user_message(
            body, make_authenticated_user(user_id="save-user-1"), conv_id, "umsg_1"
        )

        doc = await conversations_collection.find_one({"conversation_id": conv_id})
        user_msg = doc["messages"][0]
        assert user_msg["response"] == "Last turn", (
            "Must use body.messages[-1], not body.messages[0]"
        )

    async def test_user_content_falls_back_to_body_message(
        self, real_redis, conversations_collection, make_conversation
    ):
        """When messages is empty, user content must fall back to body.message."""
        conv_id = await make_conversation("save-user-2")

        body = MessageRequestWithHistory(
            message="Fallback content",
            messages=[],
            conversation_id=conv_id,
        )

        await save_user_message(body, make_authenticated_user(user_id="save-user-2"), conv_id, "u1")

        doc = await conversations_collection.find_one({"conversation_id": conv_id})
        assert doc["messages"][0]["response"] == "Fallback content"

    async def test_message_ids_applied_in_turn_order(
        self, real_redis, conversations_collection, make_conversation
    ):
        """Provided message_ids must appear on saved messages, user before reply."""
        conv_id = await make_conversation("save-user-3")
        user = make_authenticated_user(user_id="save-user-3")

        body = MessageRequestWithHistory(
            message="Hello",
            messages=[{"role": "user", "content": "Hello"}],
            conversation_id=conv_id,
        )

        await save_user_message(body, user, conv_id, "specific-umsg")
        await save_bot_reply(
            body=body,
            user=user,
            conversation_id=conv_id,
            complete_message="Hi",
            tool_data={},
            metadata={},
            bot_message_id="specific-bmsg",
        )

        doc = await conversations_collection.find_one({"conversation_id": conv_id})
        assert [m["message_id"] for m in doc["messages"]] == ["specific-umsg", "specific-bmsg"]

    async def test_tool_data_applied_to_bot_message(
        self, real_redis, conversations_collection, make_conversation
    ):
        """tool_data dict entries must be set as attributes on bot message."""
        conv_id = await make_conversation("save-user-4")

        body = MessageRequestWithHistory(
            message="Search",
            messages=[{"role": "user", "content": "Search"}],
            conversation_id=conv_id,
        )

        tool_data = {
            "tool_data": [{"tool_name": "web_search", "data": {"query": "cats"}, "timestamp": "t"}]
        }

        await save_bot_reply(
            body=body,
            user=make_authenticated_user(user_id="save-user-4"),
            conversation_id=conv_id,
            complete_message="Results",
            tool_data=tool_data,
            metadata={},
            bot_message_id="b",
        )

        doc = await conversations_collection.find_one({"conversation_id": conv_id})
        bot_msg = doc["messages"][0]
        assert bot_msg["tool_data"][0]["tool_name"] == "web_search"
