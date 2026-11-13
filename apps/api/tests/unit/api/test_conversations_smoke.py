"""
Tests for conversation endpoints (/api/v1/conversations/*).

Covers:
- POST /conversations — create
- GET /conversations — list (paginated)
- GET /conversations/{id} — get single
- DELETE /conversations/{id} — delete single
- DELETE /conversations — delete all
- PUT /conversations/{id}/star — star/unstar
- PUT /conversations/{id}/description — update description
- PATCH /conversations/{id}/read — mark as read
- PATCH /conversations/{id}/unread — mark as unread
- GET /messages/pinned — get pinned messages
"""

from unittest.mock import AsyncMock, patch

from httpx import AsyncClient
import pytest

from app.models.chat_models import MessageModel
from app.models.conversation_models import (
    ConversationActionResponse,
    ConversationDocument,
    ConversationListResponse,
    ConversationMessageHit,
    CreateConversationResponse,
    DeleteAllConversationsResponse,
    PinnedMessagesResponse,
    StarConversationResponse,
    UpdateDescriptionResponse,
)
from tests.conftest import FAKE_USER

CONV_SERVICE = "app.api.v1.endpoints.conversations"


class TestCreateConversation:
    """POST /api/v1/conversations."""

    async def test_create_returns_response(self, client: AsyncClient):
        mock_resp = CreateConversationResponse(
            conversation_id="conv_123",
            user_id="user_1",
            createdAt="2024-01-01T00:00:00+00:00",
            detail="Conversation created successfully",
        )
        with (
            patch(
                f"{CONV_SERVICE}.create_conversation_service",
                new_callable=AsyncMock,
                return_value=mock_resp,
            ),
            patch(f"{CONV_SERVICE}.log") as mock_log,
        ):
            resp = await client.post(
                "/api/v1/conversations",
                json={"conversation_id": "conv_123", "description": "New Chat"},
            )

        assert resp.status_code == 200
        assert resp.json()["conversation_id"] == "conv_123"
        assert resp.json()["detail"] == "Conversation created successfully"
        mock_log.set.assert_any_call(
            user={"id": FAKE_USER.user_id},
            conversation={"operation": "create", "is_new": True},
        )

    async def test_create_requires_auth(self, unauthed_client: AsyncClient):
        resp = await unauthed_client.post(
            "/api/v1/conversations",
            json={"conversation_id": "conv_nope"},
        )
        assert resp.status_code == 401


class TestListConversations:
    """GET /api/v1/conversations."""

    async def test_list_default_pagination(self, client: AsyncClient):
        mock_resp = ConversationListResponse(
            conversations=[], total=0, page=1, limit=10, total_pages=1
        )
        with (
            patch(
                f"{CONV_SERVICE}.get_conversations",
                new_callable=AsyncMock,
                return_value=mock_resp,
            ) as mock_list,
            patch(f"{CONV_SERVICE}.log") as mock_log,
        ):
            resp = await client.get("/api/v1/conversations")

        assert resp.status_code == 200
        body = resp.json()
        assert "conversations" in body
        assert body["page"] == 1
        assert mock_list.await_args.kwargs == {"page": 1, "limit": 10}
        mock_log.set.assert_any_call(
            user={"id": FAKE_USER.user_id},
            conversation={"operation": "list", "page": 1, "limit": 10},
        )

    async def test_list_with_pagination(self, client: AsyncClient):
        mock_resp = ConversationListResponse(
            conversations=[], total=0, page=2, limit=5, total_pages=1
        )
        with patch(
            f"{CONV_SERVICE}.get_conversations",
            new_callable=AsyncMock,
            return_value=mock_resp,
        ) as mock_list:
            resp = await client.get("/api/v1/conversations?page=2&limit=5")

        assert resp.status_code == 200
        assert resp.json()["page"] == 2
        assert mock_list.await_args.kwargs == {"page": 2, "limit": 5}

    async def test_list_invalid_page(self, client: AsyncClient):
        resp = await client.get("/api/v1/conversations?page=0")
        assert resp.status_code == 422

    @pytest.mark.regression
    async def test_list_rejects_page_that_would_overflow_the_mongo_skip(
        self, client: AsyncClient
    ) -> None:
        """A page too large is a 422, not a 500: schemathesis drove skip to 10534517480782774985, past int64 max, which BSON cannot encode."""
        resp = await client.get("/api/v1/conversations?limit=55&page=191536681468777728")

        assert resp.status_code == 422


