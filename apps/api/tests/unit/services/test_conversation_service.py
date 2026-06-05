"""Unit tests for conversation service CRUD operations."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from bson import ObjectId
from fastapi import HTTPException
import pytest

from app.models.chat_models import ConversationModel, SystemPurpose
from app.services.conversation_service import (
    _convert_datetime_to_iso,
    _convert_ids,
    create_conversation_service,
    delete_all_conversations,
    delete_conversation,
    get_conversation,
    get_conversations,
    mark_conversation_as_read,
    mark_conversation_as_unread,
    star_conversation,
    update_conversation_description,
)


@pytest.fixture
def mock_collection():
    """Provide a mocked conversations_collection."""
    with patch("app.services.conversation_service.conversations_collection") as mock_col:
        yield mock_col


@pytest.fixture
def test_user():
    return {"user_id": "user_123", "email": "test@example.com"}


@pytest.mark.unit
class TestCreateConversationService:
    """Tests for create_conversation_service persistence, auth guard, error handling and source field."""

    async def test_creates_conversation_with_correct_data(self, mock_collection, test_user):
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
        mock_collection.insert_one = AsyncMock(side_effect=Exception("DB connection failed"))

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

    async def test_persists_source_when_set(self, mock_collection, test_user):
        """A bot conversation's source must be written to the document (as a string)
        so the web list query's $nin filter can exclude it."""
        from app.models.chat_models import ConversationSource

        mock_result = MagicMock()
        mock_result.acknowledged = True
        mock_collection.insert_one = AsyncMock(return_value=mock_result)

        conversation = ConversationModel(
            conversation_id="conv_bot",
            description="WhatsApp Chat",
            source=ConversationSource.WHATSAPP,
        )

        await create_conversation_service(conversation, test_user)

        call_args = mock_collection.insert_one.call_args[0][0]
        # Stored as the plain string literal, matching the $nin source values.
        assert call_args["source"] == "whatsapp"

    async def test_source_defaults_to_none_for_web(self, mock_collection, test_user):
        """Web/mobile conversations leave source null, which the $nin filter still
        includes — that behavior must be preserved."""
        mock_result = MagicMock()
        mock_result.acknowledged = True
        mock_collection.insert_one = AsyncMock(return_value=mock_result)

        conversation = ConversationModel(
            conversation_id="conv_web",
            description="New Chat",
        )

        await create_conversation_service(conversation, test_user)

        call_args = mock_collection.insert_one.call_args[0][0]
        assert call_args["source"] is None


@pytest.mark.unit
class TestGetConversation:
    """Tests for get_conversation retrieval, 404 handling and user_id ownership scoping."""

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

    async def test_get_conversation_wrong_user_returns_none(self, mock_collection):
        """A different user's conversation must not be returned.

        The MongoDB query is expected to include BOTH conversation_id AND user_id so
        that the lookup returns nothing for a user who does not own the conversation.
        """
        # Simulate MongoDB correctly honouring the user_id filter: no document found
        mock_collection.find_one = AsyncMock(return_value=None)

        other_user = {"user_id": "user_other"}

        with pytest.raises(HTTPException) as exc_info:
            await get_conversation("conv_abc", other_user)

        assert exc_info.value.status_code == 404

        # Critical: verify the filter sent to MongoDB contained the caller's user_id,
        # not the owner's user_id, so removing user_id from the query would break this.
        call_filter = mock_collection.find_one.call_args[0][0]
        assert call_filter.get("user_id") == "user_other"
        assert call_filter.get("conversation_id") == "conv_abc"


@pytest.mark.unit
class TestStarConversation:
    """Tests for star_conversation toggling the starred flag and 404 on no match."""

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
    """Tests for delete_conversation and delete_all_conversations, including 404 when nothing is deleted."""

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
    """Tests for update_conversation_description updating the title and 404 on no match."""

    async def test_updates_description(self, mock_collection, test_user):
        mock_result = MagicMock()
        mock_result.modified_count = 1
        mock_collection.update_one = AsyncMock(return_value=mock_result)

        result = await update_conversation_description("conv_abc", "New Description", test_user)

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
    """Tests for mark_conversation_as_read/unread toggling is_unread, auth guard and 404 handling."""

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
    """Tests for the _convert_datetime_to_iso and _convert_ids serialization helpers."""

    def test_convert_datetime_to_iso(self):
        dt = datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC)
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


