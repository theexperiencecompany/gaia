"""
Service tests: call the real update_messages() against real MongoDB.

The conftest patches conversations_collection to a real Motor collection,
so update_messages() runs its actual code path unmodified.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from app.models.chat_models import MessageModel, UpdateMessagesRequest
from app.services.conversation_service import update_messages


@pytest.mark.service
class TestUpdateMessagesReal:
    """Call the real update_messages() against real MongoDB."""

    async def test_messages_persisted(
        self, conversations_collection, make_conversation
    ):
        """update_messages must $push user+bot messages to real MongoDB."""
        user = {"user_id": "user-1"}
        conv_id = await make_conversation("user-1")

        request = UpdateMessagesRequest(
            conversation_id=conv_id,
            messages=[
                MessageModel(
                    type="user",
                    response="Hello GAIA",
                    date=datetime.now(timezone.utc).isoformat(),
                ),
                MessageModel(
                    type="bot",
                    response="Hello! How can I help?",
                    date=datetime.now(timezone.utc).isoformat(),
                ),
            ],
        )

        result = await update_messages(request, user)

        assert result["modified_count"] == 1
        assert len(result["message_ids"]) == 2

        doc = await conversations_collection.find_one({"conversation_id": conv_id})
        assert len(doc["messages"]) == 2
        assert doc["messages"][0]["type"] == "user"
        assert doc["messages"][0]["response"] == "Hello GAIA"
        assert doc["messages"][1]["type"] == "bot"
        assert doc["messages"][1]["response"] == "Hello! How can I help?"
        assert doc["messages"][0]["message_id"]
        assert doc["messages"][1]["message_id"]
        assert doc["updatedAt"]

    async def test_nonexistent_conversation_raises_404(self, conversations_collection):
        """update_messages must raise HTTPException(404) for missing conversations."""
        request = UpdateMessagesRequest(
            conversation_id="nonexistent",
            messages=[
                MessageModel(
                    type="bot",
                    response="Ghost",
                    date=datetime.now(timezone.utc).isoformat(),
                ),
            ],
        )

        with pytest.raises(HTTPException) as exc_info:
            await update_messages(request, {"user_id": "no-one"})

        assert exc_info.value.status_code == 404

    async def test_tool_data_survives_roundtrip(
        self, conversations_collection, make_conversation
    ):
        """tool_data on a bot message must survive MongoDB serialization."""
        user = {"user_id": "user-2"}
        conv_id = await make_conversation("user-2")

        request = UpdateMessagesRequest(
            conversation_id=conv_id,
            messages=[
                MessageModel(
                    type="bot",
                    response="Here are results",
                    date=datetime.now(timezone.utc).isoformat(),
                    tool_data=[
                        {
                            "tool_name": "search_results",
                            "data": {"items": ["a", "b"]},
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        }
                    ],
                ),
            ],
        )

        await update_messages(request, user)

        doc = await conversations_collection.find_one({"conversation_id": conv_id})
        saved = doc["messages"][0]
        assert saved["tool_data"][0]["tool_name"] == "search_results"
        assert saved["tool_data"][0]["data"]["items"] == ["a", "b"]

    async def test_consecutive_updates_append(
        self, conversations_collection, make_conversation
    ):
        """Multiple update_messages calls must append, not overwrite."""
        user = {"user_id": "user-3"}
        conv_id = await make_conversation("user-3")

        for i in range(3):
            request = UpdateMessagesRequest(
                conversation_id=conv_id,
                messages=[
                    MessageModel(
                        type="bot",
                        response=f"Message {i}",
                        date=datetime.now(timezone.utc).isoformat(),
                    ),
                ],
            )
            await update_messages(request, user)

        doc = await conversations_collection.find_one({"conversation_id": conv_id})
        assert len(doc["messages"]) == 3
        assert doc["messages"][0]["response"] == "Message 0"
        assert doc["messages"][2]["response"] == "Message 2"

    async def test_user_isolation(self, conversations_collection, make_conversation):
        """User A's update must not touch User B's conversation."""
        conv_id = await make_conversation("user-A")

        request = UpdateMessagesRequest(
            conversation_id=conv_id,
            messages=[
                MessageModel(
                    type="bot",
                    response="From B",
                    date=datetime.now(timezone.utc).isoformat(),
                ),
            ],
        )

        with pytest.raises(HTTPException) as exc_info:
            await update_messages(request, {"user_id": "user-B"})

        assert exc_info.value.status_code == 404
