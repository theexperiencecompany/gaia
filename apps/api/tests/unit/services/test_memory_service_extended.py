"""Extended unit tests for MemoryService (app/services/memory_service.py).

Supplements existing test_memory_service.py to cover:
- store_memory_batch (all branches)
- search_agent_memories
- get_all_memories
- delete_all_memories
- get_project_info
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.memory_models import MemorySearchResult
from app.services.memory_service import MemoryService


@pytest.fixture
def service():
    return MemoryService()


# ---------------------------------------------------------------------------
# store_memory_batch
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestStoreMemoryBatch:
    async def test_returns_false_when_no_user_or_agent(self, service):
        result = await service.store_memory_batch(
            [{"role": "user", "content": "hi"}], user_id=None, agent_id=None
        )
        assert result is False

    async def test_returns_false_for_empty_user_and_no_agent(self, service):
        result = await service.store_memory_batch(
            [{"role": "user", "content": "hi"}], user_id="", agent_id=None
        )
        assert result is False

    async def test_success_with_user_id(self, service):
        mock_client = AsyncMock()
        mock_client.add = AsyncMock(
            return_value={
                "results": [
                    {"id": "m1", "memory": "stored", "event": "ADD"},
                    {"id": "m2", "memory": "stored2", "event": "ADD"},
                ]
            }
        )

        with patch.object(service, "_get_client", return_value=mock_client):
            result = await service.store_memory_batch(
                [
                    {"role": "user", "content": "first"},
                    {"role": "assistant", "content": "second"},
                ],
                user_id="user_123",
            )

        assert result is True
        call_kwargs = mock_client.add.call_args.kwargs
        assert call_kwargs["user_id"] == "user_123"
        assert call_kwargs["async_mode"] is True

    async def test_success_with_agent_id_only(self, service):
        mock_client = AsyncMock()
        mock_client.add = AsyncMock(
            return_value={"results": [{"event": "ADD", "id": "m1", "memory": "x"}]}
        )

        with patch.object(service, "_get_client", return_value=mock_client):
            result = await service.store_memory_batch(
                [{"role": "user", "content": "skill data"}],
                user_id=None,
                agent_id="gaia_agent_123",
            )

        assert result is True
        call_kwargs = mock_client.add.call_args.kwargs
        assert "user_id" not in call_kwargs
        assert call_kwargs["agent_id"] == "gaia_agent_123"

    async def test_passes_custom_instructions(self, service):
        mock_client = AsyncMock()
        mock_client.add = AsyncMock(
            return_value={"results": [{"event": "ADD", "id": "m1", "memory": "x"}]}
        )

        with patch.object(service, "_get_client", return_value=mock_client):
            await service.store_memory_batch(
                [{"role": "user", "content": "msg"}],
                user_id="u1",
                custom_instructions="Be concise",
            )

        call_kwargs = mock_client.add.call_args.kwargs
        assert call_kwargs["custom_instructions"] == "Be concise"

    async def test_passes_infer_false(self, service):
        mock_client = AsyncMock()
        mock_client.add = AsyncMock(
            return_value={"results": [{"event": "ADD", "id": "m1", "memory": "x"}]}
        )

        with patch.object(service, "_get_client", return_value=mock_client):
            await service.store_memory_batch(
                [{"role": "user", "content": "raw data"}],
                user_id="u1",
                infer=False,
            )

        call_kwargs = mock_client.add.call_args.kwargs
        assert call_kwargs["infer"] is False

    async def test_returns_false_for_empty_results(self, service):
        mock_client = AsyncMock()
        mock_client.add = AsyncMock(return_value={"results": []})

        with patch.object(service, "_get_client", return_value=mock_client):
            result = await service.store_memory_batch(
                [{"role": "user", "content": "msg"}], user_id="u1"
            )

        assert result is False

    async def test_direct_list_response(self, service):
        mock_client = AsyncMock()
        mock_client.add = AsyncMock(return_value=[{"id": "m1", "memory": "test"}])

        with patch.object(service, "_get_client", return_value=mock_client):
            result = await service.store_memory_batch(
                [{"role": "user", "content": "msg"}], user_id="u1"
            )

        assert result is True

    async def test_empty_list_response_returns_false(self, service):
        mock_client = AsyncMock()
        mock_client.add = AsyncMock(return_value=[])

        with patch.object(service, "_get_client", return_value=mock_client):
            result = await service.store_memory_batch(
                [{"role": "user", "content": "msg"}], user_id="u1"
            )

        assert result is False

    async def test_unexpected_response_format_returns_false(self, service):
        mock_client = AsyncMock()
        mock_client.add = AsyncMock(return_value="unexpected")

        with patch.object(service, "_get_client", return_value=mock_client):
            result = await service.store_memory_batch(
                [{"role": "user", "content": "msg"}], user_id="u1"
            )

        assert result is False

    async def test_exception_returns_false(self, service):
        mock_client = AsyncMock()
        mock_client.add = AsyncMock(side_effect=Exception("API error"))

        with patch.object(service, "_get_client", return_value=mock_client):
            result = await service.store_memory_batch(
                [{"role": "user", "content": "msg"}], user_id="u1"
            )

        assert result is False

    async def test_zero_result_count_warns(self, service):
        mock_client = AsyncMock()
        # "results" key present but empty list
        mock_client.add = AsyncMock(return_value={"results": []})

        with patch.object(service, "_get_client", return_value=mock_client):
            result = await service.store_memory_batch(
                [{"role": "user", "content": "msg"}], user_id="u1"
            )

        assert result is False

    async def test_with_conversation_id_and_metadata(self, service):
        mock_client = AsyncMock()
        mock_client.add = AsyncMock(
            return_value={"results": [{"event": "ADD", "id": "m1", "memory": "x"}]}
        )

        with patch.object(service, "_get_client", return_value=mock_client):
            result = await service.store_memory_batch(
                [{"role": "user", "content": "msg"}],
                user_id="u1",
                conversation_id="conv_123",
                metadata={"source": "chat"},
            )

        assert result is True
        call_kwargs = mock_client.add.call_args.kwargs
        assert call_kwargs["run_id"] == "conv_123"
        assert "source" in call_kwargs["metadata"]
        assert "timestamp" in call_kwargs["metadata"]


# ---------------------------------------------------------------------------
# search_agent_memories
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSearchAgentMemories:
    async def test_returns_empty_for_no_agent_id(self, service):
        result = await service.search_agent_memories("query", "")
        assert isinstance(result, MemorySearchResult)
        assert result.total_count == 0

    async def test_returns_results(self, service):
        mock_client = AsyncMock()
        mock_client.search = AsyncMock(
            return_value={
                "results": [{"id": "m1", "memory": "Gaia can do X", "score": 0.9}],
                "relations": [],
            }
        )

        with patch.object(service, "_get_client", return_value=mock_client):
            result = await service.search_agent_memories("capabilities", "agent_123")

        assert result.total_count == 1
        assert result.memories[0].content == "Gaia can do X"
        # search called with agent_id filter
        call_kwargs = mock_client.search.call_args.kwargs
        assert call_kwargs["filters"] == {"agent_id": "agent_123"}

    async def test_includes_relations(self, service):
        mock_client = AsyncMock()
        mock_client.search = AsyncMock(
            return_value={
                "results": [{"id": "m1", "memory": "data", "score": 0.8}],
                "relations": [
                    {"source": "gaia", "relation": "supports", "destination": "MCP"}
                ],
            }
        )

        with patch.object(service, "_get_client", return_value=mock_client):
            result = await service.search_agent_memories("MCP", "agent_123")

        assert len(result.relations) == 1
        assert result.relations[0].source == "gaia"

    async def test_list_response_fallback(self, service):
        mock_client = AsyncMock()
        mock_client.search = AsyncMock(
            return_value=[{"id": "m1", "memory": "Direct list", "score": 0.7}]
        )

        with patch.object(service, "_get_client", return_value=mock_client):
            result = await service.search_agent_memories("query", "agent_123")

        assert result.total_count == 1

    async def test_unexpected_format_returns_empty(self, service):
        mock_client = AsyncMock()
        mock_client.search = AsyncMock(return_value="unexpected")

        with patch.object(service, "_get_client", return_value=mock_client):
            result = await service.search_agent_memories("query", "agent_123")

        assert result.total_count == 0

    async def test_error_returns_empty(self, service):
        mock_client = AsyncMock()
        mock_client.search = AsyncMock(side_effect=Exception("fail"))

        with patch.object(service, "_get_client", return_value=mock_client):
            result = await service.search_agent_memories("query", "agent_123")

        assert result.total_count == 0


# ---------------------------------------------------------------------------
# get_all_memories
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetAllMemories:
    async def test_returns_empty_for_invalid_user(self, service):
        result = await service.get_all_memories(None)
        assert isinstance(result, MemorySearchResult)
        assert result.total_count == 0

    async def test_returns_memories_and_relations(self, service):
        mock_client = AsyncMock()
        mock_client.get_all = AsyncMock(
            return_value={
                "results": [
                    {"id": "m1", "memory": "Likes Python"},
                    {"id": "m2", "memory": "Uses Mac"},
                ],
                "relations": [
                    {"source": "user", "relation": "uses", "destination": "Mac"}
                ],
            }
        )

        with patch.object(service, "_get_client", return_value=mock_client):
            result = await service.get_all_memories("user_123")

        assert result.total_count == 2
        assert len(result.relations) == 1
        # Verify called with correct filters
        call_kwargs = mock_client.get_all.call_args.kwargs
        assert call_kwargs["output_format"] == "v1.1"

    async def test_error_returns_empty(self, service):
        mock_client = AsyncMock()
        mock_client.get_all = AsyncMock(side_effect=Exception("fail"))

        with patch.object(service, "_get_client", return_value=mock_client):
            result = await service.get_all_memories("user_123")

        assert result.total_count == 0


# ---------------------------------------------------------------------------
# delete_all_memories
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDeleteAllMemories:
    async def test_returns_false_for_invalid_user(self, service):
        result = await service.delete_all_memories(None)
        assert result is False

    async def test_returns_true_on_success(self, service):
        mock_client = AsyncMock()
        mock_client.delete_all = AsyncMock(return_value={"status": "ok"})

        with patch.object(service, "_get_client", return_value=mock_client):
            result = await service.delete_all_memories("user_123")

        assert result is True
        mock_client.delete_all.assert_called_once_with(user_id="user_123")

    async def test_returns_false_on_error(self, service):
        mock_client = AsyncMock()
        mock_client.delete_all = AsyncMock(side_effect=Exception("fail"))

        with patch.object(service, "_get_client", return_value=mock_client):
            result = await service.delete_all_memories("user_123")

        assert result is False


# ---------------------------------------------------------------------------
# get_project_info
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetProjectInfo:
    async def test_returns_project_info(self, service):
        mock_project = AsyncMock()
        mock_project.get = AsyncMock(return_value={"graph_memory": True})

        mock_client = AsyncMock()
        mock_client.project = mock_project

        with patch.object(service, "_get_client", return_value=mock_client):
            result = await service.get_project_info()

        assert result["success"] is True
        assert result["project_info"] == {"graph_memory": True}

    async def test_returns_not_available_when_no_project_attr(self, service):
        mock_client = AsyncMock(spec=[])  # No attributes

        with patch.object(service, "_get_client", return_value=mock_client):
            result = await service.get_project_info()

        assert result["success"] is False
        assert "not available" in result["message"]

    async def test_returns_error_on_exception(self, service):
        mock_project = AsyncMock()
        mock_project.get = AsyncMock(side_effect=Exception("api error"))

        mock_client = AsyncMock()
        mock_client.project = mock_project

        with patch.object(service, "_get_client", return_value=mock_client):
            result = await service.get_project_info()

        assert result["success"] is False
        assert "api error" in result["error"]

    async def test_project_has_get_but_no_project(self, service):
        """Client has project attr but project has no get method."""
        mock_client = AsyncMock()
        mock_client.project = MagicMock(spec=[])  # has project but no get

        with patch.object(service, "_get_client", return_value=mock_client):
            result = await service.get_project_info()

        assert result["success"] is False


# ---------------------------------------------------------------------------
# store_memory edge cases (async pending with no event_id)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestStoreMemoryAsyncEdgeCases:
    async def test_async_pending_no_event_id_returns_none(self, service):
        """PENDING response without event_id should return None."""
        mock_client = AsyncMock()
        mock_client.add = AsyncMock(
            return_value={"results": [{"status": "PENDING", "message": "queued"}]}
        )

        with patch.object(service, "_get_client", return_value=mock_client):
            result = await service.store_memory("Test", "user_123")

        assert result is None

    async def test_store_memory_with_metadata_and_conversation(self, service):
        mock_client = AsyncMock()
        mock_client.add = AsyncMock(
            return_value={
                "results": [
                    {
                        "id": "mem_1",
                        "memory": "User likes coffee",
                        "event": "ADD",
                        "structured_attributes": {},
                    }
                ]
            }
        )

        with patch.object(service, "_get_client", return_value=mock_client):
            result = await service.store_memory(
                "I like coffee",
                "user_123",
                conversation_id="conv_abc",
                metadata={"source": "chat"},
                async_mode=False,
            )

        assert result is not None
        assert result.user_id == "user_123"
        call_kwargs = mock_client.add.call_args.kwargs
        assert call_kwargs["run_id"] == "conv_abc"
        assert call_kwargs["async_mode"] is False
        assert "source" in call_kwargs["metadata"]


# ---------------------------------------------------------------------------
# _parse_add_result edge: async with event_id via is_async flag
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestParseAddResultAsyncEventId:
    def test_async_flag_with_event_id(self, service):
        raw = {"event_id": "evt_999", "message": "Processing"}
        entry = service._parse_add_result(raw, is_async=True)
        assert entry is not None
        assert entry.id == "evt_999"
        assert entry.metadata["async_mode"] is True

    def test_async_flag_without_event_id(self, service):
        raw = {"message": "Processing"}
        entry = service._parse_add_result(raw, is_async=True)
        # No event_id and no PENDING status => falls through to sync path
        # sync path has no "memory" content => returns None
        assert entry is None
