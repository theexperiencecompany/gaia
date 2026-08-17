"""Unit tests for the conversation service layer.

The service is functional; it orchestrates ``conversation_repository`` and maps
its results to HTTP responses. Per the repository-layer contract, these tests
mock the repository singleton (never the DB) and assert the service's own
behaviour — auth guards, 404 mapping, response shapes, and that each function
delegates to the right repository method with the caller's ``user_id``. The
repository's own behaviour (user-scoping, source persistence, message stripping,
pin semantics) is covered by the real-DB contract suite.
"""

from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
import pytest

from app.models.chat_models import (
    BatchSyncRequest,
    ConversationModel,
    ConversationSource,
    ConversationSyncItem,
    MessageModel,
    SystemPurpose,
    UpdateMessagesRequest,
)
from app.models.conversation_models import (
    ConversationDocument,
    ConversationMessageHit,
    ConversationSummary,
)
from app.services import conversation_service
from app.services.analytics_service import AnalyticsEvents
from app.services.conversation_service import (
    batch_sync_conversations,
    create_conversation_service,
    create_system_conversation,
    delete_all_conversations,
    delete_conversation,
    get_conversation,
    get_conversations,
    get_starred_messages,
    mark_conversation_as_read,
    mark_conversation_as_unread,
    pin_message,
    star_conversation,
    update_conversation_description,
    update_messages,
)


@pytest.fixture
def mock_repo():
    """Patch the repository singleton with an AsyncMock (services mock the repo)."""
    repo = AsyncMock()
    with patch.object(conversation_service, "conversation_repository", repo):
        yield repo


@pytest.fixture
def test_user():
    return {"user_id": "user_123", "email": "test@example.com"}


@pytest.fixture(autouse=True)
def _no_analytics():
    """Neutralize analytics captures for tests not asserting on them.

    ``capture_event`` resolves the PostHog provider at call time, which is not
    registered in this test module's import chain — capture-specific tests
    patch the call explicitly and assert on it.
    """
    with (
        patch("app.services.conversation_service.capture_event"),
    ):
        yield


def _document(**overrides) -> ConversationDocument:
    data = {
        "user_id": "user_123",
        "conversation_id": "conv_abc",
        "createdAt": "2026-01-01T00:00:00+00:00",
    }
    data.update(overrides)
    return ConversationDocument.model_validate(data)


class TestCreateConversationService:
    async def test_creates_conversation_and_returns_response(self, mock_repo, test_user):
        mock_repo.create.return_value = _document()
        conversation = ConversationModel(conversation_id="conv_abc", description="Test Chat")

        result = await create_conversation_service(conversation, test_user)

        assert result.conversation_id == "conv_abc"
        assert result.user_id == "user_123"
        assert result.detail == "Conversation created successfully"
        # The document handed to the repository carries the caller's user_id + fields.
        document = mock_repo.create.call_args[0][0]
        assert document.user_id == "user_123"
        assert document.conversation_id == "conv_abc"
        assert document.description == "Test Chat"

    async def test_raises_403_when_no_user_id(self, mock_repo):
        with pytest.raises(HTTPException) as exc_info:
            await create_conversation_service(ConversationModel(conversation_id="c"), {})
        assert exc_info.value.status_code == 403

    async def test_raises_500_on_repository_error(self, mock_repo, test_user):
        mock_repo.create.side_effect = Exception("DB connection failed")
        with pytest.raises(HTTPException) as exc_info:
            await create_conversation_service(ConversationModel(conversation_id="c"), test_user)
        assert exc_info.value.status_code == 500

    async def test_captures_conversation_created(self, mock_repo, test_user):
        mock_repo.create.return_value = _document()
        conversation = ConversationModel(conversation_id="conv_abc", description="Test Chat")

        with patch("app.services.conversation_service.capture_event") as mock_capture:
            await create_conversation_service(conversation, test_user)

        mock_capture.assert_called_once_with(
            "user_123",
            AnalyticsEvents.CONVERSATION_CREATED,
            {"is_system_generated": False, "is_onboarding_demo": False},
        )

    async def test_no_capture_on_repository_error(self, mock_repo, test_user):
        mock_repo.create.side_effect = Exception("DB connection failed")
        with (
            pytest.raises(HTTPException),
            patch("app.services.conversation_service.capture_event") as mock_capture,
        ):
            await create_conversation_service(ConversationModel(conversation_id="c"), test_user)
        mock_capture.assert_not_called()

    async def test_persists_source_and_flags(self, mock_repo, test_user):
        mock_repo.create.return_value = _document()
        conversation = ConversationModel(
            conversation_id="conv_bot",
            description="WhatsApp Chat",
            source=ConversationSource.WHATSAPP,
            is_system_generated=True,
            system_purpose=SystemPurpose.EMAIL_PROCESSING,
        )
        await create_conversation_service(conversation, test_user)
        document = mock_repo.create.call_args[0][0]
        assert document.source is ConversationSource.WHATSAPP
        assert document.is_system_generated is True
        assert document.system_purpose is SystemPurpose.EMAIL_PROCESSING