class TestGetConversation:
    """GET /api/v1/conversations/{id}."""

    async def test_get_existing(self, client: AsyncClient):
        # A stray top-level field a legacy row carries must still reach the
        # client: the document is extra="allow" and the response model keeps it.
        mock_resp = ConversationDocument.model_validate(
            {
                "conversation_id": "conv_123",
                "user_id": "user_1",
                "messages": [],
                "metadata": {"legacy": True},
            }
        )
        with (
            patch(
                f"{CONV_SERVICE}.get_conversation",
                new_callable=AsyncMock,
                return_value=mock_resp,
            ) as mock_get,
            patch(f"{CONV_SERVICE}.log") as mock_log,
        ):
            resp = await client.get("/api/v1/conversations/conv_123")

        assert resp.status_code == 200
        mock_log.set.assert_any_call(
            user={"id": FAKE_USER.user_id},
            conversation={"operation": "get", "id": "conv_123"},
        )
        # The lookup is scoped to the path id AND the caller — either dropped
        # would serve another user's conversation or nothing at all.
        assert mock_get.await_args.args == ("conv_123", FAKE_USER)
        assert mock_get.await_args.kwargs == {}
        body = resp.json()
        assert body["conversation_id"] == "conv_123"
        assert body["messages"] == []
        assert body["metadata"] == {"legacy": True}
        # The Mongo _id is excluded from the response model — it must not
        # reach the client.
        assert "id" not in body


class TestDeleteConversation:
    """DELETE /api/v1/conversations/{id}."""

    async def test_delete_single(self, client: AsyncClient):
        mock_resp = ConversationActionResponse(
            message="Conversation deleted successfully", conversation_id="conv_123"
        )
        with (
            patch(
                f"{CONV_SERVICE}.delete_conversation",
                new_callable=AsyncMock,
                return_value=mock_resp,
            ),
            patch(f"{CONV_SERVICE}.log") as mock_log,
        ):
            resp = await client.delete("/api/v1/conversations/conv_123")

        assert resp.status_code == 200
        assert resp.json()["conversation_id"] == "conv_123"
        mock_log.set.assert_any_call(
            user={"id": FAKE_USER.user_id},
            conversation={"operation": "delete", "id": "conv_123"},
        )

    async def test_delete_all(self, client: AsyncClient):
        mock_resp = DeleteAllConversationsResponse(message="All conversations deleted successfully")
        with (
            patch(
                f"{CONV_SERVICE}.delete_all_conversations",
                new_callable=AsyncMock,
                return_value=mock_resp,
            ),
            patch(f"{CONV_SERVICE}.log") as mock_log,
        ):
            resp = await client.delete("/api/v1/conversations")

        assert resp.status_code == 200
        assert resp.json()["message"] == "All conversations deleted successfully"
        mock_log.set.assert_any_call(
            user={"id": FAKE_USER.user_id},
            conversation={"operation": "delete_all"},
        )


class TestStarConversation:
    """PUT /api/v1/conversations/{id}/star."""

    async def test_star(self, client: AsyncClient):
        mock_resp = StarConversationResponse(message="Conversation starred", starred=True)
        with (
            patch(
                f"{CONV_SERVICE}.star_conversation",
                new_callable=AsyncMock,
                return_value=mock_resp,
            ),
            patch(f"{CONV_SERVICE}.log") as mock_log,
        ):
            resp = await client.put(
                "/api/v1/conversations/conv_123/star",
                json={"starred": True},
            )

        assert resp.status_code == 200
        assert resp.json()["starred"] is True
        mock_log.set.assert_any_call(
            user={"id": FAKE_USER.user_id},
            conversation={"operation": "star", "id": "conv_123", "is_starred": True},
        )


