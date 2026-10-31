"""Unit tests for the conversation service layer.

The service is functional; it orchestrates conversation_repository and maps
its results to HTTP responses. Per the repository-layer contract, these tests
mock the repository singleton (never the DB) and assert the service's own
behaviour — auth guards, 404 mapping, response shapes, and that each function
delegates to the right repository method with the caller's user_id. The
repository's own behaviour (user-scoping, source persistence, message stripping,
pin semantics) is covered by the real-DB contract suite.
"""

from types import SimpleNamespace
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
from app.models.user_models import AuthenticatedUser
from app.services import conversation_service
from app.services.conversation_service import (
    batch_sync_conversations,
    create_conversation_service,
    create_system_conversation,
    delete_all_conversations,
    delete_conversation,
    delete_todo_conversations,
    get_conversation,
    get_conversations,
    get_or_create_todo_conversation,
    get_starred_messages,
    mark_conversation_as_read,
    mark_conversation_as_unread,
    pin_message,
    require_owned_conversation,
    star_conversation,
    update_conversation_description,
    update_messages,
)
from app.utils.errors import AppError
from shared.py.analytics import UserId
from shared.py.analytics.catalog.chat import (
    ChatConversationCreated,
    ChatConversationDeleted,
    ChatConversationRenamed,
    ChatConversationStarred,
    ChatMessagePinned,
    ChatMessageUnpinned,
)

USER_ID = "6812f0b3c9a14e2b7d5a91cc"


@pytest.fixture
def mock_repo():
    """Patch the repository singleton with an AsyncMock (services mock the repo)."""
    repo = AsyncMock()
    with patch.object(conversation_service, "conversation_repository", repo):
        yield repo


@pytest.fixture
def test_user():
    return AuthenticatedUser(user_id=USER_ID, email="test@example.com")


@pytest.fixture(autouse=True)
def _no_analytics():
    """Neutralize analytics captures for tests not asserting on them.

    capture resolves the PostHog provider at call time, which is not
    registered in this test module's import chain — capture-specific tests
    patch the call explicitly and assert on it.
    """
    with (
        patch("app.services.conversation_service.capture"),
    ):
        yield