class TestGetConversation:
    async def test_returns_dumped_document(self, mock_repo, test_user):
        mock_repo.get.return_value = _document(description="Test")
        result = await get_conversation("conv_abc", test_user)
        assert result.conversation_id == "conv_abc"
        assert result.description == "Test"
        # Scoped by the caller's user_id.
        assert mock_repo.get.call_args.kwargs["user_id"] == "user_123"

    async def test_raises_404_when_not_found(self, mock_repo, test_user):
        mock_repo.get.return_value = None
        with pytest.raises(HTTPException) as exc_info:
            await get_conversation("nonexistent", test_user)
        assert exc_info.value.status_code == 404


class TestStarConversation:
    async def test_stars(self, mock_repo, test_user):
        mock_repo.set_starred.return_value = True
        result = await star_conversation("conv_abc", True, test_user)
        assert result.starred is True
        assert mock_repo.set_starred.call_args.kwargs["user_id"] == "user_123"

    async def test_raises_404_when_not_found(self, mock_repo, test_user):
        mock_repo.set_starred.return_value = False
        with pytest.raises(HTTPException) as exc_info:
            await star_conversation("nonexistent", True, test_user)
        assert exc_info.value.status_code == 404

    async def test_captures_conversation_starred(self, mock_repo, test_user):
        mock_repo.set_starred.return_value = True
        with patch("app.services.conversation_service.capture_event") as mock_capture:
            await star_conversation("conv_abc", True, test_user)
        mock_capture.assert_called_once_with(
            "user_123",
            AnalyticsEvents.CONVERSATION_STARRED,
            {"starred": True, "conversation_id": "conv_abc"},
        )


class TestDeleteConversation:
    async def test_deletes_single(self, mock_repo, test_user):
        mock_repo.delete.return_value = True
        with (
            patch.object(conversation_service, "delete_session_dir", new=AsyncMock()),
            patch.object(conversation_service, "_cleanup_checkpoint_threads", new=AsyncMock()),
            patch("app.services.conversation_service.capture_event") as mock_capture,
        ):
            result = await delete_conversation("conv_abc", test_user)
        assert result.conversation_id == "conv_abc"
        mock_capture.assert_called_once_with(
            "user_123", AnalyticsEvents.CONVERSATION_DELETED, {"conversation_id": "conv_abc"}
        )

    async def test_raises_404_when_not_found(self, mock_repo, test_user):
        mock_repo.delete.return_value = False
        with pytest.raises(HTTPException) as exc_info:
            await delete_conversation("nonexistent", test_user)
        assert exc_info.value.status_code == 404

    async def test_delete_all_cleans_up_each_conversation(self, mock_repo, test_user):
        mock_repo.delete_all_for_user.return_value = ["conv_1", "conv_2"]
        cleanup = AsyncMock()
        with (
            patch.object(conversation_service, "_cleanup_checkpoint_threads", new=cleanup),
            patch("app.services.conversation_service.capture_event") as mock_capture,
        ):
            result = await delete_all_conversations(test_user)
        assert result.message == "All conversations deleted successfully"
        assert cleanup.await_count == 2
        mock_capture.assert_called_once_with(
            "user_123", AnalyticsEvents.CONVERSATION_DELETED, {"count": 2}
        )

    async def test_delete_all_raises_404_when_none(self, mock_repo, test_user):
        mock_repo.delete_all_for_user.return_value = []
        with pytest.raises(HTTPException) as exc_info:
            await delete_all_conversations(test_user)
        assert exc_info.value.status_code == 404


