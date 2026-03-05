"""Integration tests for conversation API endpoints.

Tests the conversation CRUD endpoints with mocked service layer
to verify routing, auth enforcement, and response status codes.
"""

from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.integration
class TestConversationEndpoints:
    """Test conversation REST endpoints."""

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
        }
        response = await test_client.get("/api/v1/conversations")
        assert response.status_code == 200
        data = response.json()
        assert "conversations" in data

    @patch(
        "app.api.v1.endpoints.conversations.create_conversation_service",
        new_callable=AsyncMock,
    )
    async def test_create_conversation_returns_200(self, mock_create, test_client):
        """POST /api/v1/conversations should return 200 on success."""
        mock_create.return_value = {
            "conversation_id": "conv-123",
            "message": "Conversation created",
        }
        response = await test_client.post(
            "/api/v1/conversations",
            json={
                "conversation_id": "conv-123",
                "description": "Test conversation",
                "messages": [],
            },
        )
        assert response.status_code == 200

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
            "messages": [],
        }
        response = await test_client.get("/api/v1/conversations/conv-456")
        assert response.status_code == 200

    @patch(
        "app.api.v1.endpoints.conversations.delete_conversation",
        new_callable=AsyncMock,
    )
    async def test_delete_conversation_returns_200(self, mock_delete, test_client):
        """DELETE /api/v1/conversations/{id} should return 200."""
        mock_delete.return_value = {"message": "Deleted"}
        response = await test_client.delete("/api/v1/conversations/conv-789")
        assert response.status_code == 200

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
                "messages": [],
            },
        )
        assert response.status_code == 401

    @patch(
        "app.api.v1.endpoints.conversations.star_conversation",
        new_callable=AsyncMock,
    )
    async def test_star_conversation_returns_200(self, mock_star, test_client):
        """PUT /api/v1/conversations/{id}/star should return 200."""
        mock_star.return_value = {"message": "Starred"}
        response = await test_client.put(
            "/api/v1/conversations/conv-star/star",
            json={"starred": True},
        )
        assert response.status_code == 200

    @patch(
        "app.api.v1.endpoints.conversations.mark_conversation_as_read",
        new_callable=AsyncMock,
    )
    async def test_mark_as_read_returns_200(self, mock_read, test_client):
        """PATCH /api/v1/conversations/{id}/read should return 200."""
        mock_read.return_value = {"message": "Marked as read"}
        response = await test_client.patch("/api/v1/conversations/conv-read/read")
        assert response.status_code == 200