@pytest.mark.unit
class TestListConversations:
    """Tests that verify get_conversations passes correct filters to MongoDB.

    The invariant being protected: removing the user_id filter from any query
    inside get_conversations must cause at least one test here to fail.
    """

    def _make_cursor(self, docs: list):
        """Return a mock async cursor that supports .sort().skip().limit().to_list()."""
        cursor = MagicMock()
        cursor.sort.return_value = cursor
        cursor.skip.return_value = cursor
        cursor.limit.return_value = cursor
        cursor.to_list = AsyncMock(return_value=docs)
        return cursor

    async def test_list_conversations_filters_by_user_id(self, mock_collection):
        """Every MongoDB query in get_conversations must include the caller's user_id."""
        user = {"user_id": "user_abc"}

        mock_collection.find.return_value = self._make_cursor([])
        mock_collection.count_documents = AsyncMock(return_value=0)

        await get_conversations(user, page=1, limit=10)

        assert mock_collection.find.call_count >= 1
        for call in mock_collection.find.call_args_list:
            query_filter = call[0][0]
            assert query_filter.get("user_id") == "user_abc", (
                "Every find() call must include user_id == 'user_abc'; "
                "a call without user_id would expose other users' data."
            )

        # count_documents must also be scoped to the correct user
        count_filter = mock_collection.count_documents.call_args[0][0]
        assert count_filter.get("user_id") == "user_abc"

    async def test_list_conversations_different_users_see_only_their_own(self, mock_collection):
        """Queries for two different users must carry distinct user_id values."""
        mock_collection.find.return_value = self._make_cursor([])
        mock_collection.count_documents = AsyncMock(return_value=0)

        await get_conversations({"user_id": "user_1"}, page=1, limit=10)
        calls_user_1 = [c[0][0] for c in mock_collection.find.call_args_list]

        mock_collection.find.reset_mock()
        mock_collection.count_documents.reset_mock()
        mock_collection.find.return_value = self._make_cursor([])
        mock_collection.count_documents = AsyncMock(return_value=0)

        await get_conversations({"user_id": "user_2"}, page=1, limit=10)
        calls_user_2 = [c[0][0] for c in mock_collection.find.call_args_list]

        for f in calls_user_1:
            assert f.get("user_id") == "user_1"
        for f in calls_user_2:
            assert f.get("user_id") == "user_2"

    async def test_list_conversations_pagination_skip_and_limit_applied(self, mock_collection):
        """Skip and limit must reflect the requested page and limit values."""
        user = {"user_id": "user_abc"}

        starred_cursor = self._make_cursor([])
        non_starred_cursor = self._make_cursor([])
        mock_collection.find.side_effect = [starred_cursor, non_starred_cursor]
        mock_collection.count_documents = AsyncMock(return_value=50)

        await get_conversations(user, page=3, limit=5)

        # The non-starred cursor should have skip((3-1)*5 = 10) and limit(5)
        non_starred_cursor.skip.assert_called_once_with(10)
        non_starred_cursor.limit.assert_called_once_with(5)

    async def test_list_conversations_sorted_by_created_at_descending(self, mock_collection):
        """Results must be sorted newest-first (createdAt descending = -1)."""
        user = {"user_id": "user_abc"}

        starred_cursor = self._make_cursor([])
        non_starred_cursor = self._make_cursor([])
        mock_collection.find.side_effect = [starred_cursor, non_starred_cursor]
        mock_collection.count_documents = AsyncMock(return_value=0)

        await get_conversations(user, page=1, limit=10)

        # Both cursors must sort by createdAt descending
        for cursor in [starred_cursor, non_starred_cursor]:
            cursor.sort.assert_called_once_with("createdAt", -1)

    async def test_list_conversations_returns_pagination_metadata(self, mock_collection):
        """Response must include total, page, limit and total_pages fields."""
        user = {"user_id": "user_abc"}

        mock_collection.find.return_value = self._make_cursor([])
        mock_collection.count_documents = AsyncMock(return_value=25)

        result = await get_conversations(user, page=2, limit=10)

        assert result["page"] == 2
        assert result["limit"] == 10
        assert "total" in result
        assert "total_pages" in result
        # 25 non-starred docs with limit 10 → 3 pages
        assert result["total_pages"] == 3

    @staticmethod
    def _matches_nin(doc: dict, nin_filter: dict) -> bool:
        """Replicate MongoDB $nin semantics for the `source` field.

        A document matches when its `source` value is NOT in the excluded list. A
        missing field is treated by Mongo as "not in the list" → it matches.
        """
        source = doc.get("source")
        return source not in nin_filter["source"]["$nin"]

    async def test_list_conversations_excludes_bot_sources(self, mock_collection):
        """Conversations from bot sources must be excluded via the $nin filter,
        while null-source (web/mobile) conversations are still included."""
        user = {"user_id": "user_abc"}

        mock_collection.find.return_value = self._make_cursor([])
        mock_collection.count_documents = AsyncMock(return_value=0)

        await get_conversations(user, page=1, limit=10)

        bot_sources = ["telegram", "discord", "slack", "whatsapp"]

        # Every find() call (starred + non-starred) must carry the $nin source filter.
        source_filters = []
        for call in mock_collection.find.call_args_list:
            query_filter = call[0][0]
            source_filter = query_filter.get("source", {})
            excluded = source_filter.get("$nin", [])
            assert set(bot_sources).issubset(set(excluded)), (
                "Bot sources must be excluded from conversation listings"
            )
            source_filters.append({"source": {"$nin": excluded}})

        assert source_filters, "get_conversations must issue at least one find() call"

        # Prove the filter actually keeps web/null conversations and drops bot ones.
        bot_conv = {"conversation_id": "c_bot", "source": "whatsapp"}
        web_conv = {"conversation_id": "c_web", "source": "web"}
        legacy_conv = {"conversation_id": "c_legacy"}  # no source field at all

        nin_filter = source_filters[0]
        assert not self._matches_nin(bot_conv, nin_filter), "bot conv must be excluded"
        assert self._matches_nin(web_conv, nin_filter), "web conv must be included"
        assert self._matches_nin(legacy_conv, nin_filter), "null-source conv must be included"

        # All bot sources, when set, are excluded.
        for source in bot_sources:
            assert not self._matches_nin({"conversation_id": "c", "source": source}, nin_filter), (
                f"source '{source}' must be excluded"
            )


