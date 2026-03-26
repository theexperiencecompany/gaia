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


CONV_SERVICE = "app.api.v1.endpoints.conversations"


class TestCreateConversation:
    """POST /api/v1/conversations"""

    async def test_create_returns_response(self, client: AsyncClient):
        mock_resp = {"id": "conv_123", "description": "New Chat"}
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
        assert resp.json()["id"] == "conv_123"

    async def test_create_requires_auth(self, unauthed_client: AsyncClient):
        resp = await unauthed_client.post(
            "/api/v1/conversations",
            json={"conversation_id": "conv_nope"},
        )
        assert resp.status_code == 401


class TestListConversations:
    """GET /api/v1/conversations"""

    async def test_list_default_pagination(self, client: AsyncClient):
        mock_resp = {"conversations": [], "total": 0, "page": 1}
        with patch(
            f"{CONV_SERVICE}.get_conversations",
            new_callable=AsyncMock,
            return_value=mock_resp,
        ):
            resp = await client.get("/api/v1/conversations")

        assert resp.status_code == 200
        body = resp.json()
        assert "conversations" in body

    async def test_list_with_pagination(self, client: AsyncClient):
        mock_resp = {"conversations": [], "total": 0, "page": 2}
        with patch(
            f"{CONV_SERVICE}.get_conversations",
            new_callable=AsyncMock,
            return_value=mock_resp,
        ):
            resp = await client.get("/api/v1/conversations?page=2&limit=5")

        assert resp.status_code == 200

    async def test_list_invalid_page(self, client: AsyncClient):
        resp = await client.get("/api/v1/conversations?page=0")
        assert resp.status_code == 422


class TestGetConversation:
    """GET /api/v1/conversations/{id}"""

    async def test_get_existing(self, client: AsyncClient):
        mock_resp = {"id": "conv_123", "messages": []}
        with patch(
            f"{CONV_SERVICE}.get_conversation",
            new_callable=AsyncMock,
            return_value=mock_resp,
        ):
            resp = await client.get("/api/v1/conversations/conv_123")

        assert resp.status_code == 200
        assert resp.json()["id"] == "conv_123"


class TestDeleteConversation:
    """DELETE /api/v1/conversations/{id}"""

    async def test_delete_single(self, client: AsyncClient):
        mock_resp = {"success": True}
        with patch(
            f"{CONV_SERVICE}.delete_conversation",
            new_callable=AsyncMock,
            return_value=mock_resp,
        ):
            resp = await client.delete("/api/v1/conversations/conv_123")

        assert resp.status_code == 200

    async def test_delete_all(self, client: AsyncClient):
        mock_resp = {"deleted_count": 5}
        with patch(
            f"{CONV_SERVICE}.delete_all_conversations",
            new_callable=AsyncMock,
            return_value=mock_resp,
        ):
            resp = await client.delete("/api/v1/conversations")

        assert resp.status_code == 200


class TestStarConversation:
    """PUT /api/v1/conversations/{id}/star"""

    async def test_star(self, client: AsyncClient):
        mock_resp = {"success": True}
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


class TestUpdateDescription:
    """PUT /api/v1/conversations/{id}/description"""

    async def test_update_description(self, client: AsyncClient):
        mock_resp = {"success": True}
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


class TestReadUnread:
    """PATCH /api/v1/conversations/{id}/read and /unread"""

    async def test_mark_as_read(self, client: AsyncClient):
        mock_resp = {"success": True}
        with patch(
            f"{CONV_SERVICE}.mark_conversation_as_read",
            new_callable=AsyncMock,
            return_value=mock_resp,
        ):
            resp = await client.patch("/api/v1/conversations/conv_123/read")

        assert resp.status_code == 200

    async def test_mark_as_unread(self, client: AsyncClient):
        mock_resp = {"success": True}
        with patch(
            f"{CONV_SERVICE}.mark_conversation_as_unread",
            new_callable=AsyncMock,
            return_value=mock_resp,
        ):
            resp = await client.patch("/api/v1/conversations/conv_123/unread")

        assert resp.status_code == 200


class TestPinnedMessages:
    """GET /api/v1/messages/pinned"""

    async def test_get_pinned(self, client: AsyncClient):
        mock_resp: dict = {"messages": []}
        with patch(
            f"{CONV_SERVICE}.get_starred_messages",
            new_callable=AsyncMock,
            return_value=mock_resp,
        ):
            resp = await client.get("/api/v1/messages/pinned")

        assert resp.status_code == 200
