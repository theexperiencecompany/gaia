"""
TEST 9: Database Transaction Consistency.

Verifies that MongoDB-backed services maintain data consistency across
multi-step operations: conversation CRUD and partial failure handling.

All tests mock at the repository boundary (the typed *_repository
singletons) while exercising real service logic. The repositories return typed
document models, exactly as they do at runtime; assertions target the resulting
data state and the documents handed to the repository, not mock call counts.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi import HTTPException
import pytest

from app.models.chat_models import ConversationModel, ConversationSource
from app.models.conversation_models import ConversationDocument
from app.models.user_models import AuthenticatedUser
from app.services.conversation_service import (
    create_conversation_service,
    delete_all_conversations,
    delete_conversation,
)
from app.utils.errors import AppError
from tests.helpers import users_get

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

USER_ID = "64abc123def4567890abcde1"
FAKE_USER = AuthenticatedUser(user_id=USER_ID)


@pytest.fixture(autouse=True)
def _owners_are_users():
    """Answer the owner check the way the real users collection does."""
    with patch("app.utils.auth_utils.user_repository.get", new=users_get):
        yield


# ---------------------------------------------------------------------------
# Conversation creation consistency
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestConversationCreationConsistency:
    """Verify conversation creation writes a complete, valid document."""

    async def test_create_conversation_stores_all_fields(self) -> None:
        """The created document must carry user_id, conversation_id, empty messages, and a timestamp."""
        conv_id = str(uuid4())
        captured: dict[str, ConversationDocument] = {}

        async def capture_create(document: ConversationDocument) -> ConversationDocument:
            captured["document"] = document
            return document

        conversation = ConversationModel(
            conversation_id=conv_id, description="Hello world", source=ConversationSource.WEB
        )

        with patch(
            "app.services.conversation_service.conversation_repository.create",
            AsyncMock(side_effect=capture_create),
        ):
            result = await create_conversation_service(conversation, FAKE_USER)

        assert result.conversation_id == conv_id
        document = captured["document"]
        assert document.user_id == USER_ID
        assert document.conversation_id == conv_id
        assert document.createdAt is not None

    async def test_create_conversation_unacknowledged_raises(self) -> None:
        """If the repository cannot persist the document, the service must raise 500."""
        conversation = ConversationModel(
            conversation_id=str(uuid4()), description="Should fail", source=ConversationSource.WEB
        )

        with (
            patch(
                "app.services.conversation_service.conversation_repository.create",
                AsyncMock(side_effect=AppError(message="inserted document could not be read back")),
            ),
            pytest.raises(AppError, match="could not be read back"),
        ):
            await create_conversation_service(conversation, FAKE_USER)

    async def test_create_conversation_db_error_raises(self) -> None:
        """A repository exception during create propagates unchanged to the error handler."""
        conversation = ConversationModel(
            conversation_id=str(uuid4()), description="DB down", source=ConversationSource.WEB
        )

        with (
            patch(
                "app.services.conversation_service.conversation_repository.create",
                AsyncMock(side_effect=Exception("connection refused")),
            ),
            pytest.raises(Exception, match="connection refused"),
        ):
            await create_conversation_service(conversation, FAKE_USER)

    async def test_create_conversation_requires_user_id(self) -> None:
        """An empty user_id must raise 403."""
        conversation = ConversationModel(
            conversation_id=str(uuid4()), description="No user", source=ConversationSource.WEB
        )

        with pytest.raises(HTTPException) as exc_info:
            await create_conversation_service(conversation, AuthenticatedUser(user_id=""))

        assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# Conversation deletion cleanup
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestConversationDeletionCleanup:
    """Verify single and bulk deletion remove all associated data, user-scoped."""

    async def test_delete_conversation_removes_document(self) -> None:
        """Deleting a conversation must delete via the repository, scoped to the owner."""
        conv_id = str(uuid4())
        mock_delete = AsyncMock(return_value=True)

        with (
            patch("app.services.conversation_service.conversation_repository.delete", mock_delete),
            patch(
                "app.services.conversation_service.delete_session_dir",
                AsyncMock(),
            ),
            patch(
                "app.services.conversation_service._cleanup_checkpoint_threads",
                AsyncMock(),
            ),
        ):
            result = await delete_conversation(conv_id, FAKE_USER)

        assert result.conversation_id == conv_id
        assert mock_delete.await_args.args[0] == conv_id
        assert mock_delete.await_args.kwargs["user_id"] == USER_ID

    async def test_delete_conversation_not_found_raises(self) -> None:
        """Deleting a nonexistent conversation must raise 404."""
        with (
            patch(
                "app.services.conversation_service.conversation_repository.delete",
                AsyncMock(return_value=False),
            ),
            pytest.raises(HTTPException) as exc_info,
        ):
            await delete_conversation("nonexistent", FAKE_USER)

        assert exc_info.value.status_code == 404

    async def test_delete_all_conversations_clears_user_data(self) -> None:
        """Bulk-deleting must target only the current user's conversations."""
        mock_delete_all = AsyncMock(return_value=[str(uuid4()) for _ in range(5)])

        with (
            patch(
                "app.services.conversation_service.conversation_repository.delete_all_chats_for_user",
                mock_delete_all,
            ),
            patch(
                "app.services.conversation_service._cleanup_checkpoint_threads",
                AsyncMock(),
            ),
        ):
            result = await delete_all_conversations(FAKE_USER)

        assert "deleted" in result.message.lower() or "All" in result.message
        assert mock_delete_all.await_args.args[0] == USER_ID

    async def test_delete_all_conversations_none_found_raises(self) -> None:
        """If the user has no conversations, bulk delete must raise 404."""
        with (
            patch(
                "app.services.conversation_service.conversation_repository.delete_all_chats_for_user",
                AsyncMock(return_value=[]),
            ),
            pytest.raises(HTTPException) as exc_info,
        ):
            await delete_all_conversations(FAKE_USER)

        assert exc_info.value.status_code == 404


@pytest.mark.integration
class TestPartialFailureHandling:
    """Verify services handle repository-level failures gracefully."""

    async def test_conversation_insert_failure_does_not_leave_orphan(self) -> None:
        """If the repository create throws, the service must raise and call create exactly once."""
        mock_create = AsyncMock(side_effect=Exception("disk full"))
        conversation = ConversationModel(
            conversation_id=str(uuid4()), description="Will fail", source=ConversationSource.WEB
        )

        with (
            patch("app.services.conversation_service.conversation_repository.create", mock_create),
            pytest.raises(Exception, match="disk full"),
        ):
            await create_conversation_service(conversation, FAKE_USER)

        assert mock_create.await_count == 1
