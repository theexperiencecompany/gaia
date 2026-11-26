"""Unit tests for the conversation service layer.

The service is functional; it orchestrates conversation_repository and maps
its results to HTTP responses. Per the repository-layer contract, these tests
mock the repository singleton (never the DB) and assert the service's own
behaviour — auth guards, 404 mapping, response shapes, and that each function
delegates to the right repository method with the caller's user_id. The
repository's own behaviour (user-scoping, source persistence, message stripping,
pin semantics) is covered by the real-DB contract suite.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import UUID

from fastapi import HTTPException
import pytest

from app.config.settings import settings
from app.db.repositories.short_links import short_link_repository
from app.models.chat_models import (
    BatchSyncRequest,
    ConversationModel,
    ConversationSource,
    ConversationSyncItem,
    SystemPurpose,
)
from app.models.conversation_frame_models import EntryFrame
from app.models.conversation_log_models import Reply, UserMessage
from app.models.conversation_models import (
    ConversationMessageHit,
    ConversationSummary,
    LogPage,
    StoredConversation,
)
from app.models.short_link_models import RecordTarget, ShortLink, ShortLinkTargetType
from app.models.user_models import AuthenticatedUser
from app.services import conversation_service
from app.services.conversation.screen_patches import ScreenTracker
from app.services.conversation_service import (
    batch_sync_conversations,
    create_conversation_service,
    create_system_conversation,
    delete_all_conversations,
    delete_conversation,
    delete_todo_conversations,
    get_conversation,
    get_conversations,
    get_entries_before,
    get_or_create_todo_conversation,
    get_starred_messages,
    mark_conversation_as_read,
    mark_conversation_as_unread,
    pin_message,
    require_owned_conversation,
    star_conversation,
    update_conversation_description,
)
from app.services.links.placeholders import link_placeholder
from app.services.links.urls import build_url
from app.utils.errors import AppError, ConversationIdTakenError, ConversationStoreError
from shared.py.analytics import UserId
from shared.py.analytics.catalog.chat import (
    ChatConversationCreated,
    ChatConversationDeleted,
    ChatConversationRenamed,
    ChatConversationStarred,
    ChatMessagePinned,
    ChatMessageUnpinned,
)
from tests.factories import make_reply_item

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


def _document(**overrides) -> StoredConversation:
    data = {
        "user_id": USER_ID,
        "conversation_id": "conv_abc",
        "source": "web",
        "createdAt": "2026-01-01T00:00:00+00:00",
        "state": {"head": 0, "display": "idle", "work": []},
    }
    data.update(overrides)
    return StoredConversation.model_validate(data)


class TestCreateConversationService:
    async def test_creates_conversation_and_returns_response(self, mock_repo, test_user):
        mock_repo.create.return_value = _document()
        conversation = ConversationModel(
            conversation_id="conv_abc", description="Test Chat", source=ConversationSource.WEB
        )

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
                ConversationModel(conversation_id="c", source=ConversationSource.WEB),
                AuthenticatedUser(user_id=""),
            )
        assert exc_info.value.status_code == 403

    async def test_an_id_another_user_holds_is_refused_as_a_conflict(self, mock_repo, test_user):
        mock_repo.create.side_effect = ConversationIdTakenError(message="taken")
        with pytest.raises(ConversationIdTakenError) as exc_info:
            await create_conversation_service(
                ConversationModel(conversation_id="c", source=ConversationSource.WEB), test_user
            )
        assert exc_info.value.status_code == 409

    async def test_captures_conversation_created(self, mock_repo, test_user):
        mock_repo.create.return_value = _document()
        conversation = ConversationModel(
            conversation_id="conv_abc", description="Test Chat", source=ConversationSource.WEB
        )

        with patch("app.services.conversation_service.capture") as mock_capture:
            await create_conversation_service(conversation, test_user)

        mock_capture.assert_called_once_with(
            UserId(USER_ID),
            ChatConversationCreated(is_system_generated=False, is_onboarding_demo=False),
        )

    async def test_no_capture_on_repository_error(self, mock_repo, test_user):
        mock_repo.create.side_effect = ConversationStoreError(message="DB connection failed")
        with (
            pytest.raises(ConversationStoreError),
            patch("app.services.conversation_service.capture") as mock_capture,
        ):
            await create_conversation_service(
                ConversationModel(conversation_id="c", source=ConversationSource.WEB), test_user
            )
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


class TestTheScreenAPageProjectsTo:
    """The screen a conversation's log page is shown as: its items, its paging, its own conversation."""

    @staticmethod
    def _page(**overrides: object) -> LogPage:
        entry = EntryFrame(
            seq=4,
            at=datetime(2026, 1, 1, tzinfo=UTC),
            entry=UserMessage(id="u4", text="hello", surface=ConversationSource.WEB),
        )
        data: dict[str, object] = {
            "entries": [entry],
            "state": {"head": 4, "display": "idle", "work": []},
            "has_older": True,
            "cursor": 4,
        }
        data.update(overrides)
        return LogPage.model_validate(data)

    async def test_an_older_page_carries_its_items_paging_and_conversation(
        self, mock_repo, test_user
    ):
        mock_repo.read_entries_before.return_value = self._page()
        loads: list[str] = []
        real_load = ScreenTracker.load

        async def load(conversation_id: str, entries: Any) -> ScreenTracker:
            loads.append(conversation_id)
            return await real_load(conversation_id, entries)

        with patch.object(ScreenTracker, "load", load):
            page = await get_entries_before("conv_abc", test_user, before_seq=9, limit=20)

        assert loads == ["conv_abc"]
        assert (page.has_older, page.cursor) == (True, 4)
        assert len(page.items) == 1
        mock_repo.read_entries_before.assert_awaited_once_with(
            "conv_abc", user_id=USER_ID, before_seq=9, limit=20
        )

    async def test_an_older_page_of_someone_elses_conversation_is_not_found(
        self, mock_repo, test_user
    ):
        mock_repo.read_entries_before.return_value = None

        with pytest.raises(HTTPException) as raised:
            await get_entries_before("conv_abc", test_user, before_seq=9, limit=20)

        assert raised.value.status_code == 404
        assert raised.value.detail == "Conversation not found or does not belong to the user"

    async def test_a_loaded_conversation_projects_its_own_page(self, mock_repo, test_user):
        page = self._page()
        mock_repo.get.return_value = _document(
            entries=[frame.model_dump() for frame in page.entries], has_older=True, cursor=4
        )
        loads: list[str] = []
        real_load = ScreenTracker.load

        async def load(conversation_id: str, entries: Any) -> ScreenTracker:
            loads.append(conversation_id)
            return await real_load(conversation_id, entries)

        with patch.object(ScreenTracker, "load", load):
            loaded = await get_conversation("conv_abc", test_user)

        assert loads == ["conv_abc"]
        assert (loaded.has_older, loaded.cursor, len(loaded.items)) == (True, 4, 1)


