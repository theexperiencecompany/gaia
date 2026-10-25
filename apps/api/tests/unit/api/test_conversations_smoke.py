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

from app.models.conversation_models import (
    ConversationDocument,
)
from tests.conftest import FAKE_USER

CONV_SERVICE = "app.api.v1.endpoints.conversations"


class TestListConversations:
    """GET /api/v1/conversations."""

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
