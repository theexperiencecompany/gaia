"""
Service tests: call real create_conversation() against real MongoDB.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.utils.chat_utils import create_conversation


@pytest.mark.service
class TestCreateConversationReal:
    """Call real create_conversation against real MongoDB."""

    async def test_creates_document_in_mongodb(
        self, real_redis, conversations_collection
    ):
        """create_conversation must insert a document retrievable by conversation_id."""
        with patch(
            "app.utils.chat_utils._generate_description_from_message",
            new=AsyncMock(return_value="Test description"),
        ):
            result = await create_conversation(
                {"role": "user", "content": "Hello world"},
                user={"user_id": "create-user-1"},
                selectedTool=None,
                generate_description=False,
            )

        assert "conversation_id" in result
        conv_id = result["conversation_id"]

        doc = await conversations_collection.find_one({"conversation_id": conv_id})
        assert doc is not None
        assert doc["user_id"] == "create-user-1"

    async def test_conversation_id_is_unique(
        self, real_redis, conversations_collection
    ):
        """Each call must generate a unique conversation_id."""
        with patch(
            "app.utils.chat_utils._generate_description_from_message",
            new=AsyncMock(return_value="Desc"),
        ):
            r1 = await create_conversation(
                {"role": "user", "content": "First"},
                user={"user_id": "create-user-2"},
                selectedTool=None,
                generate_description=False,
            )
            r2 = await create_conversation(
                {"role": "user", "content": "Second"},
                user={"user_id": "create-user-2"},
                selectedTool=None,
                generate_description=False,
            )

        assert r1["conversation_id"] != r2["conversation_id"]
