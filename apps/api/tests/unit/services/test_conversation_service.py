"""Unit tests for the conversation service layer.

The service is functional; it orchestrates ``conversation_repository`` and maps
its results to HTTP responses. Per the repository-layer contract, these tests
mock the repository singleton (never the DB) and assert the service's own
behaviour — auth guards, 404 mapping, exact response shapes, exact arguments
forwarded to the repository (including the empty-string user_id the service
derives when the auth payload carries no user), and the error paths (repository
failures, session-dir cleanup failures) that must not fail the API call. The
repository's own behaviour (user-scoping, source persistence, message stripping,
pin semantics) is covered by the real-DB contract suite.
"""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, call, patch
from uuid import UUID

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
    BatchSyncResponse,
    ConversationDocument,
    ConversationMessageHit,
    ConversationSummary,
    ConversationSyncRow,
)
from app.services import conversation_service
from app.services.conversation_service import (
    _cleanup_checkpoint_threads,
    _delete_checkpoint_threads,
    _like_escape,
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
from app.services.storage import JuiceFSUnavailable


@pytest.fixture
def mock_repo():
    """Patch the repository singleton with an AsyncMock (services mock the repo)."""
    repo = AsyncMock()
    with patch.object(conversation_service, "conversation_repository", repo):
        yield repo


@pytest.fixture
def test_user():
    return {"user_id": "user_123", "email": "test@example.com"}


@pytest.fixture
def decoy_user():
    """An auth payload whose dict also carries decoy keys.

    Pins the exact ``"user_id"`` key the service reads out of the payload: a
    lookup of any other key (``"USER_ID"``, the empty string, ``None``) would
    surface the decoy value and break the exact-call assertions.
    """
    return {
        "user_id": "user_123",
        "email": "test@example.com",
        None: "decoy",
        "": "decoy",
        "XXuser_idXX": "decoy",
        "USER_ID": "decoy",
    }


def _document(**overrides) -> ConversationDocument:
    data = {
        "user_id": "user_123",
        "conversation_id": "conv_abc",
        "createdAt": "2026-01-01T00:00:00+00:00",
    }
    data.update(overrides)
    return ConversationDocument.model_validate(data)


class TestLikeEscape:
    async def test_escapes_wildcards_and_backslashes(self):
        assert _like_escape("plain") == "plain"
        assert _like_escape("50%") == "50\\%"
        assert _like_escape("a_b") == "a\\_b"
        assert _like_escape("a\\b") == "a\\\\b"
        # Backslash first, then wildcards: a pre-escaped sequence stays escaped.
        assert _like_escape(r"\%_") == "\\\\\\%\\_"


class TestCheckpointCleanup:
    def _delete_setup(self, thread_ids):
        """Async-context stubs for the pool/connection/cursor chain.

        ``async with pool.connection() as conn, conn.cursor() as cur`` — the
        pool proxy is a plain Mock whose call returns an async context manager;
        a bare AsyncMock call would hand back a coroutine instead.
        """
        cursor = AsyncMock()
        cursor.fetchall.return_value = thread_ids
        cur_cm = AsyncMock()
        cur_cm.__aenter__.return_value = cursor
        conn = Mock()
        conn.cursor.return_value = cur_cm
        conn_cm = AsyncMock()
        conn_cm.__aenter__.return_value = conn
        pool = Mock()
        pool.connection.return_value = conn_cm
        checkpointer = AsyncMock()
        manager = SimpleNamespace(pool=pool, get_checkpointer=lambda: checkpointer)
        return manager, cursor, checkpointer

    async def test_deletes_every_matching_thread(self):
        manager, cursor, checkpointer = self._delete_setup(
            [("conv_abc",), ("executor_conv_abc_123",)]
        )
        with patch.object(
            conversation_service,
            "get_checkpointer_manager",
            new=AsyncMock(return_value=manager),
        ):
            await _delete_checkpoint_threads("conv_abc")
        cursor.execute.assert_awaited_once_with(
            "SELECT DISTINCT thread_id FROM checkpoints WHERE thread_id LIKE %s ESCAPE '\\'",
            ("%conv\\_abc%",),
        )
        assert checkpointer.adelete_thread.call_args_list == [
            call("conv_abc"),
            call("executor_conv_abc_123"),
        ]

    async def test_escapes_wildcards_in_the_like_pattern(self):
        manager, cursor, checkpointer = self._delete_setup([])
        with patch.object(
            conversation_service,
            "get_checkpointer_manager",
            new=AsyncMock(return_value=manager),
        ):
            await _delete_checkpoint_threads("50%_x")
        cursor.execute.assert_awaited_once_with(
            "SELECT DISTINCT thread_id FROM checkpoints WHERE thread_id LIKE %s ESCAPE '\\'",
            ("%50\\%\\_x%",),
        )
        checkpointer.adelete_thread.assert_not_awaited()

    async def test_cleanup_checkpoint_threads_logs_failure(self):
        inner = AsyncMock(side_effect=Exception("boom"))
        with (
            patch.object(conversation_service, "_delete_checkpoint_threads", new=inner),
            patch.object(conversation_service, "log", new=Mock()) as log,
        ):
            await _cleanup_checkpoint_threads("conv_abc")
        inner.assert_awaited_once_with("conv_abc")
        log.warning.assert_called_once_with(
            "[AGENT] checkpoint thread cleanup failed", conv="conv_abc", error="boom"
        )

    async def test_cleanup_checkpoint_threads_is_quiet_on_success(self):
        inner = AsyncMock()
        with (
            patch.object(conversation_service, "_delete_checkpoint_threads", new=inner),
            patch.object(conversation_service, "log", new=Mock()) as log,
        ):
            await _cleanup_checkpoint_threads("conv_abc")
        inner.assert_awaited_once_with("conv_abc")
        log.warning.assert_not_called()


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
        # Unset flags are stored as explicit falsy defaults, not None.
        assert document.is_system_generated is False
        assert document.is_unread is False
        assert document.is_onboarding_demo is False
        assert document.source is None
        assert document.system_purpose is None
        # created_at is one UTC instant, shared by the document and the response.
        assert document.createdAt is not None
        assert document.createdAt == result.createdAt
        assert document.createdAt.endswith("+00:00")

    async def test_raises_403_when_no_user_id(self, mock_repo):
        with pytest.raises(HTTPException) as exc_info:
            await create_conversation_service(ConversationModel(conversation_id="c"), {})
        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == "Not authenticated"

    async def test_raises_500_on_repository_error(self, mock_repo, test_user):
        mock_repo.create.side_effect = Exception("DB connection failed")
        with pytest.raises(HTTPException) as exc_info:
            await create_conversation_service(ConversationModel(conversation_id="c"), test_user)
        assert exc_info.value.status_code == 500
        assert exc_info.value.detail == "Failed to create conversation: DB connection failed"

    async def test_persists_source_and_flags(self, mock_repo, test_user):
        mock_repo.create.return_value = _document()
        conversation = ConversationModel(
            conversation_id="conv_bot",
            description="WhatsApp Chat",
            source=ConversationSource.WHATSAPP,
            is_system_generated=True,
            system_purpose=SystemPurpose.EMAIL_PROCESSING,
            is_unread=True,
            is_onboarding_demo=True,
        )
        await create_conversation_service(conversation, test_user)
        document = mock_repo.create.call_args[0][0]
        assert document.source is ConversationSource.WHATSAPP
        assert document.is_system_generated is True
        assert document.system_purpose is SystemPurpose.EMAIL_PROCESSING
        assert document.is_unread is True
        assert document.is_onboarding_demo is True


class TestGetConversation:
    async def test_returns_dumped_document(self, mock_repo, test_user):
        mock_repo.get.return_value = _document(description="Test")
        result = await get_conversation("conv_abc", test_user)
        assert result.conversation_id == "conv_abc"
        assert result.description == "Test"
        # Scoped by the caller's user_id.
        mock_repo.get.assert_awaited_once_with("conv_abc", user_id="user_123")

    async def test_raises_404_when_not_found(self, mock_repo, test_user):
        mock_repo.get.return_value = None
        with pytest.raises(HTTPException) as exc_info:
            await get_conversation("nonexistent", test_user)
        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "Conversation not found or does not belong to the user"

    async def test_defaults_to_empty_user_id(self, mock_repo):
        mock_repo.get.return_value = _document()
        result = await get_conversation("conv_abc", {"email": "test@example.com"})
        assert result.conversation_id == "conv_abc"
        mock_repo.get.assert_awaited_once_with("conv_abc", user_id="")


class TestStarConversation:
    async def test_stars(self, mock_repo, test_user):
        mock_repo.set_starred.return_value = True
        result = await star_conversation("conv_abc", True, test_user)
        assert result.starred is True
        assert result.message == "Conversation updated successfully"
        mock_repo.set_starred.assert_awaited_once_with(
            "conv_abc", user_id="user_123", starred=True
        )

    async def test_raises_404_when_not_found(self, mock_repo, test_user):
        mock_repo.set_starred.return_value = False
        with pytest.raises(HTTPException) as exc_info:
            await star_conversation("nonexistent", True, test_user)
        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "Conversation not found or update failed"

    async def test_defaults_to_empty_user_id(self, mock_repo):
        mock_repo.set_starred.return_value = True
        result = await star_conversation("conv_abc", True, {"email": "test@example.com"})
        assert result.starred is True
        mock_repo.set_starred.assert_awaited_once_with(
            "conv_abc", user_id="", starred=True
        )


class TestDeleteConversation:
    async def test_deletes_single(self, mock_repo, decoy_user):
        mock_repo.delete.return_value = True
        session_dir = AsyncMock()
        cleanup = AsyncMock()
        with (
            patch.object(conversation_service, "delete_session_dir", new=session_dir),
            patch.object(conversation_service, "_cleanup_checkpoint_threads", new=cleanup),
        ):
            result = await delete_conversation("conv_abc", decoy_user)
        assert result.conversation_id == "conv_abc"
        assert result.message == "Conversation deleted successfully"
        # conversation_id + user_id are forwarded into every call.
        mock_repo.delete.assert_awaited_once_with("conv_abc", user_id="user_123")
        session_dir.assert_awaited_once_with("user_123", "conv_abc")
        cleanup.assert_awaited_once_with("conv_abc")

    async def test_deletes_with_missing_user_id(self, mock_repo):
        """Without a user_id the delete still proceeds, scoped to '', but skips
        the on-disk session-dir cleanup (no user dir exists to clean)."""
        mock_repo.delete.return_value = True
        session_dir = AsyncMock()
        cleanup = AsyncMock()
        with (
            patch.object(conversation_service, "delete_session_dir", new=session_dir),
            patch.object(conversation_service, "_cleanup_checkpoint_threads", new=cleanup),
        ):
            result = await delete_conversation("conv_abc", {"email": "test@example.com"})
        assert result.conversation_id == "conv_abc"
        mock_repo.delete.assert_awaited_once_with("conv_abc", user_id="")
        session_dir.assert_not_awaited()
        cleanup.assert_awaited_once_with("conv_abc")

    async def test_raises_404_when_not_found(self, mock_repo, test_user):
        mock_repo.delete.return_value = False
        with pytest.raises(HTTPException) as exc_info:
            await delete_conversation("nonexistent", test_user)
        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "Conversation not found or does not belong to the user"

    async def test_logs_juicefs_unavailable_during_session_cleanup(self, mock_repo, test_user):
        mock_repo.delete.return_value = True
        session_dir = AsyncMock(side_effect=JuiceFSUnavailable("not mounted"))
        with (
            patch.object(conversation_service, "delete_session_dir", new=session_dir),
            patch.object(conversation_service, "_cleanup_checkpoint_threads", new=AsyncMock()),
            patch.object(conversation_service, "log", new=Mock()) as log,
        ):
            result = await delete_conversation("conv_abc", test_user)
        assert result.conversation_id == "conv_abc"
        log.warning.assert_called_once_with(
            "[conversation] juicefs cleanup skipped", error="not mounted"
        )

    async def test_logs_session_dir_cleanup_failure(self, mock_repo, test_user):
        mock_repo.delete.return_value = True
        session_dir = AsyncMock(side_effect=RuntimeError("boom"))
        with (
            patch.object(conversation_service, "delete_session_dir", new=session_dir),
            patch.object(conversation_service, "_cleanup_checkpoint_threads", new=AsyncMock()),
            patch.object(conversation_service, "log", new=Mock()) as log,
        ):
            result = await delete_conversation("conv_abc", test_user)
        assert result.conversation_id == "conv_abc"
        log.warning.assert_called_once_with(
            "[conversation] session dir cleanup failed", error="boom"
        )

    async def test_delete_all_cleans_up_each_conversation(self, mock_repo, decoy_user):
        mock_repo.delete_all_for_user.return_value = ["conv_1", "conv_2"]
        cleanup = AsyncMock()
        with patch.object(conversation_service, "_cleanup_checkpoint_threads", new=cleanup):
            result = await delete_all_conversations(decoy_user)
        assert result.message == "All conversations deleted successfully"
        mock_repo.delete_all_for_user.assert_awaited_once_with("user_123")
        assert cleanup.call_args_list == [call("conv_1"), call("conv_2")]

    async def test_delete_all_raises_404_when_none(self, mock_repo):
        mock_repo.delete_all_for_user.return_value = []
        with pytest.raises(HTTPException) as exc_info:
            await delete_all_conversations({"email": "test@example.com"})
        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "No conversations found for the user"
        # The 404 path still reaches the repository with the caller's id.
        mock_repo.delete_all_for_user.assert_awaited_once_with("")


class TestUpdateDescription:
    async def test_updates(self, mock_repo, decoy_user):
        mock_repo.set_description.return_value = True
        result = await update_conversation_description(
            "conv_abc", "New Description", decoy_user
        )
        assert result.description == "New Description"
        assert result.message == "Conversation description updated successfully"
        assert result.conversation_id == "conv_abc"
        mock_repo.set_description.assert_awaited_once_with(
            "conv_abc", user_id="user_123", description="New Description"
        )

    async def test_raises_404_when_not_found(self, mock_repo, test_user):
        mock_repo.set_description.return_value = False
        with pytest.raises(HTTPException) as exc_info:
            await update_conversation_description("nonexistent", "New Desc", test_user)
        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "Conversation not found or description not updated"

    async def test_defaults_to_empty_user_id(self, mock_repo):
        mock_repo.set_description.return_value = True
        result = await update_conversation_description(
            "conv_abc", "New Description", {"email": "test@example.com"}
        )
        assert result.description == "New Description"
        mock_repo.set_description.assert_awaited_once_with(
            "conv_abc", user_id="", description="New Description"
        )


class TestMarkAsReadUnread:
    async def test_mark_as_read(self, mock_repo, test_user):
        mock_repo.set_unread.return_value = True
        result = await mark_conversation_as_read("conv_abc", test_user)
        assert result.conversation_id == "conv_abc"
        assert result.message == "Conversation marked as read"
        mock_repo.set_unread.assert_awaited_once_with(
            "conv_abc", user_id="user_123", unread=False
        )

    async def test_mark_as_read_rejects_unauthenticated(self, mock_repo):
        with pytest.raises(HTTPException) as exc_info:
            await mark_conversation_as_read("conv_abc", {})
        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == "Not authenticated"

    async def test_mark_as_unread(self, mock_repo, test_user):
        mock_repo.set_unread.return_value = True
        result = await mark_conversation_as_unread("conv_abc", test_user)
        assert result.conversation_id == "conv_abc"
        assert result.message == "Conversation marked as unread"
        mock_repo.set_unread.assert_awaited_once_with(
            "conv_abc", user_id="user_123", unread=True
        )

    async def test_mark_as_unread_rejects_unauthenticated(self, mock_repo):
        with pytest.raises(HTTPException) as exc_info:
            await mark_conversation_as_unread("conv_abc", {})
        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == "Not authenticated"

    async def test_mark_as_unread_raises_404(self, mock_repo, test_user):
        mock_repo.set_unread.return_value = False
        with pytest.raises(HTTPException) as exc_info:
            await mark_conversation_as_unread("conv_abc", test_user)
        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "Conversation not found or update failed"


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
        result = await get_conversations({"user_id": "user_1"}, page=1, limit=10)
        assert mock_repo.list_starred_summaries.call_args[0][0] == "user_1"
        assert mock_repo.list_active_summaries.call_args[0][0] == "user_1"
        assert mock_repo.count_active.call_args[0][0] == "user_1"
        # Zero active conversations is one page, not an empty page.
        assert result.total_pages == 1

    async def test_uses_default_page_and_limit(self, mock_repo):
        mock_repo.list_starred_summaries.return_value = []
        mock_repo.list_active_summaries.return_value = []
        mock_repo.count_active.return_value = 0
        result = await get_conversations({"user_id": "user_1"})
        assert result.page == 1
        assert result.limit == 10
        assert result.total_pages == 1
        mock_repo.list_active_summaries.assert_awaited_once_with("user_1", skip=0, limit=10)

    async def test_total_pages_rounds_up_to_page_boundary(self, mock_repo):
        mock_repo.list_starred_summaries.return_value = []
        mock_repo.list_active_summaries.return_value = []
        mock_repo.count_active.return_value = 10
        result = await get_conversations({"user_id": "user_1"}, page=1, limit=10)
        # 10 items at limit 10 is exactly one page.
        assert result.total_pages == 1

    async def test_total_pages_is_at_least_one(self, mock_repo):
        mock_repo.list_starred_summaries.return_value = []
        mock_repo.list_active_summaries.return_value = []
        mock_repo.count_active.return_value = 1
        result = await get_conversations({"user_id": "user_1"}, page=1, limit=10)
        # 1 item at limit 10 rounds up to one page, never zero.
        assert result.total_pages == 1


class TestUpdateMessages:
    async def test_appends_and_returns_ids(self, mock_repo, test_user):
        mock_repo.append_messages.return_value = ["m1"]
        request = UpdateMessagesRequest(
            conversation_id="conv_abc", messages=[MessageModel(type="user", response="Hi")]
        )
        result = await update_messages(request, test_user, max_messages=50)
        assert result.message_ids == ["m1"]
        assert result.conversation_id == "conv_abc"
        assert result.message == "Messages updated"
        assert result.modified_count == 1
        mock_repo.append_messages.assert_awaited_once_with(
            "conv_abc", user_id="user_123", messages=request.messages, max_messages=50
        )

    async def test_raises_404_when_conversation_missing(self, mock_repo, test_user):
        mock_repo.append_messages.return_value = None
        request = UpdateMessagesRequest(
            conversation_id="missing", messages=[MessageModel(type="user", response="Hi")]
        )
        with pytest.raises(HTTPException) as exc_info:
            await update_messages(request, test_user)
        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "Conversation not found or does not belong to the user"

    async def test_defaults_to_empty_user_id(self, mock_repo):
        mock_repo.append_messages.return_value = ["m1"]
        request = UpdateMessagesRequest(
            conversation_id="conv_abc", messages=[MessageModel(type="user", response="Hi")]
        )
        result = await update_messages(request, {"email": "test@example.com"})
        assert result.message_ids == ["m1"]
        mock_repo.append_messages.assert_awaited_once_with(
            "conv_abc", user_id="", messages=request.messages, max_messages=None
        )


class TestPinMessage:
    async def test_pins_message(self, mock_repo, decoy_user):
        mock_repo.get.return_value = _document(
            messages=[{"type": "bot", "response": "Hello", "message_id": "msg_1"}]
        )
        mock_repo.set_message_pinned.return_value = True
        result = await pin_message("conv_abc", "msg_1", True, decoy_user)
        assert result.pinned is True
        assert result.message == "Message with ID msg_1 pinned successfully"
        mock_repo.get.assert_awaited_once_with("conv_abc", user_id="user_123")
        mock_repo.set_message_pinned.assert_awaited_once_with(
            "conv_abc", user_id="user_123", message_id="msg_1", pinned=True
        )

    async def test_pins_with_missing_user_id(self, mock_repo):
        mock_repo.get.return_value = _document(
            messages=[{"type": "bot", "response": "x", "message_id": "msg_1"}]
        )
        mock_repo.set_message_pinned.return_value = True
        result = await pin_message("conv_abc", "msg_1", True, {"email": "test@example.com"})
        assert result.pinned is True
        mock_repo.get.assert_awaited_once_with("conv_abc", user_id="")
        mock_repo.set_message_pinned.assert_awaited_once_with(
            "conv_abc", user_id="", message_id="msg_1", pinned=True
        )

    async def test_raises_404_conversation_not_found(self, mock_repo, test_user):
        mock_repo.get.return_value = None
        with pytest.raises(HTTPException) as exc_info:
            await pin_message("conv_abc", "msg_1", True, test_user)
        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "Conversation not found"

    async def test_raises_404_message_not_found(self, mock_repo, test_user):
        mock_repo.get.return_value = _document(
            messages=[{"type": "bot", "response": "x", "message_id": "other"}]
        )
        with pytest.raises(HTTPException) as exc_info:
            await pin_message("conv_abc", "missing", True, test_user)
        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "Message not found in conversation"

    async def test_raises_404_when_pin_update_fails(self, mock_repo, test_user):
        mock_repo.get.return_value = _document(
            messages=[{"type": "bot", "response": "x", "message_id": "msg_1"}]
        )
        mock_repo.set_message_pinned.return_value = False
        with pytest.raises(HTTPException) as exc_info:
            await pin_message("conv_abc", "msg_1", True, test_user)
        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "Message not found or update failed"


class TestGetStarredMessages:
    async def test_returns_pinned(self, mock_repo, decoy_user):
        mock_repo.list_pinned_messages.return_value = [
            ConversationMessageHit(
                conversation_id="conv_1",
                message={"type": "bot", "response": "test", "message_id": "m1", "pinned": True},
            )
        ]
        result = await get_starred_messages(decoy_user)
        assert len(result.results) == 1
        assert result.results[0].conversation_id == "conv_1"
        mock_repo.list_pinned_messages.assert_awaited_once_with("user_123")

    async def test_returns_empty_with_missing_user_id(self, mock_repo):
        mock_repo.list_pinned_messages.return_value = []
        result = await get_starred_messages({"email": "test@example.com"})
        assert result.results == []
        mock_repo.list_pinned_messages.assert_awaited_once_with("")


class TestCreateSystemConversation:
    async def test_creates(self, mock_repo):
        mock_repo.create.return_value = _document()
        result = await create_system_conversation(
            "user_123", "Email Actions", SystemPurpose.EMAIL_PROCESSING
        )
        assert result.user_id == "user_123"
        assert result.is_system_generated is True
        assert result.system_purpose == SystemPurpose.EMAIL_PROCESSING
        assert result.description == "Email Actions"
        assert result.detail == "System conversation created successfully"
        # A fresh conversation id, not a sentinel string.
        assert UUID(result.conversation_id)
        document = mock_repo.create.call_args[0][0]
        assert document.conversation_id == result.conversation_id
        assert document.is_system_generated is True and document.is_unread is True
        assert document.description == "Email Actions"
        assert document.system_purpose is SystemPurpose.EMAIL_PROCESSING
        assert document.createdAt is not None
        assert document.createdAt == result.createdAt
        assert document.createdAt.endswith("+00:00")

    async def test_raises_500_on_error(self, mock_repo):
        mock_repo.create.side_effect = Exception("DB error")
        with pytest.raises(HTTPException) as exc_info:
            await create_system_conversation("user_123", "Test", SystemPurpose.OTHER)
        assert exc_info.value.status_code == 500
        assert exc_info.value.detail == "Failed to create system conversation: DB error"


class TestBatchSyncConversations:
    async def test_rejects_unauthenticated(self, mock_repo):
        with pytest.raises(HTTPException) as exc_info:
            await batch_sync_conversations(BatchSyncRequest(conversations=[]), {})
        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == "Not authenticated"

    async def test_returns_empty_for_empty_request(self, mock_repo, test_user):
        result = await batch_sync_conversations(BatchSyncRequest(conversations=[]), test_user)
        assert result.conversations == []
        mock_repo.find_updated_since.assert_not_called()

    async def test_returns_rows_with_all_document_fields(self, mock_repo, test_user):
        updated_at = datetime(2026, 1, 2, 9, 30, tzinfo=UTC)
        mock_repo.find_updated_since.return_value = [
            _document(
                description="Updated Chat",
                starred=True,
                is_system_generated=True,
                is_onboarding_conversation=False,
                system_purpose=SystemPurpose.EMAIL_PROCESSING,
                is_unread=True,
                updatedAt=updated_at,
                messages=[{"type": "bot", "response": "Hello", "message_id": "m1"}],
                artifacts=[{"path": "/tmp/art", "kind": "chart"}],
            )
        ]
        stream = AsyncMock(return_value="stream-1")
        with patch.object(
            conversation_service.stream_manager, "get_resumable_stream_id", new=stream
        ):
            request = BatchSyncRequest(
                conversations=[ConversationSyncItem(conversation_id="conv_abc")]
            )
            result = await batch_sync_conversations(request, test_user)

        assert result == BatchSyncResponse(
            conversations=[
                ConversationSyncRow(
                    conversation_id="conv_abc",
                    description="Updated Chat",
                    starred=True,
                    is_system_generated=True,
                    is_onboarding_conversation=False,
                    system_purpose=SystemPurpose.EMAIL_PROCESSING,
                    is_unread=True,
                    createdAt="2026-01-01T00:00:00+00:00",
                    updatedAt=updated_at,
                    messages=[MessageModel(type="bot", response="Hello", message_id="m1")],
                    artifacts=[{"path": "/tmp/art", "kind": "chart"}],
                    active_stream_id="stream-1",
                )
            ]
        )
        mock_repo.find_updated_since.assert_awaited_once_with(
            "user_123", request.conversations
        )
        stream.assert_awaited_once_with("user_123", "conv_abc")
        # The internal user_id/_id must not leak into a serialized sync row.
        serialized = result.conversations[0].model_dump()
        assert "user_id" not in serialized and "_id" not in serialized
