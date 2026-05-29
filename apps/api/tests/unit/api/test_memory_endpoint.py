"""Unit tests for the memory API endpoints and the Pydantic models they serialize.

Two layers are covered:

1. The HTTP contract of ``app/api/v1/endpoints/memory.py`` (get-all / create /
   delete-one / clear-all). The ``memory_service`` singleton is mocked at the
   I/O boundary; status codes, response shapes and error handling are asserted.
2. The behavioural defaults of ``app/models/memory_models.py`` — the request /
   response models the endpoint validates and serialises. These models carry
   defaults that the endpoint relies on (``MemorySearchResult.total_count``
   starts at 0, ``MemoryEntry.immutable`` starts at False, optional request
   ``metadata`` starts at None). Those defaults are asserted both by directly
   constructing the model and through the serialised GET response.

Behaviour spec — app/models/memory_models.py
---------------------------------------------
UNIT: CreateMemoryRequest
  EXPECTED: ``content`` is required (no default); ``metadata`` is optional and
            defaults to None.
  MUST-CATCH: missing ``content`` -> 422; absent ``metadata`` -> None.

UNIT: CreateMemoryResponse / DeleteMemoryResponse
  EXPECTED: carry the boolean ``success`` and a ``message`` the endpoint sets;
            CreateMemoryResponse exposes the created ``memory_id``.
  MUST-CATCH: success True/False round-trips through the endpoint; memory_id is
            the service-returned id, not a constant.

UNIT: MemoryEntry
  EXPECTED: only ``content`` is required; ``immutable`` defaults to False,
            ``metadata`` to {}, ``categories`` to [], ``user_id`` to "" and all
            timestamp/owner fields to None.
  MUST-CATCH: ``immutable`` default is False (not True) — both on the model and
            in the serialised GET response.

UNIT: MemoryRelation
  EXPECTED: every field (source/source_type/relationship/target/target_type) is
            required and round-trips through MemorySearchResult.relations.
  MUST-CATCH: a populated relation is serialised verbatim by the GET endpoint.

UNIT: MemorySearchResult
  EXPECTED: ``memories`` and ``relations`` default to empty lists, ``total_count``
            defaults to 0.
  MUST-CATCH: ``total_count`` default is 0 (not 1) — both on the model and in the
            serialised empty GET response.

EQUIVALENT MUTANTS (allowed survivors, justified):
  - Every ``Field(description="...")`` string mutation (str -> ''). Pydantic field
    descriptions are OpenAPI documentation only; they never affect validation,
    serialisation or any runtime value the endpoint or a client observes.
PROD SMELL: ``Message`` model is dead code — imported by no production module;
    excluded from the mutation target scope.
"""

from unittest.mock import AsyncMock, MagicMock, patch

from httpx import AsyncClient
import pytest