class TestUpdateDescription:
    async def test_updates(self, mock_repo, test_user):
        mock_repo.set_description.return_value = True
        result = await update_conversation_description("conv_abc", "New Description", test_user)
        assert result.description == "New Description"

    async def test_raises_404_when_not_found(self, mock_repo, test_user):
        mock_repo.set_description.return_value = False
        with pytest.raises(HTTPException) as exc_info:
            await update_conversation_description("nonexistent", "New Desc", test_user)
        assert exc_info.value.status_code == 404

    async def test_captures_conversation_renamed(self, mock_repo, test_user):
        mock_repo.set_description.return_value = True
        with patch("app.services.conversation_service.capture_event") as mock_capture:
            await update_conversation_description("conv_abc", "New Description", test_user)
        mock_capture.assert_called_once_with(
            "user_123",
            AnalyticsEvents.CONVERSATION_RENAMED,
            {"conversation_id": "conv_abc"},
        )


class TestMarkAsReadUnread:
    async def test_mark_as_read(self, mock_repo, test_user):
        mock_repo.set_unread.return_value = True
        result = await mark_conversation_as_read("conv_abc", test_user)
        assert result.conversation_id == "conv_abc"
        assert mock_repo.set_unread.call_args.kwargs["unread"] is False

    async def test_mark_as_read_rejects_unauthenticated(self, mock_repo):
        with pytest.raises(HTTPException) as exc_info:
            await mark_conversation_as_read("conv_abc", {})
        assert exc_info.value.status_code == 403

    async def test_mark_as_unread(self, mock_repo, test_user):
        mock_repo.set_unread.return_value = True
        result = await mark_conversation_as_unread("conv_abc", test_user)
        assert result.conversation_id == "conv_abc"
        assert mock_repo.set_unread.call_args.kwargs["unread"] is True

    async def test_mark_as_unread_rejects_unauthenticated(self, mock_repo):
        with pytest.raises(HTTPException) as exc_info:
            await mark_conversation_as_unread("conv_abc", {})
        assert exc_info.value.status_code == 403

    async def test_mark_as_unread_raises_404(self, mock_repo, test_user):
        mock_repo.set_unread.return_value = False
        with pytest.raises(HTTPException) as exc_info:
            await mark_conversation_as_unread("conv_abc", test_user)
        assert exc_info.value.status_code == 404


class TestListConversations:
    async def test_combines_starred_and_active_with_metadata(self, mock_repo):
        mock_repo.list_starred_summaries.return_value = [
            ConversationSummary(conversation_id="s1", user_id="user_abc")
        ]
        mock_repo.list_active_summaries.return_value = [
            ConversationSummary(conversation_id="a1", user_id="user_abc")
        ]
        mock_repo.count_active.return_value = 25

        result = await get_conversations({"user_id": "user_abc"}, page=2, limit=10)

        ids = [c.conversation_id for c in result.conversations]
        assert ids == ["s1", "a1"]  # starred first
        assert result.page == 2 and result.limit == 10
        assert result.total == 1 + 25
        assert result.total_pages == 3  # 25 active / 10
        # Active list is paginated with the requested page's skip/limit.
        assert mock_repo.list_active_summaries.call_args.kwargs == {"skip": 10, "limit": 10}

    async def test_scopes_every_query_to_the_caller(self, mock_repo):
        mock_repo.list_starred_summaries.return_value = []
        mock_repo.list_active_summaries.return_value = []
        mock_repo.count_active.return_value = 0
        await get_conversations({"user_id": "user_1"}, page=1, limit=10)
        assert mock_repo.list_starred_summaries.call_args[0][0] == "user_1"
        assert mock_repo.list_active_summaries.call_args[0][0] == "user_1"
        assert mock_repo.count_active.call_args[0][0] == "user_1"


class TestUpdateMessages:
    async def test_appends_and_returns_ids(self, mock_repo, test_user):
        mock_repo.append_messages.return_value = ["m1"]
        request = UpdateMessagesRequest(
            conversation_id="conv_abc", messages=[MessageModel(type="user", response="Hi")]
        )
        result = await update_messages(request, test_user)
        assert result.message_ids == ["m1"]
        assert result.conversation_id == "conv_abc"
        assert mock_repo.append_messages.call_args.kwargs["user_id"] == "user_123"

    async def test_raises_404_when_conversation_missing(self, mock_repo, test_user):
        mock_repo.append_messages.return_value = None
        request = UpdateMessagesRequest(
            conversation_id="missing", messages=[MessageModel(type="user", response="Hi")]
        )
        with pytest.raises(HTTPException) as exc_info:
            await update_messages(request, test_user)
        assert exc_info.value.status_code == 404


