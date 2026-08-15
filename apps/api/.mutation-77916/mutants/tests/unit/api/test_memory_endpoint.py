"""Endpoint tests for /api/v1/memory.

Covers the MAX_PAGE_NUMBER page bound on the memory list endpoint and the
happy path with the memory engine faked.
"""

from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from httpx import AsyncClient
import pytest

from app.api.v1.endpoints.memory import _require_user_id
from app.constants.general import MAX_PAGE_NUMBER
from app.models.memory_models import MemoryListResponse

MEMORY_ENDPOINT = "app.api.v1.endpoints.memory"


class TestRequireUserId:
    """_require_user_id: extract the user id or fail the request."""

    def test_returns_user_id_when_present(self) -> None:
        assert _require_user_id({"user_id": "u-1"}) == "u-1"

    def test_missing_user_id_raises_400(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            _require_user_id({})
        assert exc_info.value.status_code == 400
        assert exc_info.value.detail == "User ID not found"


class TestListMemories:
    """GET /api/v1/memory"""

    async def test_page_over_max_returns_422(self, client: AsyncClient) -> None:
        resp = await client.get(f"/api/v1/memory?page={MAX_PAGE_NUMBER + 1}")

        assert resp.status_code == 422

    async def test_list_returns_memories(self, client: AsyncClient) -> None:
        page = MemoryListResponse(memories=[], page=1, page_size=20, total_count=0)
        with patch(
            f"{MEMORY_ENDPOINT}.memory_engine.list_memories",
            new_callable=AsyncMock,
            return_value=page,
        ) as list_memories:
            resp = await client.get("/api/v1/memory?page=1&page_size=20")

        assert resp.status_code == 200
        body = resp.json()
        assert body["memories"] == []
        assert body["page"] == 1
        list_memories.assert_awaited_once_with(
            "507f1f77bcf86cd799439011", page=1, page_size=20, category=None
        )
