"""Unit tests for conversation service CRUD operations."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

from bson import ObjectId
from fastapi import HTTPException

from app.models.chat_models import ConversationModel, SystemPurpose
from app.services.conversation_service import (
    _convert_datetime_to_iso,
    _convert_ids,
    create_conversation_service,
    delete_conversation,
    delete_all_conversations,
    get_conversation,
    mark_conversation_as_read,
    mark_conversation_as_unread,
    star_conversation,
    update_conversation_description,
)


@pytest.fixture
def mock_collection():
    """Provide a mocked conversations_collection."""
    with patch(
        "app.services.conversation_service.conversations_collection"
    ) as mock_col:
        yield mock_col


@pytest.fixture
def test_user():
    return {"user_id": "user_123", "email": "test@example.com"}


@pytest.mark.unit
class TestCreateConversationService:
    async def test_creates_conversation_with_correct_data(
        self, mock_collection, test_user
    ):
        mock_result = MagicMock()
        mock_result.acknowledged = True
        mock_collection.insert_one = AsyncMock(return_value=mock_result)

        conversation = ConversationModel(
            conversation_id="conv_abc",
            description="Test Chat",
        )

        result = await create_conversation_service(conversation, test_user)

        assert result["conversation_id"] == "conv_abc"
        assert result["user_id"] == "user_123"
        assert result["detail"] == "Conversation created successfully"

        call_args = mock_collection.insert_one.call_args[0][0]
        assert call_args["user_id"] == "user_123"
        assert call_args["conversation_id"] == "conv_abc"
        assert call_args["description"] == "Test Chat"
        assert call_args["messages"] == []

    async def test_raises_403_when_no_user_id(self, mock_collection):
        conversation = ConversationModel(
            conversation_id="conv_abc",
            description="Test",
        )

        with pytest.raises(HTTPException) as exc_info:
            await create_conversation_service(conversation, {})

        assert exc_info.value.status_code == 403

    async def test_raises_500_on_insert_failure(self, mock_collection, test_user):
        mock_result = MagicMock()
        mock_result.acknowledged = False
        mock_collection.insert_one = AsyncMock(return_value=mock_result)

        conversation = ConversationModel(
            conversation_id="conv_abc",
            description="Test",
        )

        with pytest.raises(HTTPException) as exc_info:
            await create_conversation_service(conversation, test_user)

        assert exc_info.value.status_code == 500

    async def test_raises_500_on_exception(self, mock_collection, test_user):
        mock_collection.insert_one = AsyncMock(
            side_effect=Exception("DB connection failed")
        )

        conversation = ConversationModel(
            conversation_id="conv_abc",
            description="Test",
        )

        with pytest.raises(HTTPException) as exc_info:
            await create_conversation_service(conversation, test_user)

        assert exc_info.value.status_code == 500

    async def test_system_generated_fields(self, mock_collection, test_user):
        mock_result = MagicMock()
        mock_result.acknowledged = True
        mock_collection.insert_one = AsyncMock(return_value=mock_result)

        conversation = ConversationModel(
            conversation_id="conv_sys",
            description="System Chat",
            is_system_generated=True,
            system_purpose=SystemPurpose.EMAIL_PROCESSING,
            is_unread=True,
        )

        await create_conversation_service(conversation, test_user)

        call_args = mock_collection.insert_one.call_args[0][0]
        assert call_args["is_system_generated"] is True
        assert call_args["system_purpose"] == SystemPurpose.EMAIL_PROCESSING
        assert call_args["is_unread"] is True


@pytest.mark.unit
class TestGetConversation:
    async def test_returns_conversation(self, mock_collection, test_user):
        mock_doc = {
            "_id": ObjectId(),
            "user_id": "user_123",
            "conversation_id": "conv_abc",
            "description": "Test",
            "messages": [],
        }
        mock_collection.find_one = AsyncMock(return_value=mock_doc)

        with patch(
            "app.services.conversation_service.convert_conversation_messages",
            side_effect=lambda x: x,
        ):
            result = await get_conversation("conv_abc", test_user)

        assert result["conversation_id"] == "conv_abc"
        assert isinstance(result["_id"], str)

    async def test_raises_404_when_not_found(self, mock_collection, test_user):
        mock_collection.find_one = AsyncMock(return_value=None)

        with pytest.raises(HTTPException) as exc_info:
            await get_conversation("nonexistent", test_user)

        assert exc_info.value.status_code == 404


@pytest.mark.unit
class TestStarConversation:
    async def test_stars_conversation(self, mock_collection, test_user):
        mock_result = MagicMock()
        mock_result.modified_count = 1
        mock_collection.update_one = AsyncMock(return_value=mock_result)

        result = await star_conversation("conv_abc", True, test_user)

        assert result["starred"] is True

    async def test_raises_404_when_not_found(self, mock_collection, test_user):
        mock_result = MagicMock()
        mock_result.modified_count = 0
        mock_collection.update_one = AsyncMock(return_value=mock_result)

        with pytest.raises(HTTPException) as exc_info:
            await star_conversation("nonexistent", True, test_user)

        assert exc_info.value.status_code == 404


@pytest.mark.unit
class TestDeleteConversation:
    async def test_deletes_single_conversation(self, mock_collection, test_user):
        mock_result = MagicMock()
        mock_result.deleted_count = 1
        mock_collection.delete_one = AsyncMock(return_value=mock_result)

        result = await delete_conversation("conv_abc", test_user)

        assert result["conversation_id"] == "conv_abc"

    async def test_raises_404_when_not_found(self, mock_collection, test_user):
        mock_result = MagicMock()
        mock_result.deleted_count = 0
        mock_collection.delete_one = AsyncMock(return_value=mock_result)

        with pytest.raises(HTTPException) as exc_info:
            await delete_conversation("nonexistent", test_user)

        assert exc_info.value.status_code == 404

    async def test_delete_all(self, mock_collection, test_user):
        mock_result = MagicMock()
        mock_result.deleted_count = 5
        mock_collection.delete_many = AsyncMock(return_value=mock_result)

        result = await delete_all_conversations(test_user)
        assert result["message"] == "All conversations deleted successfully"

    async def test_delete_all_raises_404_when_none(self, mock_collection, test_user):
        mock_result = MagicMock()
        mock_result.deleted_count = 0
        mock_collection.delete_many = AsyncMock(return_value=mock_result)

        with pytest.raises(HTTPException) as exc_info:
            await delete_all_conversations(test_user)

        assert exc_info.value.status_code == 404


@pytest.mark.unit
class TestUpdateDescription:
    async def test_updates_description(self, mock_collection, test_user):
        mock_result = MagicMock()
        mock_result.modified_count = 1
        mock_collection.update_one = AsyncMock(return_value=mock_result)

        result = await update_conversation_description(
            "conv_abc", "New Description", test_user
        )

        assert result["description"] == "New Description"
        assert result["conversation_id"] == "conv_abc"

    async def test_raises_404_when_not_found(self, mock_collection, test_user):
        mock_result = MagicMock()
        mock_result.modified_count = 0
        mock_collection.update_one = AsyncMock(return_value=mock_result)

        with pytest.raises(HTTPException) as exc_info:
            await update_conversation_description("nonexistent", "New Desc", test_user)

        assert exc_info.value.status_code == 404


@pytest.mark.unit
class TestMarkAsReadUnread:
    async def test_mark_as_read(self, mock_collection, test_user):
        mock_collection.update_one = AsyncMock()

        result = await mark_conversation_as_read("conv_abc", test_user)
        assert result["conversation_id"] == "conv_abc"

        call_args = mock_collection.update_one.call_args
        update_doc = call_args[0][1]
        assert update_doc["$set"] == {"is_unread": False}

    async def test_mark_as_read_rejects_unauthenticated(self, mock_collection):
        with pytest.raises(HTTPException) as exc_info:
            await mark_conversation_as_read("conv_abc", {})

        assert exc_info.value.status_code == 403

    async def test_mark_as_unread(self, mock_collection, test_user):
        mock_result = MagicMock()
        mock_result.modified_count = 1
        mock_collection.update_one = AsyncMock(return_value=mock_result)

        result = await mark_conversation_as_unread("conv_abc", test_user)
        assert result["conversation_id"] == "conv_abc"

    async def test_mark_as_unread_rejects_unauthenticated(self, mock_collection):
        with pytest.raises(HTTPException) as exc_info:
            await mark_conversation_as_unread("conv_abc", {})

        assert exc_info.value.status_code == 403

    async def test_mark_as_unread_raises_404(self, mock_collection, test_user):
        mock_result = MagicMock()
        mock_result.modified_count = 0
        mock_collection.update_one = AsyncMock(return_value=mock_result)

        with pytest.raises(HTTPException) as exc_info:
            await mark_conversation_as_unread("conv_abc", test_user)

        assert exc_info.value.status_code == 404


@pytest.mark.unit
class TestHelperFunctions:
    def test_convert_datetime_to_iso(self):
        dt = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        obj = {"createdAt": dt, "name": "test"}
        _convert_datetime_to_iso(obj, "createdAt")

        assert isinstance(obj["createdAt"], str)
        assert "2024-01-15" in obj["createdAt"]
        assert obj["name"] == "test"

    def test_convert_datetime_skips_non_datetime(self):
        obj = {"createdAt": "already_string"}
        _convert_datetime_to_iso(obj, "createdAt")
        assert obj["createdAt"] == "already_string"

    def test_convert_datetime_skips_missing_fields(self):
        obj = {"name": "test"}
        _convert_datetime_to_iso(obj, "createdAt")
        assert "createdAt" not in obj

    def test_convert_ids(self):
        oid = ObjectId()
        conversations = [{"_id": oid, "conversation_id": "c1"}]
        result = _convert_ids(conversations)

        assert result[0]["_id"] == str(oid)
