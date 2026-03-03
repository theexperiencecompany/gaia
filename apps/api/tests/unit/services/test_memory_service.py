"""Unit tests for MemoryService parsing and formatting logic."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.models.memory_models import MemoryEntry, MemoryRelation, MemorySearchResult
from app.services.memory_service import MemoryService


@pytest.fixture
def service():
    return MemoryService()


@pytest.mark.unit
class TestValidateUserId:
    def test_returns_string_user_id(self, service):
        assert service._validate_user_id("user_123") == "user_123"

    def test_returns_none_for_empty(self, service):
        assert service._validate_user_id("") is None
        assert service._validate_user_id(None) is None

    def test_extracts_from_dict(self, service):
        assert service._validate_user_id({"user_id": "u1"}) == "u1"

    def test_extracts_id_fallback_from_dict(self, service):
        assert service._validate_user_id({"id": "u2"}) == "u2"

    def test_returns_none_for_empty_dict(self, service):
        assert service._validate_user_id({}) is None

    def test_coerces_int_to_string(self, service):
        assert service._validate_user_id(42) == "42"


@pytest.mark.unit
class TestParseMemoryResult:
    def test_parses_valid_v2_result(self, service):
        raw = {
            "id": "mem_001",
            "memory": "User likes Python",
            "user_id": "user_123",
            "metadata": {"source": "conversation"},
            "categories": ["preferences"],
            "created_at": "2024-01-01T00:00:00",
            "score": 0.95,
        }

        entry = service._parse_memory_result(raw)

        assert entry is not None
        assert entry.id == "mem_001"
        assert entry.content == "User likes Python"
        assert entry.metadata == {"source": "conversation"}
        assert entry.categories == ["preferences"]
        assert entry.relevance_score == 0.95

    def test_returns_none_for_empty_memory(self, service):
        raw = {"id": "mem_001", "memory": ""}
        assert service._parse_memory_result(raw) is None

    def test_returns_none_for_non_dict(self, service):
        assert service._parse_memory_result("not a dict") is None

    def test_handles_none_metadata(self, service):
        raw = {
            "id": "mem_001",
            "memory": "test content",
            "metadata": None,
        }
        entry = service._parse_memory_result(raw)
        assert entry is not None
        assert entry.metadata == {}

    def test_handles_missing_optional_fields(self, service):
        raw = {"memory": "just content"}
        entry = service._parse_memory_result(raw)
        assert entry is not None
        assert entry.content == "just content"
        assert entry.id is None
        assert entry.categories == []


@pytest.mark.unit
class TestParseMemoryList:
    def test_parses_list_of_results(self, service):
        memories = [
            {"id": "m1", "memory": "Fact one"},
            {"id": "m2", "memory": "Fact two"},
        ]

        result = service._parse_memory_list(memories, "user_123")

        assert len(result) == 2
        assert all(e.user_id == "user_123" for e in result)

    def test_skips_unparseable_entries(self, service):
        memories = [
            {"id": "m1", "memory": "Valid"},
            {"id": "m2", "memory": ""},
            "not a dict",
        ]

        result = service._parse_memory_list(memories, "user_123")
        assert len(result) == 1

    def test_empty_list_returns_empty(self, service):
        assert service._parse_memory_list([], "user_123") == []


@pytest.mark.unit
class TestParseAddResult:
    def test_parses_sync_result(self, service):
        raw = {
            "id": "mem_new",
            "memory": "New memory stored",
            "event": "ADD",
            "structured_attributes": {"key": "value"},
        }

        entry = service._parse_add_result(raw)

        assert entry is not None
        assert entry.id == "mem_new"
        assert entry.content == "New memory stored"
        assert entry.metadata == {"key": "value"}

    def test_parses_async_result(self, service):
        raw = {
            "status": "PENDING",
            "event_id": "evt_123",
            "message": "Memory queued",
        }

        entry = service._parse_add_result(raw, is_async=True)

        assert entry is not None
        assert entry.id == "evt_123"
        assert entry.metadata["status"] == "PENDING"
        assert entry.metadata["async_mode"] is True

    def test_returns_none_for_empty_content(self, service):
        raw = {"id": "mem_noop", "memory": "", "event": "NOOP"}
        assert service._parse_add_result(raw) is None

    def test_returns_none_for_non_dict(self, service):
        assert service._parse_add_result("invalid") is None

    def test_handles_none_structured_attributes(self, service):
        raw = {
            "id": "mem_new",
            "memory": "Content here",
            "structured_attributes": None,
        }
        entry = service._parse_add_result(raw)
        assert entry is not None
        assert entry.metadata == {}


@pytest.mark.unit
class TestExtractRelationships:
    def test_extracts_relations_key(self, service):
        response = {"relations": [{"source": "a", "relation": "knows", "destination": "b"}]}
        result = service._extract_relationships_from_response(response)
        assert len(result) == 1

    def test_extracts_entities_key(self, service):
        response = {"entities": [{"source": "x"}]}
        result = service._extract_relationships_from_response(response)
        assert len(result) == 1

    def test_extracts_nested_graph(self, service):
        response = {"graph": {"relationships": [{"source": "a"}]}}
        result = service._extract_relationships_from_response(response)
        assert len(result) == 1

    def test_returns_empty_for_no_keys(self, service):
        result = service._extract_relationships_from_response({})
        assert result == []

    def test_returns_empty_for_non_dict(self, service):
        result = service._extract_relationships_from_response([1, 2, 3])
        assert result == []


@pytest.mark.unit
class TestParseRelationships:
    def test_parses_v2_graph_format(self, service):
        relations = [
            {
                "source": "alice",
                "relation": "likes",
                "destination": "pizza",
                "source_type": "person",
                "destination_type": "food",
            }
        ]

        result = service._parse_relationships(relations)

        assert len(result) == 1
        assert result[0].source == "alice"
        assert result[0].relationship == "likes"
        assert result[0].target == "pizza"
        assert result[0].source_type == "person"
        assert result[0].target_type == "food"

    def test_parses_legacy_format(self, service):
        relations = [
            {
                "source": "bob",
                "relationship": "works_at",
                "target": "acme",
            }
        ]

        result = service._parse_relationships(relations)

        assert len(result) == 1
        assert result[0].source == "bob"
        assert result[0].relationship == "works_at"
        assert result[0].target == "acme"

    def test_skips_unknown_format(self, service):
        relations = [{"foo": "bar"}]
        result = service._parse_relationships(relations)
        assert len(result) == 0

    def test_empty_list(self, service):
        assert service._parse_relationships([]) == []

    def test_none_input(self, service):
        assert service._parse_relationships(None) == []

    def test_defaults_types_to_entity(self, service):
        relations = [
            {
                "source": "x",
                "relation": "rel",
                "destination": "y",
            }
        ]
        result = service._parse_relationships(relations)
        assert result[0].source_type == "entity"
        assert result[0].target_type == "entity"


@pytest.mark.unit
class TestStoreMemory:
    async def test_store_memory_success(self, service):
        mock_client = AsyncMock()
        mock_client.add = AsyncMock(
            return_value={
                "results": [
                    {
                        "message": "Memory processing queued",
                        "status": "PENDING",
                        "event_id": "evt_123",
                    }
                ]
            }
        )

        with patch.object(service, "_get_client", return_value=mock_client):
            result = await service.store_memory("Test message", "user_123")

        assert result is not None
        assert result.content == "Memory processing queued"
        assert result.user_id == "user_123"

    async def test_store_memory_returns_none_for_invalid_user(self, service):
        result = await service.store_memory("Test", None)
        assert result is None

    async def test_store_memory_returns_none_on_error(self, service):
        mock_client = AsyncMock()
        mock_client.add = AsyncMock(side_effect=Exception("API error"))

        with patch.object(service, "_get_client", return_value=mock_client):
            result = await service.store_memory("Test", "user_123")

        assert result is None

    async def test_store_memory_returns_none_for_empty_results(self, service):
        mock_client = AsyncMock()
        mock_client.add = AsyncMock(return_value={"results": []})

        with patch.object(service, "_get_client", return_value=mock_client):
            result = await service.store_memory("Test", "user_123")

        assert result is None


@pytest.mark.unit
class TestSearchMemories:
    async def test_search_returns_results(self, service):
        mock_client = AsyncMock()
        mock_client.search = AsyncMock(
            return_value={
                "results": [
                    {"id": "m1", "memory": "Python expert", "score": 0.9}
                ],
                "relations": [],
            }
        )

        with patch.object(service, "_get_client", return_value=mock_client):
            result = await service.search_memories("programming", "user_123")

        assert isinstance(result, MemorySearchResult)
        assert result.total_count == 1
        assert result.memories[0].content == "Python expert"

    async def test_search_returns_empty_for_invalid_user(self, service):
        result = await service.search_memories("query", None)
        assert result.total_count == 0

    async def test_search_returns_empty_on_error(self, service):
        mock_client = AsyncMock()
        mock_client.search = AsyncMock(side_effect=Exception("API error"))

        with patch.object(service, "_get_client", return_value=mock_client):
            result = await service.search_memories("query", "user_123")

        assert result.total_count == 0


@pytest.mark.unit
class TestDeleteMemory:
    async def test_delete_returns_true_on_success(self, service):
        mock_client = AsyncMock()
        mock_client.delete = AsyncMock(return_value={"status": "ok"})

        with patch.object(service, "_get_client", return_value=mock_client):
            result = await service.delete_memory("mem_123", "user_123")

        assert result is True

    async def test_delete_returns_false_for_invalid_user(self, service):
        result = await service.delete_memory("mem_123", None)
        assert result is False

    async def test_delete_returns_false_on_error(self, service):
        mock_client = AsyncMock()
        mock_client.delete = AsyncMock(side_effect=Exception("API error"))

        with patch.object(service, "_get_client", return_value=mock_client):
            result = await service.delete_memory("mem_123", "user_123")

        assert result is False