# ---------------------------------------------------------------------------
# update_messages
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUpdateMessages:
    """Tests for update_messages appending messages, 404 handling and stripping None fields."""

    async def test_updates_messages_successfully(self, mock_collection, test_user):
        from app.models.chat_models import MessageModel, UpdateMessagesRequest
        from app.services.conversation_service import update_messages

        mock_result = MagicMock()
        mock_result.modified_count = 1
        mock_collection.update_one = AsyncMock(return_value=mock_result)

        msg = MessageModel(type="user", response="Hello")
        request = UpdateMessagesRequest(
            conversation_id="conv_abc",
            messages=[msg],
        )

        result = await update_messages(request, test_user)

        assert result["conversation_id"] == "conv_abc"
        assert result["message"] == "Messages updated"
        assert result["modified_count"] == 1
        assert len(result["message_ids"]) == 1

    async def test_raises_404_when_conversation_not_found(self, mock_collection, test_user):
        from app.models.chat_models import MessageModel, UpdateMessagesRequest
        from app.services.conversation_service import update_messages

        mock_result = MagicMock()
        mock_result.modified_count = 0
        mock_collection.update_one = AsyncMock(return_value=mock_result)

        msg = MessageModel(type="user", response="Hello")
        request = UpdateMessagesRequest(
            conversation_id="conv_missing",
            messages=[msg],
        )

        with pytest.raises(HTTPException) as exc_info:
            await update_messages(request, test_user)

        assert exc_info.value.status_code == 404

    async def test_strips_none_values_from_messages(self, mock_collection, test_user):
        from app.models.chat_models import MessageModel, UpdateMessagesRequest
        from app.services.conversation_service import update_messages

        mock_result = MagicMock()
        mock_result.modified_count = 1
        mock_collection.update_one = AsyncMock(return_value=mock_result)

        msg = MessageModel(type="user", response="Hi", disclaimer=None)
        request = UpdateMessagesRequest(
            conversation_id="conv_abc",
            messages=[msg],
        )

        await update_messages(request, test_user)

        call_args = mock_collection.update_one.call_args
        pushed_messages = call_args[0][1]["$push"]["messages"]["$each"]
        assert len(pushed_messages) == 1
        # None values should be stripped
        assert "disclaimer" not in pushed_messages[0]