_LINKED = RecordTarget(type=ShortLinkTargetType.OPENUI_ARTIFACT, id="art_1")
_LINKED_TEXT = f"the plan {link_placeholder(_LINKED)}"
_LINKED_SHOWN = (f"the plan {build_url('ab12cd')}",)


@pytest.fixture
def live_link():
    live = AsyncMock(return_value=ShortLink(slug="ab12cd", user_id=USER_ID, target=_LINKED))
    with patch.object(short_link_repository, "get_live_for_target", live):
        yield live


def _linked_reply_entries() -> list[dict[str, object]]:
    reply = Reply(id="e4", reply_id="r4", attempt_id="a1", text=_LINKED_TEXT)
    return [EntryFrame(seq=4, at=datetime(2026, 1, 1, tzinfo=UTC), entry=reply).model_dump()]


class TestAReplysLinkReachesTheClientResolvedForItsUser:
    """Each read a client renders from resolves the placeholders the log keeps, under the reader's id."""

    async def test_a_loaded_conversation(self, mock_repo, test_user, live_link):
        mock_repo.get.return_value = _document(entries=_linked_reply_entries())
        loaded = await get_conversation("conv_abc", test_user)
        assert [item.bubbles for item in loaded.items] == [_LINKED_SHOWN]
        assert live_link.await_args.args[0] == USER_ID

    async def test_an_older_page(self, mock_repo, test_user, live_link):
        mock_repo.read_entries_before.return_value = LogPage.model_validate(
            {
                "entries": _linked_reply_entries(),
                "state": {"head": 4, "display": "idle", "work": []},
            }
        )
        page = await get_entries_before("conv_abc", test_user, before_seq=9, limit=20)
        assert [item.bubbles for item in page.items] == [_LINKED_SHOWN]
        assert live_link.await_args.args[0] == USER_ID

    async def test_a_synced_row(self, mock_repo, test_user, live_link):
        mock_repo.find_updated_since.return_value = [_document(entries=_linked_reply_entries())]
        request = BatchSyncRequest(conversations=[ConversationSyncItem(conversation_id="conv_abc")])
        result = await batch_sync_conversations(request, test_user)
        assert [item.bubbles for item in result.conversations[0].items] == [_LINKED_SHOWN]
        assert live_link.await_args.args[0] == USER_ID

    async def test_a_pinned_message(self, mock_repo, test_user, live_link):
        mock_repo.list_pinned_messages.return_value = [
            ConversationMessageHit(conversation_id="conv_1", item=make_reply_item(_LINKED_TEXT))
        ]
        result = await get_starred_messages(test_user)
        assert [hit.item.bubbles for hit in result.results] == [_LINKED_SHOWN]
        assert live_link.await_args.args[0] == USER_ID


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


