"""
TEST 9: Database Transaction Consistency.

Verifies that MongoDB-backed services maintain data consistency across
multi-step operations: conversation CRUD, todo creation with subtasks,
message ordering, concurrent updates, partial failure handling, and
bulk operations.

All tests mock at the repository boundary (the typed ``*_repository``
singletons) while exercising real service logic. The repositories return typed
document models, exactly as they do at runtime; assertions target the resulting
data state and the documents handed to the repository, not mock call counts.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from fastapi import HTTPException
import pytest

from app.models.chat_models import (
    ConversationModel,
    MessageModel,
    UpdateMessagesRequest,
)
from app.models.conversation_models import ConversationDocument
from app.models.todo_models import (
    BulkUpdateRequest,
    Priority,
    ProjectDocument,
    SubTask,
    TodoDocument,
    TodoModel,
    TodoUpdate,
    TodoUpdateRequest,
)
from app.services.conversation_service import (
    create_conversation_service,
    delete_all_conversations,
    delete_conversation,
    update_messages,
)
from app.services.todos.todo_service import TodoService
from app.utils.errors import AppError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

USER_ID = "user_txn_test_001"
FAKE_USER: dict[str, Any] = {"user_id": USER_ID}


def _stored_todo(document: TodoDocument, **overrides: Any) -> TodoDocument:
    """Echo a to-be-created ``TodoDocument`` back as the repository would after a
    write: same fields, plus a stored id and creation/update timestamps."""
    now = datetime.now(UTC)
    data = {
        **document.model_dump(),
        "id": overrides.pop("id", str(uuid4())),
        "created_at": now,
        "updated_at": now,
    }
    data.update(overrides)
    return TodoDocument.model_validate(data)


def _inbox_project() -> ProjectDocument:
    return ProjectDocument.model_validate(
        {"id": str(uuid4()), "user_id": USER_ID, "name": "Inbox", "is_default": True}
    )


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

        conversation = ConversationModel(conversation_id=conv_id, description="Hello world")

        with patch(
            "app.services.conversation_service.conversation_repository.create",
            AsyncMock(side_effect=capture_create),
        ):
            result = await create_conversation_service(conversation, FAKE_USER)

        assert result["conversation_id"] == conv_id
        document = captured["document"]
        assert document.user_id == USER_ID
        assert document.conversation_id == conv_id
        assert document.messages == []
        assert document.createdAt is not None

    async def test_create_conversation_unacknowledged_raises(self) -> None:
        """If the repository cannot persist the document, the service must raise 500."""
        conversation = ConversationModel(conversation_id=str(uuid4()), description="Should fail")

        with (
            patch(
                "app.services.conversation_service.conversation_repository.create",
                AsyncMock(side_effect=AppError(message="inserted document could not be read back")),
            ),
            pytest.raises(HTTPException) as exc_info,
        ):
            await create_conversation_service(conversation, FAKE_USER)

        assert exc_info.value.status_code == 500

    async def test_create_conversation_db_error_raises(self) -> None:
        """A repository exception during create must propagate as HTTPException 500."""
        conversation = ConversationModel(conversation_id=str(uuid4()), description="DB down")

        with (
            patch(
                "app.services.conversation_service.conversation_repository.create",
                AsyncMock(side_effect=Exception("connection refused")),
            ),
            pytest.raises(HTTPException) as exc_info,
        ):
            await create_conversation_service(conversation, FAKE_USER)

        assert exc_info.value.status_code == 500
        assert "connection refused" in exc_info.value.detail

    async def test_create_conversation_requires_user_id(self) -> None:
        """Missing user_id in user dict must raise 403."""
        conversation = ConversationModel(conversation_id=str(uuid4()), description="No user")

        with pytest.raises(HTTPException) as exc_info:
            await create_conversation_service(conversation, {})

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

        assert result["conversation_id"] == conv_id
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
                "app.services.conversation_service.conversation_repository.delete_all_for_user",
                mock_delete_all,
            ),
            patch(
                "app.services.conversation_service._cleanup_checkpoint_threads",
                AsyncMock(),
            ),
        ):
            result = await delete_all_conversations(FAKE_USER)

        assert "deleted" in result["message"].lower() or "All" in result["message"]
        assert mock_delete_all.await_args.args[0] == USER_ID

    async def test_delete_all_conversations_none_found_raises(self) -> None:
        """If the user has no conversations, bulk delete must raise 404."""
        with (
            patch(
                "app.services.conversation_service.conversation_repository.delete_all_for_user",
                AsyncMock(return_value=[]),
            ),
            pytest.raises(HTTPException) as exc_info,
        ):
            await delete_all_conversations(FAKE_USER)

        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Todo creation with subtasks
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestTodoCreationWithSubtasks:
    """Verify that creating a todo with subtasks writes parent and children together."""

    async def test_create_todo_with_subtasks_stores_all(self) -> None:
        """Parent todo and all subtasks must reach the repository in a single create."""
        captured: dict[str, TodoDocument] = {}

        async def capture_create(document: TodoDocument) -> TodoDocument:
            captured["document"] = document
            return _stored_todo(document)

        subtasks = [
            SubTask(id=str(uuid4()), title="Step 1"),
            SubTask(id=str(uuid4()), title="Step 2"),
            SubTask(id=str(uuid4()), title="Step 3"),
        ]
        todo = TodoModel(
            title="Parent todo",
            description="With subtasks",
            priority=Priority.HIGH,
            subtasks=subtasks,
        )

        with (
            patch(
                "app.services.todos.todo_service.todo_repository.create",
                AsyncMock(side_effect=capture_create),
            ),
            patch(
                "app.services.todos.todo_service.project_repository.get_or_create_inbox",
                AsyncMock(return_value=_inbox_project()),
            ),
            patch(
                "app.services.workflow.queue_service.WorkflowQueueService."
                "queue_todo_workflow_generation",
                AsyncMock(),
            ),
            patch("app.services.todos.todo_service.store_todo_embedding", AsyncMock()),
            patch("app.services.todos.todo_service.schedule_user_todos_sync", MagicMock()),
        ):
            result = await TodoService.create_todo(todo, USER_ID)

        assert result.title == "Parent todo"
        document = captured["document"]
        assert len(document.subtasks) == 3
        for st in document.subtasks:
            assert st.id, "Subtask must have an ID assigned"
        assert document.user_id == USER_ID

    async def test_create_todo_subtasks_get_ids_when_missing(self) -> None:
        """Subtasks without IDs must receive auto-generated UUIDs before the write."""
        captured: dict[str, TodoDocument] = {}

        async def capture_create(document: TodoDocument) -> TodoDocument:
            captured["document"] = document
            return _stored_todo(document)

        subtasks = [
            SubTask(id="", title="No ID subtask 1"),
            SubTask(id="", title="No ID subtask 2"),
        ]
        todo = TodoModel(title="Auto-ID test", subtasks=subtasks)

        with (
            patch(
                "app.services.todos.todo_service.todo_repository.create",
                AsyncMock(side_effect=capture_create),
            ),
            patch(
                "app.services.todos.todo_service.project_repository.get_or_create_inbox",
                AsyncMock(return_value=_inbox_project()),
            ),
            patch(
                "app.services.workflow.queue_service.WorkflowQueueService."
                "queue_todo_workflow_generation",
                AsyncMock(),
            ),
            patch("app.services.todos.todo_service.store_todo_embedding", AsyncMock()),
            patch("app.services.todos.todo_service.schedule_user_todos_sync", MagicMock()),
        ):
            await TodoService.create_todo(todo, USER_ID)

        for st in captured["document"].subtasks:
            assert st.id, "Service must assign IDs to subtasks that lack them"


# ---------------------------------------------------------------------------
# Concurrent conversation updates
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestConcurrentConversationUpdates:
    """Verify that concurrent message additions both succeed (last-write-wins is fine)."""

    async def test_concurrent_message_updates_both_succeed(self) -> None:
        """Two concurrent update_messages calls on the same conversation must both complete."""
        conv_id = str(uuid4())
        append_count = 0

        async def mock_append(conversation_id: str, **kwargs: Any) -> list[str]:
            nonlocal append_count
            await asyncio.sleep(0.01)  # simulate slight latency
            append_count += 1
            return [str(uuid4())]

        msg_a = MessageModel(type="user", response="Message A")
        msg_b = MessageModel(type="user", response="Message B")
        req_a = UpdateMessagesRequest(conversation_id=conv_id, messages=[msg_a])
        req_b = UpdateMessagesRequest(conversation_id=conv_id, messages=[msg_b])

        with patch(
            "app.services.conversation_service.conversation_repository.append_messages",
            AsyncMock(side_effect=mock_append),
        ):
            results = await asyncio.gather(
                update_messages(req_a, FAKE_USER),
                update_messages(req_b, FAKE_USER),
            )

        assert append_count == 2
        assert all(r["message"] == "Messages updated" for r in results)

    async def test_concurrent_update_one_fails_one_succeeds(self) -> None:
        """If one of two concurrent updates targets a missing conversation, the other still succeeds."""
        conv_id = str(uuid4())
        call_count = 0

        async def alternating_append(conversation_id: str, **kwargs: Any) -> list[str] | None:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return None  # conversation not found
            return [str(uuid4())]

        msg_a = MessageModel(type="user", response="Will fail")
        msg_b = MessageModel(type="user", response="Will succeed")
        req_a = UpdateMessagesRequest(conversation_id=conv_id, messages=[msg_a])
        req_b = UpdateMessagesRequest(conversation_id=conv_id, messages=[msg_b])

        with patch(
            "app.services.conversation_service.conversation_repository.append_messages",
            AsyncMock(side_effect=alternating_append),
        ):
            results = await asyncio.gather(
                update_messages(req_a, FAKE_USER),
                update_messages(req_b, FAKE_USER),
                return_exceptions=True,
            )

        exceptions = [r for r in results if isinstance(r, HTTPException)]
        successes = [r for r in results if isinstance(r, dict)]
        assert len(exceptions) == 1
        assert len(successes) == 1
        assert exceptions[0].status_code == 404


# ---------------------------------------------------------------------------
# Message delegation
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestMessageOrdering:
    """Verify the service forwards messages to the repository in order and surfaces its ids.

    Insertion ordering and id assignment now live inside the repository and are
    asserted end-to-end against real Mongo in
    ``tests/contracts/test_conversations_repository.py::TestMessages::test_append_returns_ids_and_persists``.
    """

    async def test_forwards_all_messages_in_order(self) -> None:
        """Every message must reach append_messages, in the request's order."""
        conv_id = str(uuid4())
        captured: dict[str, list[MessageModel]] = {}

        async def capture_append(
            conversation_id: str, *, user_id: str, messages: list[MessageModel], **kwargs: Any
        ) -> list[str]:
            captured["messages"] = messages
            return [str(uuid4()) for _ in messages]

        messages = [MessageModel(type="user", response=f"msg-{i}") for i in range(5)]
        request = UpdateMessagesRequest(conversation_id=conv_id, messages=messages)

        with patch(
            "app.services.conversation_service.conversation_repository.append_messages",
            AsyncMock(side_effect=capture_append),
        ):
            await update_messages(request, FAKE_USER)

        assert [m.response for m in captured["messages"]] == [f"msg-{i}" for i in range(5)]

    async def test_returns_message_ids_from_repository(self) -> None:
        """The ids the repository assigns must be surfaced in the response."""
        conv_id = str(uuid4())
        assigned_ids = [str(uuid4())]

        messages = [MessageModel(type="bot", response="hello")]
        request = UpdateMessagesRequest(conversation_id=conv_id, messages=messages)

        with patch(
            "app.services.conversation_service.conversation_repository.append_messages",
            AsyncMock(return_value=assigned_ids),
        ):
            result = await update_messages(request, FAKE_USER)

        assert result["message_ids"] == assigned_ids


