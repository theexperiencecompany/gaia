"""
Service tests: call real _save_conversation_async() against real MongoDB.

Tests the message construction logic (user content extraction, tool_data
application, message_id assignment) with real MongoDB writes.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.models.message_models import MessageRequestWithHistory
from app.services.chat_service import _save_conversation_async


@pytest.mark.service
class TestSaveConversationAsyncReal:
    """Call real _save_conversation_async against real MongoDB."""

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

        with patch(
            "app.services.chat_service._process_token_usage_and_cost",
            new=AsyncMock(),
        ):
            await _save_conversation_async(
                body=body,
                user={"user_id": "save-user-1"},
                conversation_id=conv_id,
                complete_message="Bot response",
                tool_data={},
                metadata={},
                user_message_id="umsg_1",
                bot_message_id="bmsg_1",
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

        with patch(
            "app.services.chat_service._process_token_usage_and_cost",
            new=AsyncMock(),
        ):
            await _save_conversation_async(
                body=body,
                user={"user_id": "save-user-2"},
                conversation_id=conv_id,
                complete_message="Response",
                tool_data={},
                metadata={},
                user_message_id="u1",
                bot_message_id="b1",
            )

        doc = await conversations_collection.find_one({"conversation_id": conv_id})
        assert doc["messages"][0]["response"] == "Fallback content"

    async def test_message_ids_applied(
        self, real_redis, conversations_collection, make_conversation
    ):
        """Provided message_ids must appear on saved messages."""
        conv_id = await make_conversation("save-user-3")

        body = MessageRequestWithHistory(
            message="Hello",
            messages=[{"role": "user", "content": "Hello"}],
            conversation_id=conv_id,
        )

        with patch(
            "app.services.chat_service._process_token_usage_and_cost",
            new=AsyncMock(),
        ):
            await _save_conversation_async(
                body=body,
                user={"user_id": "save-user-3"},
                conversation_id=conv_id,
                complete_message="Hi",
                tool_data={},
                metadata={},
                user_message_id="specific-umsg",
                bot_message_id="specific-bmsg",
            )

        doc = await conversations_collection.find_one({"conversation_id": conv_id})
        assert doc["messages"][0]["message_id"] == "specific-umsg"
        assert doc["messages"][1]["message_id"] == "specific-bmsg"

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
            "tool_data": [
                {"tool_name": "web_search", "data": {"query": "cats"}, "timestamp": "t"}
            ]
        }

        with patch(
            "app.services.chat_service._process_token_usage_and_cost",
            new=AsyncMock(),
        ):
            await _save_conversation_async(
                body=body,
                user={"user_id": "save-user-4"},
                conversation_id=conv_id,
                complete_message="Results",
                tool_data=tool_data,
                metadata={},
                user_message_id="u",
                bot_message_id="b",
            )

        doc = await conversations_collection.find_one({"conversation_id": conv_id})
        bot_msg = doc["messages"][1]
        assert bot_msg["tool_data"][0]["tool_name"] == "web_search"

    async def test_token_processing_failure_does_not_block_save(
        self, real_redis, conversations_collection, make_conversation
    ):
        """If _process_token_usage_and_cost raises, messages must still save."""
        conv_id = await make_conversation("save-user-5")

        body = MessageRequestWithHistory(
            message="Hello",
            messages=[{"role": "user", "content": "Hello"}],
            conversation_id=conv_id,
        )

        with patch(
            "app.services.chat_service._process_token_usage_and_cost",
            new=AsyncMock(side_effect=Exception("payment service down")),
        ):
            await _save_conversation_async(
                body=body,
                user={"user_id": "save-user-5"},
                conversation_id=conv_id,
                complete_message="Hi",
                tool_data={},
                metadata={"model": {"input_tokens": 10}},
                user_message_id="u",
                bot_message_id="b",
            )

        doc = await conversations_collection.find_one({"conversation_id": conv_id})
        assert len(doc["messages"]) == 2, (
            "Messages must save even if token processing fails"
        )