@dataclass
class Leftovers:
    """What outlives a conversation's document, each cleanup patched at its seam."""

    links: AsyncMock
    artifacts: AsyncMock
    sessions: AsyncMock
    threads: AsyncMock
    bot_delivery: AsyncMock

    def cleaned(self) -> list[tuple[object, ...]]:
        """Return the conversations each cleanup ran for, one row per cleanup."""
        return [
            tuple(c.args for c in mock.await_args_list)
            for mock in (self.links, self.artifacts, self.sessions, self.threads, self.bot_delivery)
        ]


@pytest.fixture
def leftovers():
    found = Leftovers(AsyncMock(), AsyncMock(), AsyncMock(), AsyncMock(), AsyncMock())
    with (
        patch.object(conversation_service, "revoke_conversation_links", new=found.links),
        patch.object(
            conversation_service.openui_artifact_repository,
            "delete_for_conversation",
            new=found.artifacts,
        ),
        patch.object(conversation_service, "delete_session_dir", new=found.sessions),
        patch.object(conversation_service, "_cleanup_checkpoint_threads", new=found.threads),
        patch.object(
            conversation_service.bot_session_repository,
            "forget_delivery",
            new=found.bot_delivery,
        ),
    ):
        yield found


class TestDeleteConversation:
    async def test_deletes_single(self, mock_repo, test_user, leftovers):
        mock_repo.delete.return_value = True
        with patch("app.services.conversation_service.capture") as mock_capture:
            result = await delete_conversation("conv_abc", test_user)
        assert (result.conversation_id, result.message) == (
            "conv_abc",
            "Conversation deleted successfully",
        )
        # What outlives the document goes with it: its links, artifacts, session dir and checkpoints.
        assert leftovers.cleaned() == [
            ((USER_ID, "conv_abc"),),
            ((USER_ID, "conv_abc"),),
            ((USER_ID, "conv_abc"),),
            (("conv_abc",),),
            (("conv_abc",),),
        ]
        mock_capture.assert_called_once_with(
            UserId(USER_ID), ChatConversationDeleted(conversation_id="conv_abc")
        )

    async def test_raises_404_when_not_found(self, mock_repo, test_user):
        mock_repo.delete.return_value = False
        with pytest.raises(HTTPException) as exc_info:
            await delete_conversation("nonexistent", test_user)
        assert exc_info.value.status_code == 404

    async def test_delete_all_cleans_up_each_conversation_like_a_single_delete(
        self, mock_repo, test_user, leftovers
    ):
        mock_repo.delete_all_chats_for_user.return_value = ["conv_1", "conv_2"]
        with patch("app.services.conversation_service.capture") as mock_capture:
            result = await delete_all_conversations(test_user)
        assert result.message == "All conversations deleted successfully"
        mock_repo.delete_all_chats_for_user.assert_awaited_once_with(USER_ID)
        owned = ((USER_ID, "conv_1"), (USER_ID, "conv_2"))
        unowned = (("conv_1",), ("conv_2",))
        assert leftovers.cleaned() == [owned, owned, owned, unowned, unowned]
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
        # The server builds each row's link, so a bot's list command never spells the route.
        assert [c.url for c in result.conversations] == [
            f"{settings.FRONTEND_URL}/c/s1",
            f"{settings.FRONTEND_URL}/c/a1",
        ]
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


