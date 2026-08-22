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

CONV_SERVICE = "app.api.v1.endpoints.conversations"


class TestCreateConversation:
    """POST /api/v1/conversations"""

    async def test_create_returns_response(self, client: AsyncClient):
        mock_resp = CreateConversationResponse(
            conversation_id="conv_123",
            user_id="user_1",
            createdAt="2024-01-01T00:00:00+00:00",
            detail="Conversation created successfully",
        )
        with patch(
            f"{CONV_SERVICE}.create_conversation_service",
            new_callable=AsyncMock,
            return_value=mock_resp,
        ):
            resp = await client.post(
                "/api/v1/conversations",
                json={"conversation_id": "conv_123", "description": "New Chat"},
            )

        assert resp.status_code == 200
        assert resp.json()["conversation_id"] == "conv_123"
        assert resp.json()["detail"] == "Conversation created successfully"

    async def test_create_requires_auth(self, unauthed_client: AsyncClient):
        resp = await unauthed_client.post(
            "/api/v1/conversations",
            json={"conversation_id": "conv_nope"},
        )
        assert resp.status_code == 401


class TestListConversations:
    """GET /api/v1/conversations"""

    async def test_list_default_pagination(self, client: AsyncClient):
        mock_resp = ConversationListResponse(
            conversations=[], total=0, page=1, limit=10, total_pages=1
        )
        with patch(
            f"{CONV_SERVICE}.get_conversations",
            new_callable=AsyncMock,
            return_value=mock_resp,
        ) as mock_list:
            resp = await client.get("/api/v1/conversations")

        assert resp.status_code == 200
        body = resp.json()
        assert "conversations" in body
        assert body["page"] == 1
        assert mock_list.await_args.kwargs == {"page": 1, "limit": 10}

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
        """A page too large to page with is a 422, not a 500.

        `page` was bounded below (ge=1) but not above, and the service turns it
        into `skip = (page - 1) * limit`. These exact values came from the
        schemathesis contract gate, which drove GET /api/v1/conversations to a
        500: the product is 10534517480782774985, past int64 max, so BSON cannot
        encode the skip and the driver error escapes as a server error.
        """
        resp = await client.get("/api/v1/conversations?limit=55&page=191536681468777728")

        assert resp.status_code == 422


class TestGetConversation:
    """GET /api/v1/conversations/{id}"""

    async def test_get_existing(self, client: AsyncClient):
        mock_resp = ConversationDocument(conversation_id="conv_123", user_id="user_1", messages=[])
        with patch(
            f"{CONV_SERVICE}.get_conversation",
            new_callable=AsyncMock,
            return_value=mock_resp,
        ):
            resp = await client.get("/api/v1/conversations/conv_123")

        assert resp.status_code == 200
        body = resp.json()
        assert body["conversation_id"] == "conv_123"
        assert body["messages"] == []
        # The endpoint dumps the document with exclude={"id"} — the Mongo _id
        # must not reach the client.
        assert "id" not in body


class TestDeleteConversation:
    """DELETE /api/v1/conversations/{id}"""

    async def test_delete_single(self, client: AsyncClient):
        mock_resp = ConversationActionResponse(
            message="Conversation deleted successfully", conversation_id="conv_123"
        )
        with patch(
            f"{CONV_SERVICE}.delete_conversation",
            new_callable=AsyncMock,
            return_value=mock_resp,
        ):
            resp = await client.delete("/api/v1/conversations/conv_123")

        assert resp.status_code == 200
        assert resp.json()["conversation_id"] == "conv_123"

    async def test_delete_all(self, client: AsyncClient):
        mock_resp = DeleteAllConversationsResponse(message="All conversations deleted successfully")
        with patch(
            f"{CONV_SERVICE}.delete_all_conversations",
            new_callable=AsyncMock,
            return_value=mock_resp,
        ):
            resp = await client.delete("/api/v1/conversations")

        assert resp.status_code == 200
        assert resp.json()["message"] == "All conversations deleted successfully"


class TestStarConversation:
    """PUT /api/v1/conversations/{id}/star"""

    async def test_star(self, client: AsyncClient):
        mock_resp = StarConversationResponse(message="Conversation starred", starred=True)
        with patch(
            f"{CONV_SERVICE}.star_conversation",
            new_callable=AsyncMock,
            return_value=mock_resp,
        ):
            resp = await client.put(
                "/api/v1/conversations/conv_123/star",
                json={"starred": True},
            )

        assert resp.status_code == 200
        assert resp.json()["starred"] is True


class TestUpdateDescription:
    """PUT /api/v1/conversations/{id}/description"""

    async def test_update_description(self, client: AsyncClient):
        mock_resp = UpdateDescriptionResponse(
            message="Description updated",
            conversation_id="conv_123",
            description="My important chat",
        )
        with patch(
            f"{CONV_SERVICE}.update_conversation_description",
            new_callable=AsyncMock,
            return_value=mock_resp,
        ):
            resp = await client.put(
                "/api/v1/conversations/conv_123/description",
                json={"description": "My important chat"},
            )

        assert resp.status_code == 200
        assert resp.json()["description"] == "My important chat"


class TestReadUnread:
    """PATCH /api/v1/conversations/{id}/read and /unread"""

    async def test_mark_as_read(self, client: AsyncClient):
        mock_resp = ConversationActionResponse(
            message="Conversation marked as read", conversation_id="conv_123"
        )
        with patch(
            f"{CONV_SERVICE}.mark_conversation_as_read",
            new_callable=AsyncMock,
            return_value=mock_resp,
        ):
            resp = await client.patch("/api/v1/conversations/conv_123/read")

        assert resp.status_code == 200
        assert resp.json()["message"] == "Conversation marked as read"

    async def test_mark_as_unread(self, client: AsyncClient):
        mock_resp = ConversationActionResponse(
            message="Conversation marked as unread", conversation_id="conv_123"
        )
        with patch(
            f"{CONV_SERVICE}.mark_conversation_as_unread",
            new_callable=AsyncMock,
            return_value=mock_resp,
        ):
            resp = await client.patch("/api/v1/conversations/conv_123/unread")

        assert resp.status_code == 200
        assert resp.json()["message"] == "Conversation marked as unread"


class TestPinnedMessages:
    """GET /api/v1/messages/pinned"""

    async def test_get_pinned(self, client: AsyncClient):
        # The payload key is "results", not "messages" — the old dict mock made
        # this test pass while asserting nothing about the real shape. A
        # non-empty row is deliberate: with results=[] the assertion cannot tell
        # a forwarded result from an empty one the endpoint invented itself.
        mock_resp = PinnedMessagesResponse(
            results=[
                ConversationMessageHit(
                    conversation_id="conv_123",
                    message=MessageModel(type="bot", response="pinned answer"),
                )
            ]
        )
        with patch(
            f"{CONV_SERVICE}.get_starred_messages",
            new_callable=AsyncMock,
            return_value=mock_resp,
        ):
            resp = await client.get("/api/v1/messages/pinned")

        assert resp.status_code == 200
        results = resp.json()["results"]
        assert len(results) == 1
        assert results[0]["conversation_id"] == "conv_123"
        assert results[0]["message"]["response"] == "pinned answer"