class TestUpdateDescription:
    """PUT /api/v1/conversations/{id}/description."""

    async def test_update_description(self, client: AsyncClient):
        mock_resp = UpdateDescriptionResponse(
            message="Description updated",
            conversation_id="conv_123",
            description="My important chat",
        )
        with (
            patch(
                f"{CONV_SERVICE}.update_conversation_description",
                new_callable=AsyncMock,
                return_value=mock_resp,
            ),
            patch(f"{CONV_SERVICE}.log") as mock_log,
        ):
            resp = await client.put(
                "/api/v1/conversations/conv_123/description",
                json={"description": "My important chat"},
            )

        assert resp.status_code == 200
        assert resp.json()["description"] == "My important chat"
        mock_log.set.assert_any_call(
            user={"id": FAKE_USER.user_id},
            conversation={"operation": "update_description", "id": "conv_123"},
        )


class TestReadUnread:
    """PATCH /api/v1/conversations/{id}/read and /unread."""

    async def test_mark_as_read(self, client: AsyncClient):
        mock_resp = ConversationActionResponse(
            message="Conversation marked as read", conversation_id="conv_123"
        )
        with (
            patch(
                f"{CONV_SERVICE}.mark_conversation_as_read",
                new_callable=AsyncMock,
                return_value=mock_resp,
            ),
            patch(f"{CONV_SERVICE}.log") as mock_log,
        ):
            resp = await client.patch("/api/v1/conversations/conv_123/read")

        assert resp.status_code == 200
        assert resp.json()["message"] == "Conversation marked as read"
        mock_log.set.assert_any_call(
            user={"id": FAKE_USER.user_id},
            conversation={"operation": "mark_read", "id": "conv_123"},
        )

    async def test_mark_as_unread(self, client: AsyncClient):
        mock_resp = ConversationActionResponse(
            message="Conversation marked as unread", conversation_id="conv_123"
        )
        with (
            patch(
                f"{CONV_SERVICE}.mark_conversation_as_unread",
                new_callable=AsyncMock,
                return_value=mock_resp,
            ),
            patch(f"{CONV_SERVICE}.log") as mock_log,
        ):
            resp = await client.patch("/api/v1/conversations/conv_123/unread")

        assert resp.status_code == 200
        assert resp.json()["message"] == "Conversation marked as unread"
        mock_log.set.assert_any_call(
            user={"id": FAKE_USER.user_id},
            conversation={"operation": "mark_unread", "id": "conv_123"},
        )


class TestPinnedMessages:
    """GET /api/v1/messages/pinned."""

    async def test_get_pinned(self, client: AsyncClient):
        # The payload key is "results", not "messages"; a non-empty row is
        # deliberate — results=[] can't tell a forwarded result from one the
        # endpoint invented itself.
        mock_resp = PinnedMessagesResponse(
            results=[
                ConversationMessageHit(
                    conversation_id="conv_123",
                    message=MessageModel(type="bot", response="pinned answer"),
                )
            ]
        )
        with (
            patch(
                f"{CONV_SERVICE}.get_starred_messages",
                new_callable=AsyncMock,
                return_value=mock_resp,
            ),
            patch(f"{CONV_SERVICE}.log") as mock_log,
        ):
            resp = await client.get("/api/v1/messages/pinned")

        assert resp.status_code == 200
        mock_log.set.assert_any_call(
            user={"id": FAKE_USER.user_id},
            conversation={"operation": "get_pinned"},
        )
        results = resp.json()["results"]
        assert len(results) == 1
        assert results[0]["conversation_id"] == "conv_123"
        assert results[0]["message"]["response"] == "pinned answer"
