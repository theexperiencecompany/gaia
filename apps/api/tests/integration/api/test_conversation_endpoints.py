"""Integration tests for conversation API endpoints.

Tests the conversation CRUD endpoints with mocked service layer
to verify routing, auth enforcement, response status codes, and
response body shape.
"""

from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.integration
class TestConversationEndpoints:
    """Test conversation REST endpoints."""

    # ------------------------------------------------------------------
    # GET /api/v1/conversations
    # ------------------------------------------------------------------

    @patch(
        "app.api.v1.endpoints.conversations.get_conversations",
        new_callable=AsyncMock,
    )
    async def test_get_conversations_returns_200(self, mock_get_convos, test_client):
        """GET /api/v1/conversations should return 200 with mocked service."""
        mock_get_convos.return_value = {
            "conversations": [],
            "total": 0,
            "page": 1,
            "limit": 10,
            "total_pages": 1,
        }
        response = await test_client.get("/api/v1/conversations")
        assert response.status_code == 200
        data = response.json()
        assert "conversations" in data
        assert data["total"] == 0
        assert data["page"] == 1
        assert data["limit"] == 10

    @patch(
        "app.api.v1.endpoints.conversations.get_conversations",
        new_callable=AsyncMock,
    )
    async def test_get_conversations_500_on_service_error(
        self, mock_get_convos, test_client
    ):
        """GET /api/v1/conversations should return 500 when service raises."""
        mock_get_convos.side_effect = Exception("DB error")
        response = await test_client.get("/api/v1/conversations")
        assert response.status_code == 500

    # ------------------------------------------------------------------
    # POST /api/v1/conversations
    # ------------------------------------------------------------------

    @patch(
        "app.api.v1.endpoints.conversations.create_conversation_service",
        new_callable=AsyncMock,
    )
    async def test_create_conversation_returns_200(self, mock_create, test_client):
        """POST /api/v1/conversations should return 200 on success."""
        mock_create.return_value = {
            "conversation_id": "conv-123",
            "user_id": "integration-test-user-1",
            "createdAt": "2024-01-01T00:00:00+00:00",
            "detail": "Conversation created successfully",
        }
        response = await test_client.post(
            "/api/v1/conversations",
            json={
                "conversation_id": "conv-123",
                "description": "Test conversation",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["conversation_id"] == "conv-123"
        assert data["detail"] == "Conversation created successfully"

    @patch(
        "app.api.v1.endpoints.conversations.create_conversation_service",
        new_callable=AsyncMock,
    )
    async def test_create_conversation_500_on_service_error(
        self, mock_create, test_client
    ):
        """POST /api/v1/conversations should return 500 when service raises."""
        mock_create.side_effect = Exception("DB error")
        response = await test_client.post(
            "/api/v1/conversations",
            json={"conversation_id": "conv-err", "description": "Fail"},
        )
        assert response.status_code == 500

    # ------------------------------------------------------------------
    # GET /api/v1/conversations/{conversation_id}
    # ------------------------------------------------------------------

    @patch(
        "app.api.v1.endpoints.conversations.get_conversation",
        new_callable=AsyncMock,
    )
    async def test_get_single_conversation_returns_200(
        self, mock_get_convo, test_client
    ):
        """GET /api/v1/conversations/{id} should return 200."""
        mock_get_convo.return_value = {
            "conversation_id": "conv-456",
            "description": "A conversation",
            "messages": [],
        }
        response = await test_client.get("/api/v1/conversations/conv-456")
        assert response.status_code == 200
        data = response.json()
        assert data["conversation_id"] == "conv-456"
        assert "messages" in data

    @patch(
        "app.api.v1.endpoints.conversations.get_conversation",
        new_callable=AsyncMock,
    )
    async def test_get_single_conversation_500_on_service_error(
        self, mock_get_convo, test_client
    ):
        """GET /api/v1/conversations/{id} should return 500 when service raises."""
        mock_get_convo.side_effect = Exception("DB error")
        response = await test_client.get("/api/v1/conversations/conv-456")
        assert response.status_code == 500

    # ------------------------------------------------------------------
    # DELETE /api/v1/conversations/{conversation_id}
    # ------------------------------------------------------------------

    @patch(
        "app.api.v1.endpoints.conversations.delete_conversation",
        new_callable=AsyncMock,
    )
    async def test_delete_conversation_returns_200(self, mock_delete, test_client):
        """DELETE /api/v1/conversations/{id} should return 200."""
        mock_delete.return_value = {
            "message": "Conversation deleted successfully",
            "conversation_id": "conv-789",
        }
        response = await test_client.delete("/api/v1/conversations/conv-789")
        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "Conversation deleted successfully"
        assert data["conversation_id"] == "conv-789"

    @patch(
        "app.api.v1.endpoints.conversations.delete_conversation",
        new_callable=AsyncMock,
    )
    async def test_delete_conversation_500_on_service_error(
        self, mock_delete, test_client
    ):
        """DELETE /api/v1/conversations/{id} should return 500 when service raises."""
        mock_delete.side_effect = Exception("DB error")
        response = await test_client.delete("/api/v1/conversations/conv-789")
        assert response.status_code == 500

    # ------------------------------------------------------------------
    # Auth tests (untouched — real get_current_user wiring)
    # ------------------------------------------------------------------

    async def test_get_conversations_requires_auth(self, unauthenticated_client):
        """GET /api/v1/conversations without auth should return 401."""
        response = await unauthenticated_client.get("/api/v1/conversations")
        assert response.status_code == 401

    async def test_create_conversation_requires_auth(self, unauthenticated_client):
        """POST /api/v1/conversations without auth should return 401."""
        response = await unauthenticated_client.post(
            "/api/v1/conversations",
            json={
                "conversation_id": "conv-unauth",
                "description": "Should fail",
            },
        )
        assert response.status_code == 401

    # ------------------------------------------------------------------
    # PUT /api/v1/conversations/{conversation_id}/star
    # ------------------------------------------------------------------

    @patch(
        "app.api.v1.endpoints.conversations.star_conversation",
        new_callable=AsyncMock,
    )
    async def test_star_conversation_returns_200(self, mock_star, test_client):
        """PUT /api/v1/conversations/{id}/star should return 200."""
        mock_star.return_value = {
            "message": "Conversation updated successfully",
            "starred": True,
        }
        response = await test_client.put(
            "/api/v1/conversations/conv-star/star",
            json={"starred": True},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["starred"] is True
        assert "message" in data

    @patch(
        "app.api.v1.endpoints.conversations.star_conversation",
        new_callable=AsyncMock,
    )
    async def test_star_conversation_requires_auth(
        self, mock_star, unauthenticated_client
    ):
        """PUT /api/v1/conversations/{id}/star without auth should return 401."""
        response = await unauthenticated_client.put(
            "/api/v1/conversations/conv-star/star",
            json={"starred": True},
        )
        assert response.status_code == 401

    @patch(
        "app.api.v1.endpoints.conversations.star_conversation",
        new_callable=AsyncMock,
    )
    async def test_star_conversation_500_on_service_error(self, mock_star, test_client):
        """PUT /api/v1/conversations/{id}/star should return 500 when service raises."""
        mock_star.side_effect = Exception("DB error")
        response = await test_client.put(
            "/api/v1/conversations/conv-star/star",
            json={"starred": True},
        )
        assert response.status_code == 500

    # ------------------------------------------------------------------
    # PATCH /api/v1/conversations/{conversation_id}/read
    # ------------------------------------------------------------------

    @patch(
        "app.api.v1.endpoints.conversations.mark_conversation_as_read",
        new_callable=AsyncMock,
    )
    async def test_mark_as_read_returns_200(self, mock_read, test_client):
        """PATCH /api/v1/conversations/{id}/read should return 200."""
        mock_read.return_value = {
            "message": "Conversation marked as read",
            "conversation_id": "conv-read",
        }
        response = await test_client.patch("/api/v1/conversations/conv-read/read")
        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "Conversation marked as read"
        assert data["conversation_id"] == "conv-read"

    @patch(
        "app.api.v1.endpoints.conversations.mark_conversation_as_read",
        new_callable=AsyncMock,
    )
    async def test_mark_as_read_requires_auth(self, mock_read, unauthenticated_client):
        """PATCH /api/v1/conversations/{id}/read without auth should return 401."""
        response = await unauthenticated_client.patch(
            "/api/v1/conversations/conv-read/read"
        )
        assert response.status_code == 401

    @patch(
        "app.api.v1.endpoints.conversations.mark_conversation_as_read",
        new_callable=AsyncMock,
    )
    async def test_mark_as_read_500_on_service_error(self, mock_read, test_client):
        """PATCH /api/v1/conversations/{id}/read should return 500 when service raises."""
        mock_read.side_effect = Exception("DB error")
        response = await test_client.patch("/api/v1/conversations/conv-read/read")
        assert response.status_code == 500

    # ------------------------------------------------------------------
    # POST /api/v1/conversations/batch-sync
    # ------------------------------------------------------------------

    @patch(
        "app.api.v1.endpoints.conversations.batch_sync_conversations",
        new_callable=AsyncMock,
    )
    async def test_batch_sync_conversations_returns_200(
        self, mock_batch_sync, test_client
    ):
        """POST /api/v1/conversations/batch-sync should return 200."""
        mock_batch_sync.return_value = {"conversations": []}
        response = await test_client.post(
            "/api/v1/conversations/batch-sync",
            json={
                "conversations": [
                    {
                        "conversation_id": "conv-sync-1",
                        "last_updated": "2024-01-01T00:00:00+00:00",
                    }
                ]
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "conversations" in data
        assert isinstance(data["conversations"], list)

    @patch(
        "app.api.v1.endpoints.conversations.batch_sync_conversations",
        new_callable=AsyncMock,
    )
    async def test_batch_sync_conversations_requires_auth(
        self, mock_batch_sync, unauthenticated_client
    ):
        """POST /api/v1/conversations/batch-sync without auth should return 401."""
        response = await unauthenticated_client.post(
            "/api/v1/conversations/batch-sync",
            json={"conversations": []},
        )
        assert response.status_code == 401

    @patch(
        "app.api.v1.endpoints.conversations.batch_sync_conversations",
        new_callable=AsyncMock,
    )
    async def test_batch_sync_conversations_500_on_service_error(
        self, mock_batch_sync, test_client
    ):
        """POST /api/v1/conversations/batch-sync should return 500 when service raises."""
        mock_batch_sync.side_effect = Exception("DB error")
        response = await test_client.post(
            "/api/v1/conversations/batch-sync",
            json={"conversations": []},
        )
        assert response.status_code == 500

    # ------------------------------------------------------------------
    # DELETE /api/v1/conversations  (delete all)
    # ------------------------------------------------------------------

    @patch(
        "app.api.v1.endpoints.conversations.delete_all_conversations",
        new_callable=AsyncMock,
    )
    async def test_delete_all_conversations_returns_200(
        self, mock_delete_all, test_client
    ):
        """DELETE /api/v1/conversations should return 200."""
        mock_delete_all.return_value = {
            "message": "All conversations deleted successfully"
        }
        response = await test_client.delete("/api/v1/conversations")
        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "All conversations deleted successfully"

    @patch(
        "app.api.v1.endpoints.conversations.delete_all_conversations",
        new_callable=AsyncMock,
    )
    async def test_delete_all_conversations_requires_auth(
        self, mock_delete_all, unauthenticated_client
    ):
        """DELETE /api/v1/conversations without auth should return 401."""
        response = await unauthenticated_client.delete("/api/v1/conversations")
        assert response.status_code == 401

    @patch(
        "app.api.v1.endpoints.conversations.delete_all_conversations",
        new_callable=AsyncMock,
    )
    async def test_delete_all_conversations_500_on_service_error(
        self, mock_delete_all, test_client
    ):
        """DELETE /api/v1/conversations should return 500 when service raises."""
        mock_delete_all.side_effect = Exception("DB error")
        response = await test_client.delete("/api/v1/conversations")
        assert response.status_code == 500

    # ------------------------------------------------------------------
    # PUT /api/v1/conversations/{conversation_id}/messages
    # ------------------------------------------------------------------

    @patch(
        "app.api.v1.endpoints.conversations.update_messages",
        new_callable=AsyncMock,
    )
    async def test_update_messages_returns_200(self, mock_update, test_client):
        """PUT /api/v1/conversations/{id}/messages should return 200."""
        mock_update.return_value = {
            "conversation_id": "conv-msg",
            "message": "Messages updated",
            "modified_count": 1,
            "message_ids": ["msg-id-1"],
        }
        response = await test_client.put(
            "/api/v1/conversations/conv-msg/messages",
            json={
                "conversation_id": "conv-msg",
                "messages": [{"type": "human", "response": "Hello"}],
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["conversation_id"] == "conv-msg"
        assert data["message"] == "Messages updated"
        assert data["modified_count"] == 1
        assert "message_ids" in data

    @patch(
        "app.api.v1.endpoints.conversations.update_messages",
        new_callable=AsyncMock,
    )
    async def test_update_messages_requires_auth(
        self, mock_update, unauthenticated_client
    ):
        """PUT /api/v1/conversations/{id}/messages without auth should return 401."""
        response = await unauthenticated_client.put(
            "/api/v1/conversations/conv-msg/messages",
            json={
                "conversation_id": "conv-msg",
                "messages": [{"type": "human", "response": "Hello"}],
            },
        )
        assert response.status_code == 401

    @patch(
        "app.api.v1.endpoints.conversations.update_messages",
        new_callable=AsyncMock,
    )
    async def test_update_messages_500_on_service_error(self, mock_update, test_client):
        """PUT /api/v1/conversations/{id}/messages should return 500 when service raises."""
        mock_update.side_effect = Exception("DB error")
        response = await test_client.put(
            "/api/v1/conversations/conv-msg/messages",
            json={
                "conversation_id": "conv-msg",
                "messages": [{"type": "human", "response": "Hello"}],
            },
        )
        assert response.status_code == 500

    # ------------------------------------------------------------------
    # PUT /api/v1/conversations/{conversation_id}/messages/{message_id}/pin
    # ------------------------------------------------------------------

    @patch(
        "app.api.v1.endpoints.conversations.pin_message",
        new_callable=AsyncMock,
    )
    async def test_pin_message_returns_200(self, mock_pin, test_client):
        """PUT /api/v1/conversations/{id}/messages/{msg_id}/pin should return 200."""
        mock_pin.return_value = {
            "message": "Message with ID msg-1 pinned successfully",
            "pinned": True,
        }
        response = await test_client.put(
            "/api/v1/conversations/conv-pin/messages/msg-1/pin",
            json={"pinned": True},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["pinned"] is True
        assert "msg-1" in data["message"]

    @patch(
        "app.api.v1.endpoints.conversations.pin_message",
        new_callable=AsyncMock,
    )
    async def test_pin_message_requires_auth(self, mock_pin, unauthenticated_client):
        """PUT /api/v1/conversations/{id}/messages/{msg_id}/pin without auth should return 401."""
        response = await unauthenticated_client.put(
            "/api/v1/conversations/conv-pin/messages/msg-1/pin",
            json={"pinned": True},
        )
        assert response.status_code == 401

    @patch(
        "app.api.v1.endpoints.conversations.pin_message",
        new_callable=AsyncMock,
    )
    async def test_pin_message_500_on_service_error(self, mock_pin, test_client):
        """PUT /api/v1/conversations/{id}/messages/{msg_id}/pin should return 500 when service raises."""
        mock_pin.side_effect = Exception("DB error")
        response = await test_client.put(
            "/api/v1/conversations/conv-pin/messages/msg-1/pin",
            json={"pinned": True},
        )
        assert response.status_code == 500

    # ------------------------------------------------------------------
    # GET /api/v1/messages/pinned
    # ------------------------------------------------------------------

    @patch(
        "app.api.v1.endpoints.conversations.get_starred_messages",
        new_callable=AsyncMock,
    )
    async def test_get_starred_messages_returns_200(self, mock_starred, test_client):
        """GET /api/v1/messages/pinned should return 200."""
        mock_starred.return_value = {"results": []}
        response = await test_client.get("/api/v1/messages/pinned")
        assert response.status_code == 200
        data = response.json()
        assert "results" in data
        assert isinstance(data["results"], list)

    @patch(
        "app.api.v1.endpoints.conversations.get_starred_messages",
        new_callable=AsyncMock,
    )
    async def test_get_starred_messages_requires_auth(
        self, mock_starred, unauthenticated_client
    ):
        """GET /api/v1/messages/pinned without auth should return 401."""
        response = await unauthenticated_client.get("/api/v1/messages/pinned")
        assert response.status_code == 401

    @patch(
        "app.api.v1.endpoints.conversations.get_starred_messages",
        new_callable=AsyncMock,
    )
    async def test_get_starred_messages_500_on_service_error(
        self, mock_starred, test_client
    ):
        """GET /api/v1/messages/pinned should return 500 when service raises."""
        mock_starred.side_effect = Exception("DB error")
        response = await test_client.get("/api/v1/messages/pinned")
        assert response.status_code == 500

    # ------------------------------------------------------------------
    # PUT /api/v1/conversations/{conversation_id}/description
    # ------------------------------------------------------------------

    @patch(
        "app.api.v1.endpoints.conversations.update_conversation_description",
        new_callable=AsyncMock,
    )
    async def test_update_conversation_description_returns_200(
        self, mock_update_desc, test_client
    ):
        """PUT /api/v1/conversations/{id}/description should return 200."""
        mock_update_desc.return_value = {
            "message": "Conversation description updated successfully",
            "conversation_id": "conv-desc",
            "description": "New description",
        }
        response = await test_client.put(
            "/api/v1/conversations/conv-desc/description",
            json={"description": "New description"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["conversation_id"] == "conv-desc"
        assert data["description"] == "New description"
        assert "message" in data

    @patch(
        "app.api.v1.endpoints.conversations.update_conversation_description",
        new_callable=AsyncMock,
    )
    async def test_update_conversation_description_requires_auth(
        self, mock_update_desc, unauthenticated_client
    ):
        """PUT /api/v1/conversations/{id}/description without auth should return 401."""
        response = await unauthenticated_client.put(
            "/api/v1/conversations/conv-desc/description",
            json={"description": "New description"},
        )
        assert response.status_code == 401

    @patch(
        "app.api.v1.endpoints.conversations.update_conversation_description",
        new_callable=AsyncMock,
    )
    async def test_update_conversation_description_500_on_service_error(
        self, mock_update_desc, test_client
    ):
        """PUT /api/v1/conversations/{id}/description should return 500 when service raises."""
        mock_update_desc.side_effect = Exception("DB error")
        response = await test_client.put(
            "/api/v1/conversations/conv-desc/description",
            json={"description": "New description"},
        )
        assert response.status_code == 500

    # ------------------------------------------------------------------
    # PATCH /api/v1/conversations/{conversation_id}/unread
    # ------------------------------------------------------------------

    @patch(
        "app.api.v1.endpoints.conversations.mark_conversation_as_unread",
        new_callable=AsyncMock,
    )
    async def test_mark_conversation_as_unread_returns_200(
        self, mock_unread, test_client
    ):
        """PATCH /api/v1/conversations/{id}/unread should return 200."""
        mock_unread.return_value = {
            "message": "Conversation marked as unread",
            "conversation_id": "conv-unread",
        }
        response = await test_client.patch("/api/v1/conversations/conv-unread/unread")
        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "Conversation marked as unread"
        assert data["conversation_id"] == "conv-unread"

    @patch(
        "app.api.v1.endpoints.conversations.mark_conversation_as_unread",
        new_callable=AsyncMock,
    )
    async def test_mark_conversation_as_unread_requires_auth(
        self, mock_unread, unauthenticated_client
    ):
        """PATCH /api/v1/conversations/{id}/unread without auth should return 401."""
        response = await unauthenticated_client.patch(
            "/api/v1/conversations/conv-unread/unread"
        )
        assert response.status_code == 401

    @patch(
        "app.api.v1.endpoints.conversations.mark_conversation_as_unread",
        new_callable=AsyncMock,
    )
    async def test_mark_conversation_as_unread_500_on_service_error(
        self, mock_unread, test_client
    ):
        """PATCH /api/v1/conversations/{id}/unread should return 500 when service raises."""
        mock_unread.side_effect = Exception("DB error")
        response = await test_client.patch("/api/v1/conversations/conv-unread/unread")
        assert response.status_code == 500