# ---------------------------------------------------------------------------
# Partial failure handling
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestPartialFailureHandling:
    """Verify services handle repository-level failures gracefully."""

    async def test_conversation_insert_failure_does_not_leave_orphan(self) -> None:
        """If the repository create throws, the service must raise and call create exactly once."""
        mock_create = AsyncMock(side_effect=Exception("disk full"))
        conversation = ConversationModel(conversation_id=str(uuid4()), description="Will fail")

        with (
            patch("app.services.conversation_service.conversation_repository.create", mock_create),
            pytest.raises(HTTPException),
        ):
            await create_conversation_service(conversation, FAKE_USER)

        assert mock_create.await_count == 1

    async def test_todo_create_with_project_validation_failure(self) -> None:
        """If the referenced project does not exist, the todo must not be created."""
        fake_project_id = str(uuid4())
        todo = TodoModel(title="Orphan attempt", project_id=fake_project_id)
        mock_create = AsyncMock()

        with (
            patch(
                "app.services.todos.todo_service.project_repository.get",
                AsyncMock(return_value=None),
            ),
            patch("app.services.todos.todo_service.todo_repository.create", mock_create),
            pytest.raises(ValueError, match="not found"),
        ):
            await TodoService.create_todo(todo, USER_ID)

        mock_create.assert_not_called()

    async def test_todo_delete_nonexistent_raises(self) -> None:
        """Deleting a todo that does not exist must raise ValueError."""
        with (
            patch(
                "app.services.todos.todo_service.todo_repository.get",
                AsyncMock(return_value=None),
            ),
            pytest.raises(ValueError, match="not found"),
        ):
            await TodoService.delete_todo(str(uuid4()), USER_ID)