@pytest.fixture
def mock_log_repo():
    """Patch the log repository a pin amends through."""
    repo = AsyncMock()
    with patch.object(conversation_service, "conversation_log_repository", repo):
        yield repo


class TestPinMessage:
    @pytest.mark.parametrize(
        ("pinned", "event"), [(True, ChatMessagePinned()), (False, ChatMessageUnpinned())]
    )
    async def test_a_pin_amends_the_logged_message_and_is_captured(
        self, mock_repo, mock_log_repo, test_user, pinned, event
    ):
        mock_repo.exists.return_value = True
        mock_log_repo.set_pinned.return_value = True
        with patch("app.services.conversation_service.capture") as mock_capture:
            result = await pin_message("conv_abc", "msg_1", pinned, test_user)
        assert result.pinned is pinned
        mock_repo.exists.assert_awaited_once_with("conv_abc", user_id=USER_ID)
        mock_log_repo.set_pinned.assert_awaited_once_with(
            "conv_abc", user_id=USER_ID, message_id="msg_1", pinned=pinned
        )
        mock_capture.assert_called_once_with(UserId(USER_ID), event)

    async def test_raises_404_conversation_not_found(self, mock_repo, mock_log_repo, test_user):
        mock_repo.exists.return_value = False
        with pytest.raises(HTTPException) as exc_info:
            await pin_message("conv_abc", "msg_1", True, test_user)
        assert exc_info.value.status_code == 404
        mock_log_repo.set_pinned.assert_not_awaited()

    async def test_raises_404_message_not_found(self, mock_repo, mock_log_repo, test_user):
        mock_repo.exists.return_value = True
        mock_log_repo.set_pinned.return_value = False
        with patch("app.services.conversation_service.capture") as mock_capture:
            with pytest.raises(HTTPException) as exc_info:
                await pin_message("conv_abc", "missing", True, test_user)
        assert exc_info.value.status_code == 404
        mock_capture.assert_not_called()


