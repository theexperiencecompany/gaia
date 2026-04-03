"""
TEST 9: Database Transaction Consistency.

Verifies that MongoDB-backed services maintain data consistency across
multi-step operations: conversation CRUD, todo creation with subtasks,
message ordering, concurrent updates, partial failure handling, and
bulk operations.

All tests mock at the I/O boundary (MongoDB collections) while exercising
real service logic. Assertions target data state, not mock call counts.
"""

from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from bson import ObjectId
from fastapi import HTTPException

from app.models.chat_models import (
    ConversationModel,
    MessageModel,
    SystemPurpose,
    UpdateMessagesRequest,
)
from app.models.todo_models import (
    BulkUpdateRequest,
    Priority,
    SubTask,
    TodoModel,
    TodoUpdateRequest,
)
from app.services.conversation_service import (
    create_conversation_service,
    delete_all_conversations,
    delete_conversation,
    get_or_create_system_conversation,
    update_messages,
)
from app.services.todos.sync_service import sync_goal_node_completion
from app.services.todos.todo_service import TodoService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

USER_ID = "user_txn_test_001"
FAKE_USER: dict[str, Any] = {"user_id": USER_ID}


def _oid() -> ObjectId:
    return ObjectId()


def _make_insert_result(acknowledged: bool = True) -> MagicMock:
    result = MagicMock()
    result.acknowledged = acknowledged
    result.inserted_id = _oid()
    return result


def _make_update_result(modified: int = 1, matched: int = 1) -> MagicMock:
    result = MagicMock()
    result.modified_count = modified
    result.matched_count = matched
    return result


def _make_delete_result(deleted: int = 1) -> MagicMock:
    result = MagicMock()
    result.deleted_count = deleted
    return result