class TestPinMessage:
    async def test_pins_message(self, mock_repo, test_user):
        mock_repo.get.return_value = _document(
            messages=[{"type": "bot", "response": "Hello", "message_id": "msg_1"}]
        )
        mock_repo.set_message_pinned.return_value = True
        result = await pin_message("conv_abc", "msg_1", True, test_user)
        assert result.pinned is True
        assert "pinned successfully" in result.message

    async def test_raises_404_conversation_not_found(self, mock_repo, test_user):
        mock_repo.get.return_value = None
        with pytest.raises(HTTPException) as exc_info:
            await pin_message("conv_abc", "msg_1", True, test_user)
        assert exc_info.value.status_code == 404

    async def test_raises_404_message_not_found(self, mock_repo, test_user):
        mock_repo.get.return_value = _document(
            messages=[{"type": "bot", "response": "x", "message_id": "other"}]
        )
        with pytest.raises(HTTPException) as exc_info:
            await pin_message("conv_abc", "missing", True, test_user)
        assert exc_info.value.status_code == 404


class TestGetStarredMessages:
    async def test_returns_pinned(self, mock_repo, test_user):
        mock_repo.list_pinned_messages.return_value = [
            ConversationMessageHit(
                conversation_id="conv_1",
                message={"type": "bot", "response": "test", "message_id": "m1", "pinned": True},
            )
        ]
        result = await get_starred_messages(test_user)
        assert len(result.results) == 1
        assert result.results[0].conversation_id == "conv_1"

    async def test_returns_empty(self, mock_repo, test_user):
        mock_repo.list_pinned_messages.return_value = []
        result = await get_starred_messages(test_user)
        assert result.results == []


class TestCreateSystemConversation:
    async def test_creates(self, mock_repo):
        mock_repo.create.return_value = _document()
        result = await create_system_conversation(
            "user_123", "Email Actions", SystemPurpose.EMAIL_PROCESSING
        )
        assert result.user_id == "user_123"
        assert result.is_system_generated is True
        assert result.system_purpose == SystemPurpose.EMAIL_PROCESSING
        document = mock_repo.create.call_args[0][0]
        assert document.is_system_generated is True and document.is_unread is True

    async def test_raises_500_on_error(self, mock_repo):
        mock_repo.create.side_effect = Exception("DB error")
        with pytest.raises(HTTPException) as exc_info:
            await create_system_conversation("user_123", "Test", SystemPurpose.OTHER)
        assert exc_info.value.status_code == 500

    async def test_captures_system_conversation_created(self, mock_repo):
        mock_repo.create.return_value = _document()
        with patch("app.services.conversation_service.capture_event") as mock_capture:
            await create_system_conversation(
                "user_123", "Email Actions", SystemPurpose.WORKFLOW_EXECUTION
            )
        mock_capture.assert_called_once_with(
            "user_123",
            AnalyticsEvents.CONVERSATION_CREATED,
            {"is_system_generated": True, "system_purpose": "workflow_execution"},
        )


class TestBatchSyncConversations:
    async def test_rejects_unauthenticated(self, mock_repo):
        with pytest.raises(HTTPException) as exc_info:
            await batch_sync_conversations(BatchSyncRequest(conversations=[]), {})
        assert exc_info.value.status_code == 403

    async def test_returns_empty_for_empty_request(self, mock_repo, test_user):
        result = await batch_sync_conversations(BatchSyncRequest(conversations=[]), test_user)
        assert result.conversations == []
        mock_repo.find_updated_since.assert_not_called()

    async def test_returns_rows_with_active_stream_id(self, mock_repo, test_user):
        mock_repo.find_updated_since.return_value = [_document(description="Updated Chat")]
        with patch.object(
            conversation_service.stream_manager,
            "get_resumable_stream_id",
            new=AsyncMock(return_value="stream-1"),
        ):
            request = BatchSyncRequest(
                conversations=[ConversationSyncItem(conversation_id="conv_abc")]
            )
            result = await batch_sync_conversations(request, test_user)

        assert len(result.conversations) == 1
        row = result.conversations[0]
        assert row.conversation_id == "conv_abc"
        assert row.active_stream_id == "stream-1"
        # The internal user_id/_id must not leak into a serialized sync row.
        serialized = row.model_dump()
        assert "user_id" not in serialized and "_id" not in serialized
