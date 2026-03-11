"""Integration tests for conversation API endpoints.

Mocking strategy
----------------
All mocks are at the MongoDB client/collection boundary, NOT at the service
layer.  Patching `app.services.conversation_service.conversations_collection`
means the service functions (create_conversation_service, get_conversations,
etc.) execute their real code — validation, HTTPException raising, response
construction — while avoiding a real database connection.

This ensures that if a developer:
  - Removes a required field from ConversationModel, the 422 tests catch it.
  - Removes `Depends(get_current_user)` from an endpoint, the 401 tests catch it.
  - Changes the response shape, the schema-assertion tests catch it.
  - Changes what DB operations are called, the DB-call-verification tests catch it.

Patching the collection object at `app.services.conversation_service` means we
intercept exactly the import that the service module bound at import time.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_insert_result(acknowledged: bool = True) -> MagicMock:
    r = MagicMock()
    r.acknowledged = acknowledged
    return r


def _make_update_result(modified_count: int = 1) -> MagicMock:
    r = MagicMock()
    r.modified_count = modified_count
    return r


def _make_delete_result(deleted_count: int = 1) -> MagicMock:
    r = MagicMock()
    r.deleted_count = deleted_count
    return r


def _make_find_cursor(docs: list) -> MagicMock:
    """Return a mock that supports .sort().skip().limit().to_list() chaining."""
    cursor = MagicMock()
    cursor.sort.return_value = cursor
    cursor.skip.return_value = cursor
    cursor.limit.return_value = cursor
    cursor.to_list = AsyncMock(return_value=docs)
    return cursor


def _minimal_conversation(user_id: str, conversation_id: str = "conv-456") -> dict:
    """Return a minimal MongoDB document dict (as Motor would return it)."""
    from bson import ObjectId

    return {
        "_id": ObjectId(),
        "user_id": user_id,
        "conversation_id": conversation_id,
        "description": "Test conversation",
        "starred": False,
        "is_system_generated": False,
        "is_unread": False,
        "messages": [],
        "createdAt": "2024-01-01T00:00:00+00:00",
    }


# ---------------------------------------------------------------------------
# Shared patch target
# ---------------------------------------------------------------------------

_COLLECTION = "app.services.conversation_service.conversations_collection"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestGetConversationsEndpoint:
    """GET /api/v1/conversations"""

    async def test_get_conversations_requires_auth(self, unauthenticated_client):
        """Unauthenticated request must return 401.

        If get_current_user is removed from the endpoint this test fails.
        """
        response = await unauthenticated_client.get("/api/v1/conversations")
        assert response.status_code == 401

    async def test_get_conversations_returns_200(self, test_client, test_user):
        """Authenticated request with an empty DB returns 200 with expected schema.

        The service calls conversations_collection.find() twice and
        count_documents() once; all are stubbed here at the collection level
        so the real service code path runs.
        """
        with patch(_COLLECTION) as mock_col:
            # Starred query
            mock_col.find.return_value = _make_find_cursor([])
            # count_documents must be awaitable
            mock_col.count_documents = AsyncMock(return_value=0)

            response = await test_client.get("/api/v1/conversations")

        assert response.status_code == 200
        data = response.json()
        # Schema assertions — fail if response shape changes
        assert "conversations" in data, "Response must include 'conversations' key"
        assert "total" in data, "Response must include 'total' key"
        assert "page" in data, "Response must include 'page' key"
        assert "limit" in data, "Response must include 'limit' key"
        assert isinstance(data["conversations"], list)

    async def test_get_conversations_calls_db_with_user_id(
        self, test_client, test_user
    ):
        """The service must query MongoDB filtered by the authenticated user_id.

        If the user_id filter is removed from the DB query, data isolation
        is broken.  This test verifies the filter is passed to find().
        """
        with patch(_COLLECTION) as mock_col:
            mock_col.find.return_value = _make_find_cursor([])
            mock_col.count_documents = AsyncMock(return_value=0)

            await test_client.get("/api/v1/conversations")

        # find() is called at least twice (starred + non-starred); both calls
        # should filter by user_id.
        assert mock_col.find.call_count >= 1
        first_call_filter = mock_col.find.call_args_list[0][0][0]
        assert first_call_filter.get("user_id") == test_user["user_id"], (
            f"DB query must filter by user_id={test_user['user_id']}, "
            f"got filter: {first_call_filter}"
        )

    async def test_get_conversations_invalid_page_returns_422(self, test_client):
        """page query param must be >= 1; passing 0 must return 422.

        If the `ge=1` constraint is removed from the page Query param,
        this test will receive 200 instead of 422.
        """
        response = await test_client.get("/api/v1/conversations?page=0")
        assert response.status_code == 422

    async def test_get_conversations_invalid_limit_returns_422(self, test_client):
        """limit query param must be between 1 and 100; passing 0 must return 422."""
        response = await test_client.get("/api/v1/conversations?limit=0")
        assert response.status_code == 422

    async def test_get_conversations_limit_over_max_returns_422(self, test_client):
        """limit query param must be <= 100; passing 101 must return 422."""
        response = await test_client.get("/api/v1/conversations?limit=101")
        assert response.status_code == 422


@pytest.mark.integration
class TestCreateConversationEndpoint:
    """POST /api/v1/conversations"""

    async def test_create_conversation_requires_auth(self, unauthenticated_client):
        """Unauthenticated request must return 401."""
        response = await unauthenticated_client.post(
            "/api/v1/conversations",
            json={"conversation_id": "conv-unauth", "description": "Should fail"},
        )
        assert response.status_code == 401

    async def test_create_conversation_returns_200(self, test_client):
        """Valid request must return 200 and the created conversation metadata."""
        with patch(_COLLECTION) as mock_col:
            mock_col.insert_one = AsyncMock(return_value=_make_insert_result())

            response = await test_client.post(
                "/api/v1/conversations",
                json={"conversation_id": "conv-123", "description": "Test"},
            )

        assert response.status_code == 200
        data = response.json()
        # Schema assertions
        assert "conversation_id" in data, "Response must include 'conversation_id'"
        assert data["conversation_id"] == "conv-123"
        assert "user_id" in data, "Response must include 'user_id'"
        assert "detail" in data, "Response must include 'detail' confirmation string"

    async def test_create_conversation_calls_insert_one(self, test_client):
        """The service must call insert_one on the conversations collection.

        If the DB write is removed from the service, this test fails.
        """
        with patch(_COLLECTION) as mock_col:
            mock_col.insert_one = AsyncMock(return_value=_make_insert_result())

            await test_client.post(
                "/api/v1/conversations",
                json={"conversation_id": "conv-db-check"},
            )

        mock_col.insert_one.assert_called_once()
        inserted_doc = mock_col.insert_one.call_args[0][0]
        assert inserted_doc["conversation_id"] == "conv-db-check"

    async def test_create_conversation_missing_conversation_id_returns_422(
        self, test_client
    ):
        """conversation_id is required; omitting it must return 422.

        If conversation_id is made Optional in ConversationModel, this test fails.
        """
        response = await test_client.post(
            "/api/v1/conversations",
            json={"description": "Missing ID"},
        )
        assert response.status_code == 422

    async def test_create_conversation_422_response_schema(self, test_client):
        """422 response must contain a 'detail' list describing missing fields."""
        response = await test_client.post(
            "/api/v1/conversations",
            json={},  # missing conversation_id
        )
        assert response.status_code == 422
        data = response.json()
        assert "detail" in data
        assert isinstance(data["detail"], list)
        field_names = [e.get("loc", [])[-1] for e in data["detail"] if e.get("loc")]
        assert "conversation_id" in field_names, (
            f"Expected validation error for 'conversation_id', got: {data['detail']}"
        )

    async def test_create_conversation_db_failure_returns_500(self, test_client):
        """If insert_one fails the endpoint must propagate a 500 error.

        This exercises the exception handling in create_conversation_service.
        """
        with patch(_COLLECTION) as mock_col:
            mock_col.insert_one = AsyncMock(
                side_effect=Exception("DB connection lost")
            )

            response = await test_client.post(
                "/api/v1/conversations",
                json={"conversation_id": "conv-fail"},
            )

        assert response.status_code == 500


@pytest.mark.integration
class TestGetSingleConversationEndpoint:
    """GET /api/v1/conversations/{conversation_id}"""

    async def test_get_single_conversation_returns_200(self, test_client, test_user):
        """Fetching an existing conversation returns 200 and the conversation data."""
        doc = _minimal_conversation(test_user["user_id"], "conv-456")
        with patch(_COLLECTION) as mock_col:
            mock_col.find_one = AsyncMock(return_value=doc)

            response = await test_client.get("/api/v1/conversations/conv-456")

        assert response.status_code == 200
        data = response.json()
        assert data.get("conversation_id") == "conv-456"

    async def test_get_single_conversation_response_schema(
        self, test_client, test_user
    ):
        """Response must include conversation_id and messages keys."""
        doc = _minimal_conversation(test_user["user_id"], "conv-schema")
        with patch(_COLLECTION) as mock_col:
            mock_col.find_one = AsyncMock(return_value=doc)

            response = await test_client.get("/api/v1/conversations/conv-schema")

        assert response.status_code == 200
        data = response.json()
        assert "conversation_id" in data, "Response must include 'conversation_id'"
        assert "messages" in data, "Response must include 'messages'"

    async def test_get_single_conversation_not_found_returns_404(self, test_client):
        """When the conversation doesn't exist the service must raise 404.

        If the `if not conversation: raise HTTPException(404)` guard is removed
        from get_conversation(), this returns 200 instead of 404.
        """
        with patch(_COLLECTION) as mock_col:
            mock_col.find_one = AsyncMock(return_value=None)

            response = await test_client.get("/api/v1/conversations/nonexistent-id")

        assert response.status_code == 404

    async def test_get_single_conversation_queries_by_user_and_id(
        self, test_client, test_user
    ):
        """DB query must filter by both user_id AND conversation_id for data isolation."""
        doc = _minimal_conversation(test_user["user_id"], "conv-isolation")
        with patch(_COLLECTION) as mock_col:
            mock_col.find_one = AsyncMock(return_value=doc)

            await test_client.get("/api/v1/conversations/conv-isolation")

        mock_col.find_one.assert_called_once()
        query_filter = mock_col.find_one.call_args[0][0]
        assert query_filter.get("user_id") == test_user["user_id"], (
            "DB query must include user_id filter"
        )
        assert query_filter.get("conversation_id") == "conv-isolation", (
            "DB query must include conversation_id filter"
        )

    async def test_get_single_conversation_requires_auth(
        self, unauthenticated_client
    ):
        """Unauthenticated request must return 401."""
        response = await unauthenticated_client.get("/api/v1/conversations/conv-auth")
        assert response.status_code == 401


@pytest.mark.integration
class TestDeleteConversationEndpoint:
    """DELETE /api/v1/conversations/{conversation_id}"""

    async def test_delete_conversation_returns_200(self, test_client):
        """Deleting an existing conversation returns 200."""
        with patch(_COLLECTION) as mock_col:
            mock_col.delete_one = AsyncMock(return_value=_make_delete_result(1))

            response = await test_client.delete("/api/v1/conversations/conv-789")

        assert response.status_code == 200

    async def test_delete_conversation_response_schema(self, test_client):
        """Delete response must include 'message' and 'conversation_id' keys."""
        with patch(_COLLECTION) as mock_col:
            mock_col.delete_one = AsyncMock(return_value=_make_delete_result(1))

            response = await test_client.delete("/api/v1/conversations/conv-schema")

        assert response.status_code == 200
        data = response.json()
        assert "message" in data, "Delete response must include 'message'"
        assert "conversation_id" in data, (
            "Delete response must include 'conversation_id'"
        )

    async def test_delete_conversation_not_found_returns_404(self, test_client):
        """When the conversation doesn't exist delete_one returns deleted_count=0 → 404.

        Removing the `if delete_result.deleted_count == 0` guard from the
        service will cause this test to return 200 instead of 404.
        """
        with patch(_COLLECTION) as mock_col:
            mock_col.delete_one = AsyncMock(return_value=_make_delete_result(0))

            response = await test_client.delete(
                "/api/v1/conversations/nonexistent-conv"
            )

        assert response.status_code == 404

    async def test_delete_conversation_calls_delete_one_with_user_filter(
        self, test_client, test_user
    ):
        """delete_one must be called with a filter that includes user_id.

        Without this filter a user could delete another user's conversation.
        """
        with patch(_COLLECTION) as mock_col:
            mock_col.delete_one = AsyncMock(return_value=_make_delete_result(1))

            await test_client.delete("/api/v1/conversations/conv-filter-check")

        mock_col.delete_one.assert_called_once()
        query_filter = mock_col.delete_one.call_args[0][0]
        assert query_filter.get("user_id") == test_user["user_id"], (
            "delete_one must filter by user_id to prevent cross-user deletion"
        )

    async def test_delete_conversation_requires_auth(self, unauthenticated_client):
        """Unauthenticated request must return 401."""
        response = await unauthenticated_client.delete(
            "/api/v1/conversations/conv-auth"
        )
        assert response.status_code == 401


@pytest.mark.integration
class TestStarConversationEndpoint:
    """PUT /api/v1/conversations/{conversation_id}/star"""

    async def test_star_conversation_returns_200(self, test_client):
        """Starring a conversation returns 200 with a confirmation message."""
        with patch(_COLLECTION) as mock_col:
            mock_col.update_one = AsyncMock(return_value=_make_update_result(1))

            response = await test_client.put(
                "/api/v1/conversations/conv-star/star",
                json={"starred": True},
            )

        assert response.status_code == 200
        data = response.json()
        assert "message" in data
        assert data.get("starred") is True

    async def test_star_conversation_not_found_returns_404(self, test_client):
        """If no document was modified, the service must raise 404."""
        with patch(_COLLECTION) as mock_col:
            mock_col.update_one = AsyncMock(return_value=_make_update_result(0))

            response = await test_client.put(
                "/api/v1/conversations/nonexistent/star",
                json={"starred": True},
            )

        assert response.status_code == 404

    async def test_star_conversation_missing_starred_field_returns_422(
        self, test_client
    ):
        """Body must include 'starred' boolean; omitting it returns 422.

        If `starred: bool` is made Optional in StarredUpdate this test fails.
        """
        response = await test_client.put(
            "/api/v1/conversations/conv-star/star",
            json={},  # missing 'starred'
        )
        assert response.status_code == 422

    async def test_star_conversation_wrong_type_for_starred_returns_422(
        self, test_client
    ):
        """'starred' must be a boolean; passing a dict (object) must return 422.

        Note: Pydantic v2 coerces strings like "yes"/"no" to bool in lax mode,
        so we use an object type which cannot be coerced to bool.
        """
        response = await test_client.put(
            "/api/v1/conversations/conv-star/star",
            json={"starred": {"value": "yes"}},  # dict cannot be coerced to bool
        )
        assert response.status_code == 422

    async def test_star_conversation_requires_auth(self, unauthenticated_client):
        """Unauthenticated request must return 401."""
        response = await unauthenticated_client.put(
            "/api/v1/conversations/conv-star/star",
            json={"starred": True},
        )
        assert response.status_code == 401


@pytest.mark.integration
class TestMarkAsReadEndpoint:
    """PATCH /api/v1/conversations/{conversation_id}/read"""

    async def test_mark_as_read_returns_200(self, test_client):
        """Marking a conversation as read returns 200 with expected keys."""
        with patch(_COLLECTION) as mock_col:
            mock_col.update_one = AsyncMock(return_value=_make_update_result(1))

            response = await test_client.patch("/api/v1/conversations/conv-read/read")

        assert response.status_code == 200
        data = response.json()
        assert "message" in data
        assert "conversation_id" in data
        assert data["conversation_id"] == "conv-read"

    async def test_mark_as_read_calls_update_one_with_user_filter(
        self, test_client, test_user
    ):
        """update_one must be called with user_id in the filter for data isolation."""
        with patch(_COLLECTION) as mock_col:
            mock_col.update_one = AsyncMock(return_value=_make_update_result(1))

            await test_client.patch("/api/v1/conversations/conv-isolation-read/read")

        mock_col.update_one.assert_called_once()
        query_filter = mock_col.update_one.call_args[0][0]
        assert query_filter.get("user_id") == test_user["user_id"], (
            "update_one must filter by user_id to prevent cross-user modification"
        )

    async def test_mark_as_read_requires_auth(self, unauthenticated_client):
        """Unauthenticated request must return 401."""
        response = await unauthenticated_client.patch(
            "/api/v1/conversations/conv-read/read"
        )
        assert response.status_code == 401


@pytest.mark.integration
class TestMarkAsUnreadEndpoint:
    """PATCH /api/v1/conversations/{conversation_id}/unread"""

    async def test_mark_as_unread_returns_200(self, test_client):
        """Marking a conversation as unread returns 200."""
        with patch(_COLLECTION) as mock_col:
            mock_col.update_one = AsyncMock(return_value=_make_update_result(1))

            response = await test_client.patch(
                "/api/v1/conversations/conv-unread/unread"
            )

        assert response.status_code == 200
        data = response.json()
        assert "message" in data
        assert "conversation_id" in data

    async def test_mark_as_unread_not_found_returns_404(self, test_client):
        """If no document was modified the service must raise 404."""
        with patch(_COLLECTION) as mock_col:
            mock_col.update_one = AsyncMock(return_value=_make_update_result(0))

            response = await test_client.patch(
                "/api/v1/conversations/nonexistent/unread"
            )

        assert response.status_code == 404

    async def test_mark_as_unread_requires_auth(self, unauthenticated_client):
        """Unauthenticated request must return 401."""
        response = await unauthenticated_client.patch(
            "/api/v1/conversations/conv-unread/unread"
        )
        assert response.status_code == 401


@pytest.mark.integration
class TestBatchSyncEndpoint:
    """POST /api/v1/conversations/batch-sync"""

    async def test_batch_sync_returns_200_with_empty_list(self, test_client):
        """Batch sync with an empty conversations list returns 200 with empty result."""
        response = await test_client.post(
            "/api/v1/conversations/batch-sync",
            json={"conversations": []},
        )
        assert response.status_code == 200
        data = response.json()
        assert "conversations" in data
        assert data["conversations"] == []

    async def test_batch_sync_missing_conversations_field_returns_422(
        self, test_client
    ):
        """'conversations' field is required; omitting it returns 422."""
        response = await test_client.post(
            "/api/v1/conversations/batch-sync",
            json={},
        )
        assert response.status_code == 422

    async def test_batch_sync_requires_auth(self, unauthenticated_client):
        """Unauthenticated request must return 401."""
        response = await unauthenticated_client.post(
            "/api/v1/conversations/batch-sync",
            json={"conversations": []},
        )
        assert response.status_code == 401

    async def test_batch_sync_calls_db_for_non_empty_request(
        self, test_client, test_user
    ):
        """batch_sync must hit the DB when the request contains conversation IDs."""
        with patch(_COLLECTION) as mock_col:
            # aggregate returns an async iterable; to_list returns the docs
            agg_cursor = MagicMock()
            agg_cursor.to_list = AsyncMock(return_value=[])
            mock_col.aggregate.return_value = agg_cursor

            response = await test_client.post(
                "/api/v1/conversations/batch-sync",
                json={
                    "conversations": [
                        {
                            "conversation_id": "conv-sync-1",
                            "last_updated": "2024-01-01T00:00:00Z",
                        }
                    ]
                },
            )

        assert response.status_code == 200
        mock_col.aggregate.assert_called_once()