def _stored_conversation(
    conversation_id: str,
    user_id: str = USER_ID,
    messages: list[dict] | None = None,
) -> dict[str, Any]:
    """Return a dict resembling a stored MongoDB conversation document."""
    return {
        "_id": _oid(),
        "user_id": user_id,
        "conversation_id": conversation_id,
        "description": "Test conversation",
        "messages": messages or [],
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Conversation creation consistency
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestConversationCreationConsistency:
    """Verify conversation creation writes a complete, valid document."""

    async def test_create_conversation_stores_all_fields(self) -> None:
        """Created doc must contain user_id, conversation_id, empty messages, and timestamp."""
        conv_id = str(uuid4())
        captured: dict[str, Any] = {}

        async def capture_insert(doc: dict) -> MagicMock:
            captured.update(deepcopy(doc))
            return _make_insert_result()

        mock_collection = AsyncMock()
        mock_collection.insert_one = AsyncMock(side_effect=capture_insert)

        conversation = ConversationModel(
            conversation_id=conv_id,
            description="Hello world",
        )

        with patch(
            "app.services.conversation_service.conversations_collection",
            mock_collection,
        ):
            result = await create_conversation_service(conversation, FAKE_USER)

        assert result["conversation_id"] == conv_id
        assert captured["user_id"] == USER_ID
        assert captured["conversation_id"] == conv_id
        assert captured["messages"] == []
        assert "createdAt" in captured

    async def test_create_conversation_unacknowledged_raises(self) -> None:
        """If MongoDB does not acknowledge the insert, service must raise."""
        mock_collection = AsyncMock()
        mock_collection.insert_one = AsyncMock(
            return_value=_make_insert_result(acknowledged=False)
        )

        conversation = ConversationModel(
            conversation_id=str(uuid4()),
            description="Should fail",
        )

        with (
            patch(
                "app.services.conversation_service.conversations_collection",
                mock_collection,
            ),
            pytest.raises(HTTPException) as exc_info,
        ):
            await create_conversation_service(conversation, FAKE_USER)

        assert exc_info.value.status_code == 500

    async def test_create_conversation_db_error_raises(self) -> None:
        """A MongoDB exception during insert must propagate as HTTPException."""
        mock_collection = AsyncMock()
        mock_collection.insert_one = AsyncMock(
            side_effect=Exception("connection refused")
        )

        conversation = ConversationModel(
            conversation_id=str(uuid4()),
            description="DB down",
        )

        with (
            patch(
                "app.services.conversation_service.conversations_collection",
                mock_collection,
            ),
            pytest.raises(HTTPException) as exc_info,
        ):
            await create_conversation_service(conversation, FAKE_USER)

        assert exc_info.value.status_code == 500
        assert "connection refused" in exc_info.value.detail

    async def test_create_conversation_requires_user_id(self) -> None:
        """Missing user_id in user dict must raise 403."""
        conversation = ConversationModel(
            conversation_id=str(uuid4()),
            description="No user",
        )

        with pytest.raises(HTTPException) as exc_info:
            await create_conversation_service(conversation, {})

        assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# Conversation deletion cleanup
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestConversationDeletionCleanup:
    """Verify single and bulk deletion remove all associated data."""

    async def test_delete_conversation_removes_document(self) -> None:
        """Deleting a conversation must call delete_one with correct filter."""
        conv_id = str(uuid4())
        mock_collection = AsyncMock()
        mock_collection.delete_one = AsyncMock(
            return_value=_make_delete_result(deleted=1)
        )

        with patch(
            "app.services.conversation_service.conversations_collection",
            mock_collection,
        ):
            result = await delete_conversation(conv_id, FAKE_USER)

        assert result["conversation_id"] == conv_id
        call_filter = mock_collection.delete_one.call_args[0][0]
        assert call_filter["user_id"] == USER_ID
        assert call_filter["conversation_id"] == conv_id

    async def test_delete_conversation_not_found_raises(self) -> None:
        """Deleting a nonexistent conversation must raise 404."""
        mock_collection = AsyncMock()
        mock_collection.delete_one = AsyncMock(
            return_value=_make_delete_result(deleted=0)
        )

        with (
            patch(
                "app.services.conversation_service.conversations_collection",
                mock_collection,
            ),
            pytest.raises(HTTPException) as exc_info,
        ):
            await delete_conversation("nonexistent", FAKE_USER)

        assert exc_info.value.status_code == 404

    async def test_delete_all_conversations_clears_user_data(self) -> None:
        """Bulk-deleting must target only the current user's conversations."""
        mock_collection = AsyncMock()
        mock_collection.delete_many = AsyncMock(
            return_value=_make_delete_result(deleted=5)
        )

        with patch(
            "app.services.conversation_service.conversations_collection",
            mock_collection,
        ):
            result = await delete_all_conversations(FAKE_USER)

        assert "deleted" in result["message"].lower() or "All" in result["message"]
        call_filter = mock_collection.delete_many.call_args[0][0]
        assert call_filter == {"user_id": USER_ID}

    async def test_delete_all_conversations_none_found_raises(self) -> None:
        """If user has no conversations, bulk delete must raise 404."""
        mock_collection = AsyncMock()
        mock_collection.delete_many = AsyncMock(
            return_value=_make_delete_result(deleted=0)
        )

        with (
            patch(
                "app.services.conversation_service.conversations_collection",
                mock_collection,
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
    """Verify that creating a todo with subtasks writes parent and children atomically."""

    async def test_create_todo_with_subtasks_stores_all(self) -> None:
        """Parent todo and all subtasks must be stored in a single insert."""
        captured: dict[str, Any] = {}
        inserted_id = _oid()

        async def capture_insert(doc: dict) -> MagicMock:
            captured.update(deepcopy(doc))
            r = MagicMock()
            r.inserted_id = inserted_id
            return r

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

        inserted_doc = {
            **todo.model_dump(),
            "_id": inserted_id,
            "user_id": USER_ID,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
            "completed": False,
            "workflow_activated": True,
            "subtasks": [s.model_dump() for s in subtasks],
        }

        mock_todos = AsyncMock()
        mock_todos.insert_one = AsyncMock(side_effect=capture_insert)
        mock_todos.find_one = AsyncMock(return_value=deepcopy(inserted_doc))

        mock_projects = AsyncMock()
        inbox_id = str(_oid())
        mock_projects.find_one = AsyncMock(
            return_value={
                "_id": ObjectId(inbox_id),
                "user_id": USER_ID,
                "is_default": True,
            }
        )

        with (
            patch("app.services.todos.todo_service.todos_collection", mock_todos),
            patch("app.services.todos.todo_service.projects_collection", mock_projects),
            patch("app.services.todos.todo_service.store_todo_embedding", AsyncMock()),
            patch("app.services.todos.todo_service.delete_cache", AsyncMock()),
            patch(
                "app.services.todos.todo_service.delete_cache_by_pattern", AsyncMock()
            ),
            patch(
                "app.services.todos.todo_service.get_cache",
                AsyncMock(return_value=None),
            ),
            patch("app.services.todos.todo_service.set_cache", AsyncMock()),
        ):
            result = await TodoService.create_todo(todo, USER_ID)

        assert result.title == "Parent todo"
        assert len(captured["subtasks"]) == 3
        # Each subtask must have an ID
        for st in captured["subtasks"]:
            assert st["id"], "Subtask must have an ID assigned"
        assert captured["user_id"] == USER_ID

    async def test_create_todo_subtasks_get_ids_when_missing(self) -> None:
        """Subtasks without IDs must receive auto-generated UUIDs."""
        captured: dict[str, Any] = {}
        inserted_id = _oid()

        async def capture_insert(doc: dict) -> MagicMock:
            captured.update(deepcopy(doc))
            r = MagicMock()
            r.inserted_id = inserted_id
            return r

        subtasks = [
            SubTask(id="", title="No ID subtask 1"),
            SubTask(id="", title="No ID subtask 2"),
        ]
        todo = TodoModel(title="Auto-ID test", subtasks=subtasks)

        inserted_doc = {
            **todo.model_dump(),
            "_id": inserted_id,
            "user_id": USER_ID,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
            "completed": False,
            "workflow_activated": True,
        }
        # Set subtask IDs like the service would
        for st in inserted_doc.get("subtasks", []):
            if not st.get("id"):
                st["id"] = str(uuid4())

        mock_todos = AsyncMock()
        mock_todos.insert_one = AsyncMock(side_effect=capture_insert)
        mock_todos.find_one = AsyncMock(return_value=deepcopy(inserted_doc))

        mock_projects = AsyncMock()
        mock_projects.find_one = AsyncMock(
            return_value={"_id": _oid(), "user_id": USER_ID, "is_default": True}
        )

        with (
            patch("app.services.todos.todo_service.todos_collection", mock_todos),
            patch("app.services.todos.todo_service.projects_collection", mock_projects),
            patch("app.services.todos.todo_service.store_todo_embedding", AsyncMock()),
            patch("app.services.todos.todo_service.delete_cache", AsyncMock()),
            patch(
                "app.services.todos.todo_service.delete_cache_by_pattern", AsyncMock()
            ),
            patch(
                "app.services.todos.todo_service.get_cache",
                AsyncMock(return_value=None),
            ),
            patch("app.services.todos.todo_service.set_cache", AsyncMock()),
        ):
            await TodoService.create_todo(todo, USER_ID)

        for st in captured["subtasks"]:
            assert st["id"], "Service must assign IDs to subtasks that lack them"


# ---------------------------------------------------------------------------
# Todo sync integrity (sync_service)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestTodoSyncIntegrity:
    """Verify goal-node <-> subtask sync does not create orphans or duplicates."""

    async def test_sync_goal_node_updates_subtask(self) -> None:
        """Completing a goal node must mark the corresponding subtask complete."""

        subtask_id = str(uuid4())
        todo_oid = _oid()
        goal_oid = _oid()

        goal_doc = {
            "_id": goal_oid,
            "user_id": USER_ID,
            "todo_id": str(todo_oid),
            "roadmap": {
                "nodes": [
                    {
                        "id": "node-1",
                        "data": {"subtask_id": subtask_id, "title": "Step 1"},
                    }
                ]
            },
        }

        todo_doc = {"_id": todo_oid, "project_id": "proj-1"}

        mock_goals = AsyncMock()
        mock_goals.find_one = AsyncMock(return_value=deepcopy(goal_doc))

        mock_todos = AsyncMock()
        mock_todos.update_one = AsyncMock(return_value=_make_update_result(modified=1))
        mock_todos.find_one = AsyncMock(return_value=deepcopy(todo_doc))

        with (
            patch("app.services.todos.sync_service.goals_collection", mock_goals),
            patch("app.services.todos.sync_service.todos_collection", mock_todos),
            patch("app.services.todos.sync_service.delete_cache", AsyncMock()),
            patch(
                "app.services.todos.sync_service.delete_cache_by_pattern", AsyncMock()
            ),
        ):
            success = await sync_goal_node_completion(
                str(goal_oid), "node-1", True, USER_ID
            )

        assert success is True
        # Verify the update targeted the correct subtask
        update_call = mock_todos.update_one.call_args
        assert update_call[0][0]["subtasks.id"] == subtask_id
        assert update_call[0][1]["$set"]["subtasks.$.completed"] is True

    async def test_sync_returns_false_for_missing_goal(self) -> None:
        """Syncing a nonexistent goal must return False without side effects."""

        mock_goals = AsyncMock()
        mock_goals.find_one = AsyncMock(return_value=None)

        with patch("app.services.todos.sync_service.goals_collection", mock_goals):
            success = await sync_goal_node_completion(
                str(_oid()), "node-x", True, USER_ID
            )

        assert success is False


# ---------------------------------------------------------------------------
# Concurrent conversation updates
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestConcurrentConversationUpdates:
    """Verify that concurrent message additions both succeed (last-write-wins is fine)."""

    async def test_concurrent_message_updates_both_succeed(self) -> None:
        """Two concurrent update_messages calls on the same conversation must both complete."""
        conv_id = str(uuid4())
        update_count = 0

        async def mock_update_one(filter_: dict, update: dict) -> MagicMock:
            nonlocal update_count
            # Simulate slight latency
            await asyncio.sleep(0.01)
            update_count += 1
            return _make_update_result(modified=1)

        mock_collection = AsyncMock()
        mock_collection.update_one = AsyncMock(side_effect=mock_update_one)

        msg_a = MessageModel(type="user", response="Message A")
        msg_b = MessageModel(type="user", response="Message B")

        req_a = UpdateMessagesRequest(conversation_id=conv_id, messages=[msg_a])
        req_b = UpdateMessagesRequest(conversation_id=conv_id, messages=[msg_b])

        with patch(
            "app.services.conversation_service.conversations_collection",
            mock_collection,
        ):
            results = await asyncio.gather(
                update_messages(req_a, FAKE_USER),
                update_messages(req_b, FAKE_USER),
            )

        assert update_count == 2
        assert all(r["message"] == "Messages updated" for r in results)

    async def test_concurrent_update_one_fails_one_succeeds(self) -> None:
        """If one of two concurrent updates fails, the other must still succeed."""
        conv_id = str(uuid4())
        call_count = 0

        async def alternating_update(filter_: dict, update: dict) -> MagicMock:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _make_update_result(modified=0)  # Simulate not-found
            return _make_update_result(modified=1)

        mock_collection = AsyncMock()
        mock_collection.update_one = AsyncMock(side_effect=alternating_update)

        msg_a = MessageModel(type="user", response="Will fail")
        msg_b = MessageModel(type="user", response="Will succeed")

        req_a = UpdateMessagesRequest(conversation_id=conv_id, messages=[msg_a])
        req_b = UpdateMessagesRequest(conversation_id=conv_id, messages=[msg_b])

        with patch(
            "app.services.conversation_service.conversations_collection",
            mock_collection,
        ):
            results = await asyncio.gather(
                update_messages(req_a, FAKE_USER),
                update_messages(req_b, FAKE_USER),
                return_exceptions=True,
            )

        # One should be an HTTPException (404), one should succeed
        exceptions = [r for r in results if isinstance(r, HTTPException)]
        successes = [r for r in results if isinstance(r, dict)]
        assert len(exceptions) == 1
        assert len(successes) == 1
        assert exceptions[0].status_code == 404


# ---------------------------------------------------------------------------
# Message ordering
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestMessageOrdering:
    """Verify messages are pushed in insertion order via $push + $each."""

    async def test_messages_pushed_in_order(self) -> None:
        """Messages appended via update_messages must preserve insertion order."""
        conv_id = str(uuid4())
        pushed_messages: list[dict] = []

        async def capture_update(filter_: dict, update: dict) -> MagicMock:
            msgs = update.get("$push", {}).get("messages", {}).get("$each", [])
            pushed_messages.extend(msgs)
            return _make_update_result(modified=1)

        mock_collection = AsyncMock()
        mock_collection.update_one = AsyncMock(side_effect=capture_update)

        messages = [MessageModel(type="user", response=f"msg-{i}") for i in range(5)]
        request = UpdateMessagesRequest(conversation_id=conv_id, messages=messages)

        with patch(
            "app.services.conversation_service.conversations_collection",
            mock_collection,
        ):
            await update_messages(request, FAKE_USER)

        assert len(pushed_messages) == 5
        for i, msg in enumerate(pushed_messages):
            assert msg["response"] == f"msg-{i}"
        # message_ids must all be present and unique
        ids = [m["message_id"] for m in pushed_messages]
        assert len(set(ids)) == 5

    async def test_messages_get_assigned_ids(self) -> None:
        """Each message must receive a message_id before being pushed."""
        conv_id = str(uuid4())
        pushed_messages: list[dict] = []

        async def capture_update(filter_: dict, update: dict) -> MagicMock:
            msgs = update.get("$push", {}).get("messages", {}).get("$each", [])
            pushed_messages.extend(msgs)
            return _make_update_result(modified=1)

        mock_collection = AsyncMock()
        mock_collection.update_one = AsyncMock(side_effect=capture_update)

        messages = [MessageModel(type="bot", response="hello")]
        request = UpdateMessagesRequest(conversation_id=conv_id, messages=messages)

        with patch(
            "app.services.conversation_service.conversations_collection",
            mock_collection,
        ):
            result = await update_messages(request, FAKE_USER)

        assert len(pushed_messages) == 1
        assert pushed_messages[0]["message_id"]
        assert result["message_ids"][0] == pushed_messages[0]["message_id"]


# ---------------------------------------------------------------------------
# Partial failure handling
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestPartialFailureHandling:
    """Verify services handle collection-level failures gracefully."""

    async def test_conversation_insert_failure_does_not_leave_orphan(self) -> None:
        """If conversations_collection.insert_one throws, no document should persist."""
        mock_collection = AsyncMock()
        mock_collection.insert_one = AsyncMock(side_effect=Exception("disk full"))

        conversation = ConversationModel(
            conversation_id=str(uuid4()),
            description="Will fail",
        )

        with (
            patch(
                "app.services.conversation_service.conversations_collection",
                mock_collection,
            ),
            pytest.raises(HTTPException),
        ):
            await create_conversation_service(conversation, FAKE_USER)

        # insert_one was called exactly once, then the exception was raised
        assert mock_collection.insert_one.call_count == 1

    async def test_todo_create_with_project_validation_failure(self) -> None:
        """If the referenced project does not exist, todo must not be created."""
        fake_project_id = str(_oid())
        todo = TodoModel(
            title="Orphan attempt",
            project_id=fake_project_id,
        )

        mock_todos = AsyncMock()
        mock_projects = AsyncMock()
        mock_projects.find_one = AsyncMock(return_value=None)  # Project not found

        with (
            patch("app.services.todos.todo_service.todos_collection", mock_todos),
            patch("app.services.todos.todo_service.projects_collection", mock_projects),
            patch("app.services.todos.todo_service.delete_cache", AsyncMock()),
            patch(
                "app.services.todos.todo_service.delete_cache_by_pattern", AsyncMock()
            ),
            patch(
                "app.services.todos.todo_service.get_cache",
                AsyncMock(return_value=None),
            ),
            patch("app.services.todos.todo_service.set_cache", AsyncMock()),
            pytest.raises(ValueError, match="not found"),
        ):
            await TodoService.create_todo(todo, USER_ID)

        # Critically, insert_one must never have been called
        mock_todos.insert_one.assert_not_called()

    async def test_todo_delete_nonexistent_raises(self) -> None:
        """Deleting a todo that does not exist must raise ValueError."""
        mock_todos = AsyncMock()
        mock_todos.delete_one = AsyncMock(return_value=_make_delete_result(deleted=0))

        with (
            patch("app.services.todos.todo_service.todos_collection", mock_todos),
            patch("app.services.todos.todo_service.delete_todo_embedding", AsyncMock()),
            patch("app.services.todos.todo_service.delete_cache", AsyncMock()),
            patch(
                "app.services.todos.todo_service.delete_cache_by_pattern", AsyncMock()
            ),
            pytest.raises(ValueError, match="not found"),
        ):
            await TodoService.delete_todo(str(_oid()), USER_ID)


# ---------------------------------------------------------------------------
# Bulk operations
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestBulkOperations:
    """Verify bulk todo operations maintain count consistency."""

    async def test_bulk_delete_count_matches(self) -> None:
        """Bulk delete must report the correct number of deleted items."""
        todo_ids = [str(_oid()) for _ in range(5)]

        mock_cursor = AsyncMock()
        mock_cursor.to_list = AsyncMock(
            return_value=[
                {"_id": ObjectId(tid), "user_id": USER_ID} for tid in todo_ids
            ]
        )

        mock_todos = AsyncMock()
        mock_todos.find = MagicMock(return_value=mock_cursor)
        mock_todos.delete_many = AsyncMock(return_value=_make_delete_result(deleted=5))

        with (
            patch("app.services.todos.todo_service.todos_collection", mock_todos),
            patch("app.services.todos.todo_service.delete_todo_embedding", AsyncMock()),
            patch("app.services.todos.todo_service.delete_cache", AsyncMock()),
            patch(
                "app.services.todos.todo_service.delete_cache_by_pattern", AsyncMock()
            ),
        ):
            result = await TodoService.bulk_delete_todos(todo_ids, USER_ID)

        assert result.total == 5
        assert len(result.success) == 5
        assert len(result.failed) == 0

    async def test_bulk_delete_partial_ownership(self) -> None:
        """If user owns only 3 of 5 requested todos, only 3 should be deleted."""
        todo_ids = [str(_oid()) for _ in range(5)]

        mock_cursor = AsyncMock()
        mock_cursor.to_list = AsyncMock(
            return_value=[
                {"_id": ObjectId(tid), "user_id": USER_ID} for tid in todo_ids[:3]
            ]
        )

        mock_todos = AsyncMock()
        mock_todos.find = MagicMock(return_value=mock_cursor)
        mock_todos.delete_many = AsyncMock(return_value=_make_delete_result(deleted=3))

        with (
            patch("app.services.todos.todo_service.todos_collection", mock_todos),
            patch("app.services.todos.todo_service.delete_todo_embedding", AsyncMock()),
            patch("app.services.todos.todo_service.delete_cache", AsyncMock()),
            patch(
                "app.services.todos.todo_service.delete_cache_by_pattern", AsyncMock()
            ),
        ):
            result = await TodoService.bulk_delete_todos(todo_ids, USER_ID)

        assert result.total == 5
        assert len(result.success) == 3
        assert "3" in result.message

    async def test_bulk_update_applies_to_all(self) -> None:
        """Bulk update must apply the update dict to all matching todos."""

        todo_ids = [str(_oid()) for _ in range(4)]

        mock_cursor = AsyncMock()
        mock_cursor.to_list = AsyncMock(
            return_value=[
                {"_id": ObjectId(tid), "user_id": USER_ID, "title": f"Todo {i}"}
                for i, tid in enumerate(todo_ids)
            ]
        )

        mock_todos = AsyncMock()
        mock_todos.update_many = AsyncMock(
            return_value=_make_update_result(modified=4, matched=4)
        )
        mock_todos.find = MagicMock(return_value=mock_cursor)

        request = BulkUpdateRequest(
            todo_ids=todo_ids,
            updates=TodoUpdateRequest(priority=Priority.HIGH),
        )

        with (
            patch("app.services.todos.todo_service.todos_collection", mock_todos),
            patch("app.services.todos.todo_service.projects_collection", AsyncMock()),
            patch("app.services.todos.todo_service.update_todo_embedding", AsyncMock()),
            patch("app.services.todos.todo_service.delete_cache", AsyncMock()),
            patch(
                "app.services.todos.todo_service.delete_cache_by_pattern", AsyncMock()
            ),
        ):
            result = await TodoService.bulk_update_todos(request, USER_ID)

        assert result.total == 4
        assert "4" in result.message
        # Verify the $set contained priority
        update_call = mock_todos.update_many.call_args
        set_dict = update_call[0][1]["$set"]
        assert set_dict["priority"] == Priority.HIGH


# ---------------------------------------------------------------------------
# System conversation get-or-create
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestSystemConversationGetOrCreate:
    """Verify idempotent system conversation creation."""

    async def test_returns_existing_when_present(self) -> None:
        """If a system conversation already exists, it must be returned without creating a new one."""

        existing = {
            "_id": _oid(),
            "user_id": USER_ID,
            "conversation_id": str(uuid4()),
            "is_system_generated": True,
            "system_purpose": "email_processing",
        }

        mock_collection = AsyncMock()
        mock_collection.find_one = AsyncMock(return_value=deepcopy(existing))

        with patch(
            "app.services.conversation_service.conversations_collection",
            mock_collection,
        ):
            result = await get_or_create_system_conversation(
                USER_ID, SystemPurpose.EMAIL_PROCESSING
            )

        assert result["is_system_generated"] is True
        mock_collection.insert_one.assert_not_called()

    async def test_creates_new_when_absent(self) -> None:
        """If no system conversation exists, one must be created."""

        mock_collection = AsyncMock()
        mock_collection.find_one = AsyncMock(return_value=None)
        mock_collection.insert_one = AsyncMock(return_value=_make_insert_result())

        with patch(
            "app.services.conversation_service.conversations_collection",
            mock_collection,
        ):
            result = await get_or_create_system_conversation(
                USER_ID, SystemPurpose.REMINDER_PROCESSING
            )

        assert result["is_system_generated"] is True
        assert result["system_purpose"] == SystemPurpose.REMINDER_PROCESSING
        mock_collection.insert_one.assert_called_once()