# ---------------------------------------------------------------------------
# pin_message
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPinMessage:
    """Tests for pin_message pinning/unpinning and 404s for missing conversation, message or update."""

    async def test_pins_message_successfully(self, mock_collection, test_user):
        from app.services.conversation_service import pin_message

        mock_collection.find_one = AsyncMock(
            return_value={
                "_id": ObjectId(),
                "user_id": "user_123",
                "conversation_id": "conv_abc",
                "messages": [
                    {"message_id": "msg_1", "response": "Hello"},
                ],
            }
        )
        mock_result = MagicMock()
        mock_result.modified_count = 1
        mock_collection.update_one = AsyncMock(return_value=mock_result)

        result = await pin_message("conv_abc", "msg_1", True, test_user)

        assert result["pinned"] is True
        assert "pinned successfully" in result["message"]

    async def test_unpins_message(self, mock_collection, test_user):
        from app.services.conversation_service import pin_message

        mock_collection.find_one = AsyncMock(
            return_value={
                "_id": ObjectId(),
                "messages": [{"message_id": "msg_1"}],
            }
        )
        mock_result = MagicMock()
        mock_result.modified_count = 1
        mock_collection.update_one = AsyncMock(return_value=mock_result)

        result = await pin_message("conv_abc", "msg_1", False, test_user)

        assert result["pinned"] is False
        assert "unpinned successfully" in result["message"]

    async def test_raises_404_conversation_not_found(self, mock_collection, test_user):
        from app.services.conversation_service import pin_message

        mock_collection.find_one = AsyncMock(return_value=None)

        with pytest.raises(HTTPException) as exc_info:
            await pin_message("conv_abc", "msg_1", True, test_user)

        assert exc_info.value.status_code == 404

    async def test_raises_404_message_not_found(self, mock_collection, test_user):
        from app.services.conversation_service import pin_message

        mock_collection.find_one = AsyncMock(
            return_value={
                "_id": ObjectId(),
                "messages": [{"message_id": "msg_other"}],
            }
        )

        with pytest.raises(HTTPException) as exc_info:
            await pin_message("conv_abc", "msg_nonexistent", True, test_user)

        assert exc_info.value.status_code == 404

    async def test_raises_404_update_failed(self, mock_collection, test_user):
        from app.services.conversation_service import pin_message

        mock_collection.find_one = AsyncMock(
            return_value={
                "_id": ObjectId(),
                "messages": [{"message_id": "msg_1"}],
            }
        )
        mock_result = MagicMock()
        mock_result.modified_count = 0
        mock_collection.update_one = AsyncMock(return_value=mock_result)

        with pytest.raises(HTTPException) as exc_info:
            await pin_message("conv_abc", "msg_1", True, test_user)

        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# get_starred_messages
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetStarredMessages:
    """Tests for get_starred_messages aggregating pinned messages and the empty-result case."""

    async def test_returns_pinned_messages(self, mock_collection, test_user):
        from app.services.conversation_service import get_starred_messages

        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(
            return_value=[
                {
                    "conversation_id": "conv_1",
                    "message": {"message_id": "m1", "response": "test", "pinned": True},
                },
            ]
        )
        mock_collection.aggregate = MagicMock(return_value=mock_cursor)

        with patch(
            "app.services.conversation_service.convert_legacy_tool_data",
            side_effect=lambda x: x,
        ):
            result = await get_starred_messages(test_user)

        assert len(result["results"]) == 1
        assert result["results"][0]["conversation_id"] == "conv_1"

    async def test_returns_empty_results(self, mock_collection, test_user):
        from app.services.conversation_service import get_starred_messages

        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=[])
        mock_collection.aggregate = MagicMock(return_value=mock_cursor)

        result = await get_starred_messages(test_user)

        assert result["results"] == []


# ---------------------------------------------------------------------------
# create_system_conversation
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCreateSystemConversation:
    """Tests for create_system_conversation persisting system-generated docs and 500 error handling."""

    async def test_creates_system_conversation(self, mock_collection):
        from app.services.conversation_service import create_system_conversation

        mock_result = MagicMock()
        mock_result.acknowledged = True
        mock_collection.insert_one = AsyncMock(return_value=mock_result)

        result = await create_system_conversation(
            "user_123", "Email Actions", SystemPurpose.EMAIL_PROCESSING
        )

        assert result["user_id"] == "user_123"
        assert result["is_system_generated"] is True
        assert result["system_purpose"] == SystemPurpose.EMAIL_PROCESSING
        assert result["detail"] == "System conversation created successfully"

    async def test_raises_500_on_not_acknowledged(self, mock_collection):
        from app.services.conversation_service import create_system_conversation

        mock_result = MagicMock()
        mock_result.acknowledged = False
        mock_collection.insert_one = AsyncMock(return_value=mock_result)

        with pytest.raises(HTTPException) as exc_info:
            await create_system_conversation("user_123", "Test", SystemPurpose.OTHER)

        assert exc_info.value.status_code == 500

    async def test_raises_500_on_exception(self, mock_collection):
        from app.services.conversation_service import create_system_conversation

        mock_collection.insert_one = AsyncMock(side_effect=Exception("DB error"))

        with pytest.raises(HTTPException) as exc_info:
            await create_system_conversation("user_123", "Test", SystemPurpose.OTHER)

        assert exc_info.value.status_code == 500


