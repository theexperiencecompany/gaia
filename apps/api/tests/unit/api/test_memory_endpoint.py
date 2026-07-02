"""Unit tests for the memory API endpoints.

Tests cover CRUD operations on memories (get all, create, delete one, clear all).
The memory_engine singleton is mocked; only HTTP status codes, response shapes,
and error handling are verified.
"""

from unittest.mock import AsyncMock, MagicMock, patch

from httpx import AsyncClient
import pytest

from app.models.memory_models import MemoryEntry, MemoryListResponse

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

API = "/api/v1/memory"

# Valid UUID used for path-param tests (endpoint enforces UUID_PATH_PATTERN).
_MEM_UUID = "00000000-0000-0000-0000-000000000001"


def _list_response(memories: list | None = None) -> MemoryListResponse:
    """Build a MemoryListResponse with sensible defaults."""
    mems = memories or []
    return MemoryListResponse(
        memories=mems,
        page=1,
        page_size=20,
        total_count=len(mems),
    )


def _memory_entry(memory_id: str = _MEM_UUID, content: str = "User likes coffee") -> MemoryEntry:
    return MemoryEntry(id=memory_id, content=content)


def _retained_memory(memory_id: str = "mem_new") -> MagicMock:
    """Build a RetainedMemory-shaped mock with .entry.id."""
    entry = MagicMock()
    entry.id = memory_id
    entry.category_path = "general"
    retained = MagicMock()
    retained.entry = entry
    return retained


# ===========================================================================
# GET /api/v1/memory  -- list_memories
# ===========================================================================


@pytest.mark.unit
class TestGetAllMemories:
    """GET /api/v1/memory"""

    async def test_get_all_memories_success(self, client: AsyncClient) -> None:
        result = _list_response([_memory_entry()])
        with patch(
            "app.api.v1.endpoints.memory.memory_engine.list_memories",
            new_callable=AsyncMock,
            return_value=result,
        ):
            resp = await client.get(API)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_count"] == 1
        assert data["memories"][0]["content"] == "User likes coffee"

    async def test_get_all_memories_empty(self, client: AsyncClient) -> None:
        result = _list_response([])
        with patch(
            "app.api.v1.endpoints.memory.memory_engine.list_memories",
            new_callable=AsyncMock,
            return_value=result,
        ):
            resp = await client.get(API)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_count"] == 0
        assert data["memories"] == []

    async def test_get_all_memories_requires_auth(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.get(API)
        assert resp.status_code == 401


# ===========================================================================
# POST /api/v1/memory  -- create_memory
# ===========================================================================


@pytest.mark.unit
class TestCreateMemory:
    """POST /api/v1/memory"""

    async def test_create_memory_success(self, client: AsyncClient) -> None:
        mock_retained = _retained_memory("mem_new")
        with patch(
            "app.api.v1.endpoints.memory.memory_engine.retain_single",
            new_callable=AsyncMock,
            return_value=mock_retained,
        ):
            resp = await client.post(API, json={"content": "I love Python"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["memory_id"] == "mem_new"
        assert "created" in data["message"].lower()

    async def test_create_memory_exception_returns_failure(self, client: AsyncClient) -> None:
        """When retain_single raises, the endpoint returns success=False (caught by try/except)."""
        with patch(
            "app.api.v1.endpoints.memory.memory_engine.retain_single",
            new_callable=AsyncMock,
            side_effect=RuntimeError("storage unavailable"),
        ):
            resp = await client.post(API, json={"content": "Something"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False

    async def test_create_memory_with_category_path(self, client: AsyncClient) -> None:
        mock_retained = _retained_memory("mem_categorized")
        with patch(
            "app.api.v1.endpoints.memory.memory_engine.retain_single",
            new_callable=AsyncMock,
            return_value=mock_retained,
        ):
            resp = await client.post(
                API,
                json={"content": "Important fact", "category_path": "work/gaia"},
            )
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    async def test_create_memory_validation_error_missing_content(
        self, client: AsyncClient
    ) -> None:
        resp = await client.post(API, json={})
        assert resp.status_code == 422

    async def test_create_memory_requires_auth(self, unauthed_client: AsyncClient) -> None:
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
            "app.api.v1.endpoints.memory.memory_engine.forget_memory",
            new_callable=AsyncMock,
            return_value=True,
        ):
            resp = await client.delete(f"{API}/{_MEM_UUID}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "deleted" in data["message"].lower()

    async def test_delete_memory_not_found_returns_404(self, client: AsyncClient) -> None:
        """When forget_memory returns False the endpoint raises 404."""
        with patch(
            "app.api.v1.endpoints.memory.memory_engine.forget_memory",
            new_callable=AsyncMock,
            return_value=False,
        ):
            resp = await client.delete(f"{API}/{_MEM_UUID}")
        assert resp.status_code == 404

    async def test_delete_memory_requires_auth(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.delete(f"{API}/{_MEM_UUID}")
        assert resp.status_code == 401


# ===========================================================================
# DELETE /api/v1/memory  -- clear_all_memories
# ===========================================================================


@pytest.mark.unit
class TestClearAllMemories:
    """DELETE /api/v1/memory"""

    async def test_clear_all_success(self, client: AsyncClient) -> None:
        # delete_all returns the count of deleted memories (int).
        with patch(
            "app.api.v1.endpoints.memory.memory_engine.delete_all",
            new_callable=AsyncMock,
            return_value=5,
        ):
            resp = await client.delete(API)
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

    async def test_clear_all_zero_deleted(self, client: AsyncClient) -> None:
        """Clearing when there are no memories still returns success=True."""
        with patch(
            "app.api.v1.endpoints.memory.memory_engine.delete_all",
            new_callable=AsyncMock,
            return_value=0,
        ):
            resp = await client.delete(API)
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

    async def test_clear_all_service_exception_returns_500(self, client: AsyncClient) -> None:
        """On unhandled exception the endpoint propagates a 500 (no try/except on delete_all)."""
        with patch(
            "app.api.v1.endpoints.memory.memory_engine.delete_all",
            new_callable=AsyncMock,
            side_effect=Exception("memory engine unreachable"),
        ):
            resp = await client.delete(API)
        assert resp.status_code == 500

    async def test_clear_all_requires_auth(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.delete(API)
        assert resp.status_code == 401
