"""
Tests for conversation_service.py — the actual business logic.

Mocks at the MongoDB collection boundary so all branching, data
transformation, and error handling inside the service is exercised.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from bson import ObjectId
from fastapi import HTTPException

from tests.conftest import FAKE_USER

COLLECTION = "app.services.conversation_service.conversations_collection"


class TestCreateConversation:
    async def test_inserts_correct_document(self):
        from app.models.chat_models import ConversationModel
        from app.services.conversation_service import create_conversation_service

        conv = ConversationModel(conversation_id="conv_abc")
        mock_insert = AsyncMock(return_value=MagicMock(acknowledged=True))

        with patch(COLLECTION) as mock_col:
            mock_col.insert_one = mock_insert
            result = await create_conversation_service(conv, FAKE_USER)

        # Verify the document inserted has the right structure
        inserted_doc = mock_insert.call_args[0][0]
        assert inserted_doc["user_id"] == FAKE_USER["user_id"]
        assert inserted_doc["conversation_id"] == "conv_abc"
        assert inserted_doc["messages"] == []
        assert inserted_doc["is_system_generated"] is False

        # Verify response
        assert result["conversation_id"] == "conv_abc"
        assert result["user_id"] == FAKE_USER["user_id"]
        assert "createdAt" in result

    async def test_raises_403_when_no_user_id(self):
        from app.models.chat_models import ConversationModel
        from app.services.conversation_service import create_conversation_service

        conv = ConversationModel(conversation_id="conv_abc")
        with pytest.raises(HTTPException) as exc:
            await create_conversation_service(conv, {"email": "no-id@test.com"})
        assert exc.value.status_code == 403

    async def test_raises_500_when_insert_fails(self):
        from app.models.chat_models import ConversationModel
        from app.services.conversation_service import create_conversation_service

        conv = ConversationModel(conversation_id="conv_abc")

        with patch(COLLECTION) as mock_col:
            mock_col.insert_one = AsyncMock(side_effect=Exception("DB down"))
            with pytest.raises(HTTPException) as exc:
                await create_conversation_service(conv, FAKE_USER)
            assert exc.value.status_code == 500

    async def test_raises_500_when_not_acknowledged(self):
        from app.models.chat_models import ConversationModel
        from app.services.conversation_service import create_conversation_service

        conv = ConversationModel(conversation_id="conv_abc")

        with patch(COLLECTION) as mock_col:
            mock_col.insert_one = AsyncMock(return_value=MagicMock(acknowledged=False))
            with pytest.raises(HTTPException) as exc:
                await create_conversation_service(conv, FAKE_USER)
            assert exc.value.status_code == 500


class TestGetConversation:
    async def test_returns_conversation_with_converted_ids(self):
        from app.services.conversation_service import get_conversation

        fake_doc = {
            "_id": ObjectId(),
            "user_id": FAKE_USER["user_id"],
            "conversation_id": "conv_abc",
            "description": "Test chat",
            "messages": [],
        }

        with patch(COLLECTION) as mock_col:
            mock_col.find_one = AsyncMock(return_value=fake_doc)
            result = await get_conversation("conv_abc", FAKE_USER)

        assert result["conversation_id"] == "conv_abc"
        # _id should be converted to string
        assert isinstance(result["_id"], str)

    async def test_raises_404_when_not_found(self):
        from app.services.conversation_service import get_conversation

        with patch(COLLECTION) as mock_col:
            mock_col.find_one = AsyncMock(return_value=None)
            with pytest.raises(HTTPException) as exc:
                await get_conversation("nonexistent", FAKE_USER)
            assert exc.value.status_code == 404


class TestStarConversation:
    async def test_star_success(self):
        from app.services.conversation_service import star_conversation

        with patch(COLLECTION) as mock_col:
            mock_col.update_one = AsyncMock(return_value=MagicMock(modified_count=1))
            result = await star_conversation("conv_abc", True, FAKE_USER)

        assert result["starred"] is True

    async def test_star_not_found(self):
        from app.services.conversation_service import star_conversation

        with patch(COLLECTION) as mock_col:
            mock_col.update_one = AsyncMock(return_value=MagicMock(modified_count=0))
            with pytest.raises(HTTPException) as exc:
                await star_conversation("nonexistent", True, FAKE_USER)
            assert exc.value.status_code == 404


class TestDeleteConversation:
    async def test_delete_single_success(self):
        from app.services.conversation_service import delete_conversation

        with patch(COLLECTION) as mock_col:
            mock_col.delete_one = AsyncMock(return_value=MagicMock(deleted_count=1))
            result = await delete_conversation("conv_abc", FAKE_USER)

        assert result["conversation_id"] == "conv_abc"

    async def test_delete_single_not_found(self):
        from app.services.conversation_service import delete_conversation

        with patch(COLLECTION) as mock_col:
            mock_col.delete_one = AsyncMock(return_value=MagicMock(deleted_count=0))
            with pytest.raises(HTTPException) as exc:
                await delete_conversation("nonexistent", FAKE_USER)
            assert exc.value.status_code == 404

    async def test_delete_all_success(self):
        from app.services.conversation_service import delete_all_conversations

        with patch(COLLECTION) as mock_col:
            mock_col.delete_many = AsyncMock(return_value=MagicMock(deleted_count=3))
            result = await delete_all_conversations(FAKE_USER)

        assert "deleted" in result["message"].lower()

    async def test_delete_all_none_found(self):
        from app.services.conversation_service import delete_all_conversations

        with patch(COLLECTION) as mock_col:
            mock_col.delete_many = AsyncMock(return_value=MagicMock(deleted_count=0))
            with pytest.raises(HTTPException) as exc:
                await delete_all_conversations(FAKE_USER)
            assert exc.value.status_code == 404


class TestUpdateDescription:
    async def test_update_success(self):
        from app.services.conversation_service import update_conversation_description

        with patch(COLLECTION) as mock_col:
            mock_col.update_one = AsyncMock(return_value=MagicMock(modified_count=1))
            result = await update_conversation_description(
                "conv_abc", "New description", FAKE_USER
            )

        assert result["description"] == "New description"

    async def test_update_not_found(self):
        from app.services.conversation_service import update_conversation_description

        with patch(COLLECTION) as mock_col:
            mock_col.update_one = AsyncMock(return_value=MagicMock(modified_count=0))
            with pytest.raises(HTTPException) as exc:
                await update_conversation_description("nonexistent", "desc", FAKE_USER)
            assert exc.value.status_code == 404


class TestMarkReadUnread:
    async def test_mark_as_read(self):
        from app.services.conversation_service import mark_conversation_as_read

        with patch(COLLECTION) as mock_col:
            mock_col.update_one = AsyncMock()
            result = await mark_conversation_as_read("conv_abc", FAKE_USER)

        assert "read" in result["message"].lower()

    async def test_mark_as_read_no_user_id(self):
        from app.services.conversation_service import mark_conversation_as_read

        with pytest.raises(HTTPException) as exc:
            await mark_conversation_as_read("conv_abc", {"email": "no-id@test.com"})
        assert exc.value.status_code == 403

    async def test_mark_as_unread(self):
        from app.services.conversation_service import mark_conversation_as_unread

        with patch(COLLECTION) as mock_col:
            mock_col.update_one = AsyncMock(return_value=MagicMock(modified_count=1))
            result = await mark_conversation_as_unread("conv_abc", FAKE_USER)

        assert "unread" in result["message"].lower()

    async def test_mark_as_unread_not_found(self):
        from app.services.conversation_service import mark_conversation_as_unread

        with patch(COLLECTION) as mock_col:
            mock_col.update_one = AsyncMock(return_value=MagicMock(modified_count=0))
            with pytest.raises(HTTPException) as exc:
                await mark_conversation_as_unread("conv_abc", FAKE_USER)
            assert exc.value.status_code == 404


class TestPinMessage:
    async def test_pin_success(self):
        from app.services.conversation_service import pin_message

        fake_conv = {
            "_id": ObjectId(),
            "messages": [{"message_id": "msg_1", "content": "Hello"}],
        }

        with patch(COLLECTION) as mock_col:
            mock_col.find_one = AsyncMock(return_value=fake_conv)
            mock_col.update_one = AsyncMock(return_value=MagicMock(modified_count=1))
            result = await pin_message("conv_abc", "msg_1", True, FAKE_USER)

        assert result["pinned"] is True

    async def test_pin_conversation_not_found(self):
        from app.services.conversation_service import pin_message

        with patch(COLLECTION) as mock_col:
            mock_col.find_one = AsyncMock(return_value=None)
            with pytest.raises(HTTPException) as exc:
                await pin_message("nonexistent", "msg_1", True, FAKE_USER)
            assert exc.value.status_code == 404

    async def test_pin_message_not_found(self):
        from app.services.conversation_service import pin_message

        fake_conv = {
            "_id": ObjectId(),
            "messages": [{"message_id": "msg_other", "content": "Hello"}],
        }

        with patch(COLLECTION) as mock_col:
            mock_col.find_one = AsyncMock(return_value=fake_conv)
            with pytest.raises(HTTPException) as exc:
                await pin_message("conv_abc", "msg_nonexistent", True, FAKE_USER)
            assert exc.value.status_code == 404