class TestGetStarredMessages:
    async def test_returns_pinned(self, mock_repo, test_user):
        mock_repo.list_pinned_messages.return_value = [
            ConversationMessageHit(conversation_id="conv_1", item=make_reply_item("test"))
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

    async def test_returns_the_rows_without_internal_ids(self, mock_repo, test_user):
        mock_repo.find_updated_since.return_value = [_document(description="Updated Chat")]
        mock_repo.owned_ids.return_value = {"conv_abc"}
        request = BatchSyncRequest(conversations=[ConversationSyncItem(conversation_id="conv_abc")])
        loads: list[str] = []
        real_load = ScreenTracker.load

        async def load(conversation_id: str, entries: Any) -> ScreenTracker:
            loads.append(conversation_id)
            return await real_load(conversation_id, entries)

        with patch.object(ScreenTracker, "load", load):
            result = await batch_sync_conversations(request, test_user)

        # Each row's screen is projected for its own conversation.
        assert loads == ["conv_abc"]

        assert len(result.conversations) == 1
        row = result.conversations[0]
        assert row.conversation_id == "conv_abc"
        # The internal user_id/_id must not leak into a serialized sync row.
        serialized = row.model_dump()
        assert "user_id" not in serialized and "_id" not in serialized

    async def test_flagged_row_reaches_the_client(self, mock_repo, test_user):
        """The sidebar dot reads batch-sync rows: a dropped flag here is a missing dot no frontend mapping can recover."""
        mock_repo.find_updated_since = AsyncMock(return_value=[_document(awaiting_approval=True)])
        request = BatchSyncRequest(conversations=[ConversationSyncItem(conversation_id="conv_abc")])
        result = await batch_sync_conversations(request, test_user)

        (row,) = result.conversations
        assert row.awaiting_approval is True

    async def test_unflagged_row_reads_unset(self, mock_repo, test_user):
        mock_repo.find_updated_since = AsyncMock(return_value=[_document()])
        request = BatchSyncRequest(conversations=[ConversationSyncItem(conversation_id="conv_abc")])
        result = await batch_sync_conversations(request, test_user)

        assert result.conversations[0].awaiting_approval is False

    @pytest.mark.parametrize(
        ("overrides", "listed"),
        [
            ({}, True),
            ({"source": "web"}, True),
            ({"todo_id": "todo-1"}, False),
            ({"source": "telegram"}, False),
        ],
    )
    async def test_a_row_says_whether_the_conversation_list_shows_it(
        self, mock_repo, test_user, overrides: dict[str, str], listed: bool
    ):
        """A client keeps an unlisted chat cached instead of reading its absence from the list as a delete."""
        mock_repo.find_updated_since = AsyncMock(return_value=[_document(**overrides)])
        request = BatchSyncRequest(conversations=[ConversationSyncItem(conversation_id="conv_abc")])
        result = await batch_sync_conversations(request, test_user)

        assert result.conversations[0].listed is listed

    async def test_an_asked_for_chat_the_user_no_longer_owns_comes_back_missing(
        self, mock_repo, test_user
    ):
        """A client drops a deleted chat only when sync names it missing; one it still owns stays."""
        mock_repo.find_updated_since = AsyncMock(return_value=[])
        mock_repo.owned_ids = AsyncMock(return_value={"conv_kept"})
        items = [
            ConversationSyncItem(conversation_id="conv_kept"),
            ConversationSyncItem(conversation_id="conv_gone"),
        ]

        result = await batch_sync_conversations(BatchSyncRequest(conversations=items), test_user)

        assert result.missing == ["conv_gone"]
        mock_repo.find_updated_since.assert_awaited_once_with(USER_ID, items)
        mock_repo.owned_ids.assert_awaited_once_with(USER_ID, ["conv_kept", "conv_gone"])


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
        # A fresh id, and a timezone-aware creation time the list sorts by.
        assert str(UUID(created.conversation_id)) == created.conversation_id
        assert datetime.fromisoformat(created.createdAt).utcoffset() == timedelta(0)

    async def test_the_loser_of_a_creation_race_gets_the_winners_chat(self, mock_repo):
        mock_repo.find_todo_conversation_id.side_effect = [None, "conv-winner"]
        mock_repo.try_create.return_value = False

        conversation_id = await get_or_create_todo_conversation(USER_ID, "todo-1", "Watch")

        assert conversation_id == "conv-winner"
        assert [c.args for c in mock_repo.find_todo_conversation_id.await_args_list] == [
            (USER_ID, "todo-1"),
            (USER_ID, "todo-1"),
        ]

    async def test_a_race_whose_winner_cannot_be_read_fails_loudly(self, mock_repo):
        mock_repo.find_todo_conversation_id.return_value = None
        mock_repo.try_create.return_value = False

        with pytest.raises(RuntimeError, match="todo-1"):
            await get_or_create_todo_conversation(USER_ID, "todo-1", "Watch")

    async def test_deleting_todos_cleans_up_after_each_of_their_chats(self, mock_repo, leftovers):
        mock_repo.delete_for_todos.return_value = ["conv-1", "conv-2"]
        with patch("app.services.conversation_service.capture") as mock_capture:
            await delete_todo_conversations(USER_ID, ["todo-1", "todo-2"])

        mock_repo.delete_for_todos.assert_awaited_once_with(USER_ID, ["todo-1", "todo-2"])
        owned = ((USER_ID, "conv-1"), (USER_ID, "conv-2"))
        unowned = (("conv-1",), ("conv-2",))
        assert leftovers.cleaned() == [owned, owned, owned, unowned, unowned]
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