from app.models.memory_models import (
    CreateMemoryRequest,
    MemoryEntry,
    MemoryRelation,
    MemorySearchResult,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

API = "/api/v1/memory"


def _search_result(
    memories: list[MemoryEntry] | None = None,
    relations: list[MemoryRelation] | None = None,
) -> MemorySearchResult:
    """Build a MemorySearchResult with an explicit total_count."""
    mems = memories or []
    return MemorySearchResult(
        memories=mems,
        relations=relations or [],
        total_count=len(mems),
    )


def _memory_entry(memory_id: str = "mem_1", content: str = "User likes coffee") -> MemoryEntry:
    return MemoryEntry(id=memory_id, content=content)


# ===========================================================================
# app/models/memory_models.py -- behavioural defaults
# ===========================================================================


@pytest.mark.unit
class TestMemoryModelDefaults:
    """Defaults the endpoint depends on when constructing/serialising models."""

    def test_create_request_metadata_defaults_to_none(self) -> None:
        req = CreateMemoryRequest(content="hello")
        assert req.content == "hello"
        assert req.metadata is None

    def test_create_request_content_is_required(self) -> None:
        with pytest.raises(ValueError):
            CreateMemoryRequest()  # type: ignore[call-arg]

    def test_memory_entry_defaults(self) -> None:
        entry = MemoryEntry(content="a fact")
        assert entry.content == "a fact"
        assert entry.immutable is False
        assert entry.user_id == ""
        assert entry.metadata == {}
        assert entry.categories == []
        assert entry.id is None
        assert entry.created_at is None
        assert entry.relevance_score is None

    def test_search_result_defaults(self) -> None:
        result = MemorySearchResult()
        assert result.total_count == 0
        assert result.memories == []
        assert result.relations == []

    def test_relation_fields_round_trip(self) -> None:
        relation = MemoryRelation(
            source="alice",
            source_type="user",
            relationship="lives_in",
            target="berlin",
            target_type="location",
        )
        assert relation.source == "alice"
        assert relation.relationship == "lives_in"
        assert relation.target_type == "location"


# ===========================================================================
# GET /api/v1/memory  -- get_all_memories
# ===========================================================================


@pytest.mark.unit
class TestGetAllMemories:
    """GET /api/v1/memory"""

    async def test_get_all_memories_serializes_entry_and_defaults(
        self, client: AsyncClient
    ) -> None:
        """A populated result serialises content and the MemoryEntry defaults."""
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
        entry = data["memories"][0]
        assert entry["content"] == "User likes coffee"
        # MemoryEntry.immutable default flows through serialisation as False.
        assert entry["immutable"] is False
        assert entry["metadata"] == {}
        assert entry["categories"] == []

    async def test_get_all_memories_serializes_relations(self, client: AsyncClient) -> None:
        """Relations stored on the result are serialised verbatim."""
        relation = MemoryRelation(
            source="alice",
            source_type="user",
            relationship="lives_in",
            target="berlin",
            target_type="location",
        )
        result = _search_result([_memory_entry()], relations=[relation])
        with patch(
            "app.api.v1.endpoints.memory.memory_service.get_all_memories",
            new_callable=AsyncMock,
            return_value=result,
        ):
            resp = await client.get(API)
        assert resp.status_code == 200
        rel = resp.json()["relations"][0]
        assert rel["source"] == "alice"
        assert rel["relationship"] == "lives_in"
        assert rel["target"] == "berlin"
        assert rel["target_type"] == "location"

    async def test_get_all_memories_empty_uses_zero_default(self, client: AsyncClient) -> None:
        """An empty MemorySearchResult() serialises total_count as 0, lists empty."""
        with patch(
            "app.api.v1.endpoints.memory.memory_service.get_all_memories",
            new_callable=AsyncMock,
            return_value=MemorySearchResult(),
        ):
            resp = await client.get(API)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_count"] == 0
        assert data["memories"] == []
        assert data["relations"] == []

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
        mock_entry = MagicMock()
        mock_entry.id = "mem_new"
        with patch(
            "app.api.v1.endpoints.memory.memory_service.store_memory",
            new_callable=AsyncMock,
            return_value=mock_entry,
        ) as store:
            resp = await client.post(API, json={"content": "I love Python"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["memory_id"] == "mem_new"
        assert "created" in data["message"].lower()
        # content is forwarded to the service, not dropped or replaced.
        assert store.await_args.kwargs["message"] == "I love Python"
        assert store.await_args.kwargs["metadata"] is None

    async def test_create_memory_service_returns_none(self, client: AsyncClient) -> None:
        with patch(
            "app.api.v1.endpoints.memory.memory_service.store_memory",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = await client.post(API, json={"content": "Something"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert data["memory_id"] is None
        assert "failed" in data["message"].lower()

    async def test_create_memory_forwards_metadata(self, client: AsyncClient) -> None:
        mock_entry = MagicMock()
        mock_entry.id = "mem_meta"
        with patch(
            "app.api.v1.endpoints.memory.memory_service.store_memory",
            new_callable=AsyncMock,
            return_value=mock_entry,
        ) as store:
            resp = await client.post(
                API,
                json={"content": "Important fact", "metadata": {"source": "chat"}},
            )
        assert resp.status_code == 200
        assert resp.json()["memory_id"] == "mem_meta"
        assert store.await_args.kwargs["metadata"] == {"source": "chat"}

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
            "app.api.v1.endpoints.memory.memory_service.delete_memory",
            new_callable=AsyncMock,
            return_value=True,
        ) as delete:
            resp = await client.delete(f"{API}/mem_1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "deleted" in data["message"].lower()
        # The path memory_id is forwarded to the service.
        assert delete.await_args.kwargs["memory_id"] == "mem_1"

    async def test_delete_memory_not_found_returns_success_false(self, client: AsyncClient) -> None:
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
        assert "failed" in data["message"].lower()

    async def test_delete_memory_requires_auth(self, unauthed_client: AsyncClient) -> None:
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
        assert "cleared" in data["message"].lower()

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
        assert "failed" in data["message"].lower()

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
        assert "Mem0 unreachable" in data["message"]

    async def test_clear_all_requires_auth(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.delete(API)
        assert resp.status_code == 401