# ---------------------------------------------------------------------------
# get_or_create_system_conversation
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# batch_sync_conversations
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBatchSyncConversations:
    """Tests for batch_sync_conversations auth guard, timestamp parsing and datetime serialization."""

    async def test_returns_empty_when_no_user_id(self, mock_collection):
        from app.models.chat_models import BatchSyncRequest
        from app.services.conversation_service import batch_sync_conversations

        request = BatchSyncRequest(conversations=[])
        with pytest.raises(HTTPException) as exc_info:
            await batch_sync_conversations(request, {})

        assert exc_info.value.status_code == 403

    async def test_returns_empty_for_empty_conversations(self, mock_collection, test_user):
        from app.models.chat_models import BatchSyncRequest
        from app.services.conversation_service import batch_sync_conversations

        request = BatchSyncRequest(conversations=[])
        result = await batch_sync_conversations(request, test_user)

        assert result == {"conversations": []}

    async def test_returns_updated_conversations(self, mock_collection, test_user):
        from app.models.chat_models import BatchSyncRequest, ConversationSyncItem
        from app.services.conversation_service import batch_sync_conversations

        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(
            return_value=[
                {
                    "conversation_id": "conv_1",
                    "description": "Updated Chat",
                    "messages": [],
                }
            ]
        )
        mock_collection.aggregate = MagicMock(return_value=mock_cursor)

        request = BatchSyncRequest(
            conversations=[
                ConversationSyncItem(
                    conversation_id="conv_1",
                    last_updated="2024-01-01T00:00:00Z",
                ),
            ]
        )

        with patch(
            "app.services.conversation_service.convert_conversation_messages",
            side_effect=lambda x: x,
        ):
            result = await batch_sync_conversations(request, test_user)

        assert len(result["conversations"]) == 1
        assert result["conversations"][0]["conversation_id"] == "conv_1"

    async def test_handles_no_last_updated(self, mock_collection, test_user):
        from app.models.chat_models import BatchSyncRequest, ConversationSyncItem
        from app.services.conversation_service import batch_sync_conversations

        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=[])
        mock_collection.aggregate = MagicMock(return_value=mock_cursor)

        request = BatchSyncRequest(
            conversations=[
                ConversationSyncItem(
                    conversation_id="conv_1",
                    last_updated=None,
                ),
            ]
        )

        with patch(
            "app.services.conversation_service.convert_conversation_messages",
            side_effect=lambda x: x,
        ):
            result = await batch_sync_conversations(request, test_user)

        assert "conversations" in result

    async def test_handles_invalid_timestamp(self, mock_collection, test_user):
        from app.models.chat_models import BatchSyncRequest, ConversationSyncItem
        from app.services.conversation_service import batch_sync_conversations

        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=[])
        mock_collection.aggregate = MagicMock(return_value=mock_cursor)

        request = BatchSyncRequest(
            conversations=[
                ConversationSyncItem(
                    conversation_id="conv_1",
                    last_updated="not-a-date",
                ),
            ]
        )

        with patch(
            "app.services.conversation_service.convert_conversation_messages",
            side_effect=lambda x: x,
        ):
            result = await batch_sync_conversations(request, test_user)

        assert "conversations" in result

    async def test_converts_datetime_in_messages(self, mock_collection, test_user):
        from app.models.chat_models import BatchSyncRequest, ConversationSyncItem
        from app.services.conversation_service import batch_sync_conversations

        dt = datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(
            return_value=[
                {
                    "conversation_id": "conv_1",
                    "createdAt": dt,
                    "messages": [
                        {"message_id": "m1", "timestamp": dt},
                    ],
                }
            ]
        )
        mock_collection.aggregate = MagicMock(return_value=mock_cursor)

        request = BatchSyncRequest(
            conversations=[
                ConversationSyncItem(conversation_id="conv_1"),
            ]
        )

        with patch(
            "app.services.conversation_service.convert_conversation_messages",
            side_effect=lambda x: x,
        ):
            result = await batch_sync_conversations(request, test_user)

        conv = result["conversations"][0]
        assert isinstance(conv["createdAt"], str)
        assert isinstance(conv["messages"][0]["timestamp"], str)