# ---------------------------------------------------------------------------
# Bulk operations
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestBulkOperations:
    """Verify bulk todo operations maintain count consistency."""

    async def test_bulk_delete_count_matches(self) -> None:
        """Bulk delete must report the correct number of deleted items."""
        todo_ids = [str(uuid4()) for _ in range(5)]
        owned = [
            TodoDocument.model_validate({"id": tid, "user_id": USER_ID, "title": f"T{i}"})
            for i, tid in enumerate(todo_ids)
        ]

        with (
            patch(
                "app.services.todos.todo_service.todo_repository.find_by_ids",
                AsyncMock(return_value=owned),
            ),
            patch(
                "app.services.todos.todo_service.todo_repository.bulk_delete",
                AsyncMock(return_value=5),
            ),
            patch("app.services.todos.todo_service.delete_todo_embedding", AsyncMock()),
            patch("app.services.todos.todo_service.schedule_user_todos_sync", MagicMock()),
        ):
            result = await TodoService.bulk_delete_todos(todo_ids, USER_ID)

        assert result.total == 5
        assert len(result.success) == 5
        assert len(result.failed) == 0

    async def test_bulk_delete_partial_ownership(self) -> None:
        """If the user owns only 3 of 5 requested todos, only 3 must be deleted."""
        todo_ids = [str(uuid4()) for _ in range(5)]
        owned = [
            TodoDocument.model_validate({"id": tid, "user_id": USER_ID, "title": f"T{i}"})
            for i, tid in enumerate(todo_ids[:3])
        ]

        with (
            patch(
                "app.services.todos.todo_service.todo_repository.find_by_ids",
                AsyncMock(return_value=owned),
            ),
            patch(
                "app.services.todos.todo_service.todo_repository.bulk_delete",
                AsyncMock(return_value=3),
            ),
            patch("app.services.todos.todo_service.delete_todo_embedding", AsyncMock()),
            patch("app.services.todos.todo_service.schedule_user_todos_sync", MagicMock()),
        ):
            result = await TodoService.bulk_delete_todos(todo_ids, USER_ID)

        assert result.total == 5
        assert len(result.success) == 3
        assert "3" in result.message

    async def test_bulk_update_applies_to_all(self) -> None:
        """Bulk update must apply the priority to all matching todos via a typed update."""
        todo_ids = [str(uuid4()) for _ in range(4)]
        updated = [
            TodoDocument.model_validate(
                {"id": tid, "user_id": USER_ID, "title": f"Todo {i}", "priority": Priority.HIGH}
            )
            for i, tid in enumerate(todo_ids)
        ]
        mock_bulk_update = AsyncMock(return_value=4)

        request = BulkUpdateRequest(
            todo_ids=todo_ids,
            updates=TodoUpdateRequest(priority=Priority.HIGH),
        )

        with (
            patch("app.services.todos.todo_service.todo_repository.bulk_update", mock_bulk_update),
            patch(
                "app.services.todos.todo_service.todo_repository.find_by_ids",
                AsyncMock(return_value=updated),
            ),
            patch("app.services.todos.todo_service.update_todo_embedding", AsyncMock()),
            patch("app.services.todos.todo_service.schedule_user_todos_sync", MagicMock()),
        ):
            result = await TodoService.bulk_update_todos(request, USER_ID)

        assert result.total == 4
        assert "4" in result.message
        # The repository receives a typed TodoUpdate carrying the priority change.
        applied_update = mock_bulk_update.await_args.args[2]
        assert isinstance(applied_update, TodoUpdate)
        assert applied_update.priority == Priority.HIGH
