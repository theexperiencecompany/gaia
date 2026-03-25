"""Unit tests for the memory API endpoints.

Tests cover CRUD operations on memories (get all, create, delete one, clear all).
The memory_service singleton is mocked; only HTTP status codes, response shapes,
and error handling are verified.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from app.models.memory_models import MemoryEntry, MemorySearchResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

API = "/api/v1/memory"


def _search_result(memories: list | None = None) -> MemorySearchResult:
    """Build a MemorySearchResult with sensible defaults."""
    mems = memories or []
    return MemorySearchResult(
        memories=mems,
        relations=[],
        total_count=len(mems),
    )


def _memory_entry(
    memory_id: str = "mem_1", content: str = "User likes coffee"
) -> MemoryEntry:
    return MemoryEntry(id=memory_id, content=content)


# ===========================================================================
# GET /api/v1/memory  -- get_all_memories
# ===========================================================================


@pytest.mark.unit
class TestGetAllMemories:
    """GET /api/v1/memory"""

    async def test_get_all_memories_success(self, client: AsyncClient) -> None:
        result = _search_result([_memory_entry()])
        with patch(
            "app.api.v1.endpoints.memory.memory_service.get_all_memories",
            new_callable=AsyncMock,
            return_value=result,
        ):
            resp = await client.get(API)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_count"] == 1
        assert data["memories"][0]["content"] == "User likes coffee"

    async def test_get_all_memories_empty(self, client: AsyncClient) -> None:
        result = _search_result([])
        with patch(
            "app.api.v1.endpoints.memory.memory_service.get_all_memories",
            new_callable=AsyncMock,
            return_value=result,
        ):
            resp = await client.get(API)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_count"] == 0
        assert data["memories"] == []

    async def test_get_all_memories_requires_auth(
        self, unauthed_client: AsyncClient
    ) -> None:
        resp = await unauthed_client.get(API)
        assert resp.status_code == 401


# ===========================================================================
# POST /api/v1/memory  -- create_memory
# ===========================================================================


@pytest.mark.unit
class TestCreateMemory:
    """POST /api/v1/memory"""

    async def test_create_memory_success(self, client: AsyncClient) -> None:
        mock_entry = MagicMock()
        mock_entry.id = "mem_new"
        with patch(
            "app.api.v1.endpoints.memory.memory_service.store_memory",
            new_callable=AsyncMock,
            return_value=mock_entry,
        ):
            resp = await client.post(API, json={"content": "I love Python"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["memory_id"] == "mem_new"
        assert "created" in data["message"].lower()

    async def test_create_memory_service_returns_none(
        self, client: AsyncClient
    ) -> None:
        with patch(
            "app.api.v1.endpoints.memory.memory_service.store_memory",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = await client.post(API, json={"content": "Something"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False

    async def test_create_memory_with_metadata(self, client: AsyncClient) -> None:
        mock_entry = MagicMock()
        mock_entry.id = "mem_meta"
        with patch(
            "app.api.v1.endpoints.memory.memory_service.store_memory",
            new_callable=AsyncMock,
            return_value=mock_entry,
        ):
            resp = await client.post(
                API,
                json={"content": "Important fact", "metadata": {"source": "chat"}},
            )
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    async def test_create_memory_validation_error_missing_content(
        self, client: AsyncClient
    ) -> None:
        resp = await client.post(API, json={})
        assert resp.status_code == 422

    async def test_create_memory_requires_auth(
        self, unauthed_client: AsyncClient
    ) -> None:
        resp = await unauthed_client.post(API, json={"content": "test"})
        assert resp.status_code == 401


# ===========================================================================
# DELETE /api/v1/memory/{memory_id}  -- delete_memory
# ===========================================================================


@pytest.mark.unit
class TestDeleteMemory:
    """DELETE /api/v1/memory/{memory_id}"""

    async def test_delete_memory_success(self, client: AsyncClient) -> None:
        with patch(
            "app.api.v1.endpoints.memory.memory_service.delete_memory",
            new_callable=AsyncMock,
            return_value=True,
        ):
            resp = await client.delete(f"{API}/mem_1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "deleted" in data["message"].lower()

    async def test_delete_memory_not_found_returns_success_false(
        self, client: AsyncClient
    ) -> None:
        """The endpoint returns success=False (200) when the service cannot delete."""
        with patch(
            "app.api.v1.endpoints.memory.memory_service.delete_memory",
            new_callable=AsyncMock,
            return_value=False,
        ):
            resp = await client.delete(f"{API}/nonexistent")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False

    async def test_delete_memory_requires_auth(
        self, unauthed_client: AsyncClient
    ) -> None:
        resp = await unauthed_client.delete(f"{API}/mem_1")
        assert resp.status_code == 401


# ===========================================================================
# DELETE /api/v1/memory  -- clear_all_memories
# ===========================================================================


@pytest.mark.unit
class TestClearAllMemories:
    """DELETE /api/v1/memory"""

    async def test_clear_all_success(self, client: AsyncClient) -> None:
        with patch(
            "app.api.v1.endpoints.memory.memory_service.delete_all_memories",
            new_callable=AsyncMock,
            return_value=True,
        ):
            resp = await client.delete(API)
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

    async def test_clear_all_failure(self, client: AsyncClient) -> None:
        with patch(
            "app.api.v1.endpoints.memory.memory_service.delete_all_memories",
            new_callable=AsyncMock,
            return_value=False,
        ):
            resp = await client.delete(API)
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False

    async def test_clear_all_service_exception(self, client: AsyncClient) -> None:
        """On exception the endpoint still returns 200 with success=False."""
        with patch(
            "app.api.v1.endpoints.memory.memory_service.delete_all_memories",
            new_callable=AsyncMock,
            side_effect=Exception("Mem0 unreachable"),
        ):
            resp = await client.delete(API)
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False

    async def test_clear_all_requires_auth(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.delete(API)
        assert resp.status_code == 401