def _document(**overrides) -> ConversationDocument:
    data = {
        "user_id": USER_ID,
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
        assert result.user_id == USER_ID
        assert result.detail == "Conversation created successfully"
        # The document handed to the repository carries the caller's user_id + fields.
        document = mock_repo.create.call_args[0][0]
        assert document.user_id == USER_ID
        assert document.conversation_id == "conv_abc"
        assert document.description == "Test Chat"

    async def test_raises_403_when_no_user_id(self, mock_repo):
        with pytest.raises(HTTPException) as exc_info:
            await create_conversation_service(
                ConversationModel(conversation_id="c"), AuthenticatedUser(user_id="")
            )
        assert exc_info.value.status_code == 403

    async def test_raises_500_on_repository_error(self, mock_repo, test_user):
        mock_repo.create.side_effect = Exception("DB connection failed")
        with pytest.raises(HTTPException) as exc_info:
            await create_conversation_service(ConversationModel(conversation_id="c"), test_user)
        assert exc_info.value.status_code == 500

    async def test_captures_conversation_created(self, mock_repo, test_user):
        mock_repo.create.return_value = _document()
        conversation = ConversationModel(conversation_id="conv_abc", description="Test Chat")

        with patch("app.services.conversation_service.capture") as mock_capture:
            await create_conversation_service(conversation, test_user)

        mock_capture.assert_called_once_with(
            UserId(USER_ID),
            ChatConversationCreated(is_system_generated=False, is_onboarding_demo=False),
        )

    async def test_no_capture_on_repository_error(self, mock_repo, test_user):
        mock_repo.create.side_effect = Exception("DB connection failed")
        with (
            pytest.raises(HTTPException),
            patch("app.services.conversation_service.capture") as mock_capture,
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
        assert mock_repo.get.call_args.kwargs["user_id"] == USER_ID

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
        assert mock_repo.set_starred.call_args.kwargs["user_id"] == USER_ID

    async def test_raises_404_when_not_found(self, mock_repo, test_user):
        mock_repo.set_starred.return_value = False
        with pytest.raises(HTTPException) as exc_info:
            await star_conversation("nonexistent", True, test_user)
        assert exc_info.value.status_code == 404

    async def test_captures_conversation_starred(self, mock_repo, test_user):
        mock_repo.set_starred.return_value = True
        with patch("app.services.conversation_service.capture") as mock_capture:
            await star_conversation("conv_abc", True, test_user)
        mock_capture.assert_called_once_with(
            UserId(USER_ID),
            ChatConversationStarred(starred=True, conversation_id="conv_abc"),
        )


class TestDeleteConversation:
    async def test_deletes_single(self, mock_repo, test_user):
        mock_repo.delete.return_value = True
        with (
            patch.object(conversation_service, "delete_session_dir", new=AsyncMock()),
            patch.object(conversation_service, "_cleanup_checkpoint_threads", new=AsyncMock()),
            patch("app.services.conversation_service.capture") as mock_capture,
        ):
            result = await delete_conversation("conv_abc", test_user)
        assert result.conversation_id == "conv_abc"
        mock_capture.assert_called_once_with(
            UserId(USER_ID), ChatConversationDeleted(conversation_id="conv_abc")
        )

    async def test_raises_404_when_not_found(self, mock_repo, test_user):
        mock_repo.delete.return_value = False
        with pytest.raises(HTTPException) as exc_info:
            await delete_conversation("nonexistent", test_user)
        assert exc_info.value.status_code == 404

    async def test_delete_all_cleans_up_each_conversation(self, mock_repo, test_user):
        mock_repo.delete_all_chats_for_user.return_value = ["conv_1", "conv_2"]
        cleanup = AsyncMock()
        with (
            patch.object(conversation_service, "_cleanup_checkpoint_threads", new=cleanup),
            patch("app.services.conversation_service.capture") as mock_capture,
        ):
            result = await delete_all_conversations(test_user)
        assert result.message == "All conversations deleted successfully"
        assert cleanup.await_count == 2
        mock_capture.assert_called_once_with(UserId(USER_ID), ChatConversationDeleted(count=2))

    async def test_delete_all_raises_404_when_none(self, mock_repo, test_user):
        mock_repo.delete_all_chats_for_user.return_value = []
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
        with patch("app.services.conversation_service.capture") as mock_capture:
            await update_conversation_description("conv_abc", "New Description", test_user)
        mock_capture.assert_called_once_with(
            UserId(USER_ID),
            ChatConversationRenamed(conversation_id="conv_abc"),
        )


class TestMarkAsReadUnread:
    async def test_mark_as_read(self, mock_repo, test_user):
        mock_repo.set_unread.return_value = True
        result = await mark_conversation_as_read("conv_abc", test_user)
        assert result.conversation_id == "conv_abc"
        assert mock_repo.set_unread.call_args.kwargs["unread"] is False

    async def test_mark_as_read_rejects_unauthenticated(self, mock_repo):
        with pytest.raises(HTTPException) as exc_info:
            await mark_conversation_as_read("conv_abc", AuthenticatedUser(user_id=""))
        assert exc_info.value.status_code == 403

    async def test_mark_as_unread(self, mock_repo, test_user):
        mock_repo.set_unread.return_value = True
        result = await mark_conversation_as_unread("conv_abc", test_user)
        assert result.conversation_id == "conv_abc"
        assert mock_repo.set_unread.call_args.kwargs["unread"] is True

    async def test_mark_as_unread_rejects_unauthenticated(self, mock_repo):
        with pytest.raises(HTTPException) as exc_info:
            await mark_conversation_as_unread("conv_abc", AuthenticatedUser(user_id=""))
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

        result = await get_conversations(AuthenticatedUser(user_id="user_abc"), page=2, limit=10)

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
        await get_conversations(AuthenticatedUser(user_id="user_1"), page=1, limit=10)
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
        assert mock_repo.append_messages.call_args.kwargs["user_id"] == USER_ID

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
        mock_repo.get.assert_awaited_once_with("conv_abc", user_id=USER_ID)
        mock_repo.set_message_pinned.assert_awaited_once_with(
            "conv_abc", user_id=USER_ID, message_id="msg_1", pinned=True
        )

    async def test_pin_captures_pinned_with_user_id(self, mock_repo, test_user):
        mock_repo.get.return_value = _document(
            messages=[{"type": "bot", "response": "Hello", "message_id": "msg_1"}]
        )
        mock_repo.set_message_pinned.return_value = True
        with patch(
            "app.services.conversation_service.capture",
        ) as mock_capture:
            await pin_message("conv_abc", "msg_1", True, test_user)
        mock_capture.assert_called_once_with(UserId(USER_ID), ChatMessagePinned())

    async def test_unpin_captures_unpinned_with_user_id(self, mock_repo, test_user):
        mock_repo.get.return_value = _document(
            messages=[{"type": "bot", "response": "Hello", "message_id": "msg_1"}]
        )
        mock_repo.set_message_pinned.return_value = True
        with patch(
            "app.services.conversation_service.capture",
        ) as mock_capture:
            await pin_message("conv_abc", "msg_1", False, test_user)
        mock_capture.assert_called_once_with(UserId(USER_ID), ChatMessageUnpinned())

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
        mock_repo.list_pinned_messages.assert_awaited_once_with(USER_ID)

    async def test_returns_empty(self, mock_repo, test_user):
        mock_repo.list_pinned_messages.return_value = []
        result = await get_starred_messages(test_user)
        assert result.results == []


class TestCreateSystemConversation:
    async def test_creates(self, mock_repo):
        mock_repo.create.return_value = _document()
        result = await create_system_conversation(
            USER_ID, "Email Actions", SystemPurpose.EMAIL_PROCESSING
        )
        assert result.user_id == USER_ID
        assert result.is_system_generated is True
        assert result.system_purpose == SystemPurpose.EMAIL_PROCESSING
        document = mock_repo.create.call_args[0][0]
        assert document.is_system_generated is True and document.is_unread is True

    async def test_raises_500_on_error(self, mock_repo):
        mock_repo.create.side_effect = Exception("DB error")
        with pytest.raises(HTTPException) as exc_info:
            await create_system_conversation(USER_ID, "Test", SystemPurpose.OTHER)
        assert exc_info.value.status_code == 500

    async def test_captures_system_conversation_created(self, mock_repo):
        mock_repo.create.return_value = _document()
        with patch("app.services.conversation_service.capture") as mock_capture:
            await create_system_conversation(
                USER_ID, "Email Actions", SystemPurpose.WORKFLOW_EXECUTION
            )
        mock_capture.assert_called_once_with(
            UserId(USER_ID),
            ChatConversationCreated(is_system_generated=True, system_purpose="workflow_execution"),
        )


class TestBatchSyncConversations:
    async def test_rejects_unauthenticated(self, mock_repo):
        with pytest.raises(HTTPException) as exc_info:
            await batch_sync_conversations(
                BatchSyncRequest(conversations=[]), AuthenticatedUser(user_id="")
            )
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

    async def test_flagged_row_reaches_the_client(self, mock_repo, test_user):
        """The sidebar dot reads batch-sync rows: a dropped flag here is a missing dot no frontend mapping can recover."""
        mock_repo.find_updated_since = AsyncMock(return_value=[_document(has_live_approval=True)])
        with patch.object(
            conversation_service.stream_manager,
            "get_resumable_stream_id",
            new=AsyncMock(return_value=None),
        ):
            request = BatchSyncRequest(
                conversations=[ConversationSyncItem(conversation_id="conv_abc")]
            )
            result = await batch_sync_conversations(request, test_user)

        (row,) = result.conversations
        assert row.has_live_approval is True

    async def test_unflagged_row_reads_unset(self, mock_repo, test_user):
        mock_repo.find_updated_since = AsyncMock(return_value=[_document()])
        with patch.object(
            conversation_service.stream_manager,
            "get_resumable_stream_id",
            new=AsyncMock(return_value=None),
        ):
            request = BatchSyncRequest(
                conversations=[ConversationSyncItem(conversation_id="conv_abc")]
            )
            result = await batch_sync_conversations(request, test_user)

        assert result.conversations[0].has_live_approval in (None, False)

    async def test_a_todos_chat_tells_the_client_which_todo_it_belongs_to(
        self, mock_repo, test_user
    ):
        """A client that opened a todo's chat keeps it in its own store; this is how it keeps it out of the list."""
        mock_repo.find_updated_since = AsyncMock(return_value=[_document(todo_id="todo-1")])
        with patch.object(
            conversation_service.stream_manager,
            "get_resumable_stream_id",
            new=AsyncMock(return_value=None),
        ):
            request = BatchSyncRequest(
                conversations=[ConversationSyncItem(conversation_id="conv_abc")]
            )
            result = await batch_sync_conversations(request, test_user)

        assert result.conversations[0].todo_id == "todo-1"


class TestTrackedTodoChat:
    async def test_an_existing_chat_is_returned_without_creating_one(self, mock_repo):
        mock_repo.find_todo_conversation_id.return_value = "conv-existing"

        conversation_id = await get_or_create_todo_conversation(USER_ID, "todo-1", "Watch")

        assert conversation_id == "conv-existing"
        mock_repo.find_todo_conversation_id.assert_awaited_once_with(USER_ID, "todo-1")
        mock_repo.try_create.assert_not_awaited()

    async def test_the_first_use_creates_an_unlisted_chat_bound_to_the_todo(self, mock_repo):
        mock_repo.find_todo_conversation_id.return_value = None
        mock_repo.try_create.return_value = True

        conversation_id = await get_or_create_todo_conversation(
            USER_ID, "todo-1", "Watch the deploy"
        )

        (created,) = mock_repo.try_create.await_args.args
        assert conversation_id == created.conversation_id
        assert (created.user_id, created.todo_id, created.description) == (
            USER_ID,
            "todo-1",
            "Watch the deploy",
        )
        # Never a chat the user has to read: no unread dot, no system section.
        assert created.is_unread is False
        assert created.is_system_generated is False
        assert created.createdAt is not None

    async def test_the_loser_of_a_creation_race_gets_the_winners_chat(self, mock_repo):
        mock_repo.find_todo_conversation_id.side_effect = [None, "conv-winner"]
        mock_repo.try_create.return_value = False

        conversation_id = await get_or_create_todo_conversation(USER_ID, "todo-1", "Watch")

        assert conversation_id == "conv-winner"

    async def test_a_race_whose_winner_cannot_be_read_fails_loudly(self, mock_repo):
        mock_repo.find_todo_conversation_id.return_value = None
        mock_repo.try_create.return_value = False

        with pytest.raises(RuntimeError, match="todo-1"):
            await get_or_create_todo_conversation(USER_ID, "todo-1", "Watch")

    async def test_deleting_todos_cleans_up_after_each_of_their_chats(self, mock_repo):
        mock_repo.delete_for_todos.return_value = ["conv-1", "conv-2"]
        cleanup = AsyncMock()
        sessions = AsyncMock()
        with (
            patch.object(conversation_service, "_cleanup_checkpoint_threads", new=cleanup),
            patch.object(conversation_service, "delete_session_dir", new=sessions),
            patch("app.services.conversation_service.capture") as mock_capture,
        ):
            await delete_todo_conversations(USER_ID, ["todo-1", "todo-2"])

        mock_repo.delete_for_todos.assert_awaited_once_with(USER_ID, ["todo-1", "todo-2"])
        assert [c.args for c in cleanup.await_args_list] == [("conv-1",), ("conv-2",)]
        assert [c.args for c in sessions.await_args_list] == [
            (USER_ID, "conv-1"),
            (USER_ID, "conv-2"),
        ]
        # Not a conversation the user deleted: no chat analytics for it.
        mock_capture.assert_not_called()


class TestRequireOwnedConversation:
    async def test_the_owner_passes(self, owned_conversations: set[tuple[str, str]]) -> None:
        owned_conversations.add(("conv_abc", USER_ID))

        await require_owned_conversation("conv_abc", USER_ID)

    @pytest.mark.parametrize(
        ("conversation_id", "user_id"),
        [("conv_abc", "someone-else"), ("conv_missing", USER_ID)],
    )
    async def test_a_foreign_or_missing_conversation_is_the_same_404(
        self, owned_conversations: set[tuple[str, str]], conversation_id: str, user_id: str
    ) -> None:
        owned_conversations.add(("conv_abc", USER_ID))

        with pytest.raises(AppError) as raised:
            await require_owned_conversation(conversation_id, user_id)

        assert (raised.value.status_code, raised.value.code, raised.value.message) == (
            404,
            "CONVERSATION_NOT_FOUND",
            "Conversation not found",
        )


class TestConversationSizeCap:
    """A chat thread is one Mongo document; past 16MB it can never be written again."""

    async def test_a_chat_append_caps_history_by_default(self, monkeypatch) -> None:
        from app.constants.chat import CONVERSATION_MAX_MESSAGES
        from app.services import conversation_service

        seen: dict[str, object] = {}

        async def record(conversation_id: str, **kwargs: object) -> list[str]:
            seen.update(kwargs)
            return ["m1"]

        monkeypatch.setattr(conversation_service.conversation_repository, "append_messages", record)

        await conversation_service.update_messages(
            UpdateMessagesRequest(
                conversation_id="c1",
                messages=[MessageModel(type="user", message="hi", response="", message_id="m1")],
            ),
            user=SimpleNamespace(user_id="u1"),
        )

        assert seen["max_messages"] == CONVERSATION_MAX_MESSAGES
