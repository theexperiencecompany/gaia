"""Unit tests for app.agents.tools.memory_tools."""

from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.memory_models import MemoryEntry, MemorySearchResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FAKE_USER_ID = "507f1f77bcf86cd799439011"

MODULE = "app.agents.tools.memory_tools"


def _make_config(user_id: str = FAKE_USER_ID) -> Dict[str, Any]:
    """Return a minimal RunnableConfig-like dict with metadata.user_id."""
    return {"metadata": {"user_id": user_id}}


def _make_config_no_user() -> Dict[str, Any]:
    """Config with no user_id to trigger auth errors."""
    return {"metadata": {}}


def _make_empty_config() -> None:
    """Falsy config to trigger the early 'config required' check."""
    return None


def _make_memory_entry(
    memory_id: str = "mem-1",
    content: str = "Test memory",
    score: float = 0.95,
) -> MemoryEntry:
    """Create a real MemoryEntry for use in test results."""
    return MemoryEntry(
        id=memory_id,
        content=content,
        user_id=FAKE_USER_ID,
        relevance_score=score,
    )


# ---------------------------------------------------------------------------
# Tests: add_memory
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAddMemory:
    """Tests for the add_memory tool."""

    @patch(f"{MODULE}.memory_service")
    async def test_happy_path_async_mode(
        self,
        mock_service: MagicMock,
    ) -> None:
        """Successful memory storage in async mode returns event_id."""
        stored = MemoryEntry(
            id="mem-1",
            content="User likes coffee",
            metadata={"event_id": "evt-123", "status": "queued"},
        )
        mock_service.store_memory = AsyncMock(return_value=stored)

        from app.agents.tools.memory_tools import add_memory

        result = await add_memory.coroutine(
            config=_make_config(),
            content="User likes coffee",
        )

        assert "evt-123" in result
        assert "queued" in result
        mock_service.store_memory.assert_awaited_once_with(
            message="User likes coffee",
            user_id=FAKE_USER_ID,
            metadata={},
            async_mode=True,
        )

    @patch(f"{MODULE}.memory_service")
    async def test_happy_path_sync_mode_fallback(
        self,
        mock_service: MagicMock,
    ) -> None:
        """When there is no event_id, falls back to sync response format."""
        stored = MemoryEntry(
            id="mem-42",
            content="Stored sync",
            metadata={},
        )
        mock_service.store_memory = AsyncMock(return_value=stored)

        from app.agents.tools.memory_tools import add_memory

        result = await add_memory.coroutine(
            config=_make_config(),
            content="Stored sync",
        )

        assert "mem-42" in result
        assert "stored successfully" in result.lower()

    @patch(f"{MODULE}.memory_service")
    async def test_with_metadata(
        self,
        mock_service: MagicMock,
    ) -> None:
        """Metadata is passed through to the service layer."""
        stored = MemoryEntry(
            id="mem-1",
            content="data",
            metadata={"event_id": "e1", "status": "queued"},
        )
        mock_service.store_memory = AsyncMock(return_value=stored)

        from app.agents.tools.memory_tools import add_memory

        await add_memory.coroutine(
            config=_make_config(),
            content="data",
            metadata={"source": "chat"},
        )

        call_kwargs = mock_service.store_memory.call_args.kwargs
        assert call_kwargs["metadata"] == {"source": "chat"}

    @patch(f"{MODULE}.memory_service")
    async def test_no_user_id_returns_error(
        self,
        mock_service: MagicMock,
    ) -> None:
        from app.agents.tools.memory_tools import add_memory

        result = await add_memory.coroutine(
            config=_make_config_no_user(),
            content="data",
        )

        assert "User ID is required" in result

    async def test_no_config_returns_error(self) -> None:
        """Falsy config triggers the early guard."""
        from app.agents.tools.memory_tools import add_memory

        # Pass an empty dict which is falsy in Python (`bool({})` is False)
        # The tool checks `if not config:` -- an empty dict is falsy
        result = await add_memory.coroutine(
            config={},
            content="data",
        )

        # Empty dict {} is falsy, so the tool returns early with config error
        assert "Configuration required" in result

    @patch(f"{MODULE}.memory_service")
    async def test_store_returns_none(
        self,
        mock_service: MagicMock,
    ) -> None:
        """When service returns None, tool should return failure message."""
        mock_service.store_memory = AsyncMock(return_value=None)

        from app.agents.tools.memory_tools import add_memory

        result = await add_memory.coroutine(
            config=_make_config(),
            content="data",
        )

        assert "Failed to store memory" in result

    @patch(f"{MODULE}.memory_service")
    async def test_default_metadata_is_empty_dict(
        self,
        mock_service: MagicMock,
    ) -> None:
        """When metadata is not provided, it defaults to {}."""
        stored = MemoryEntry(
            id="mem-1",
            content="test",
            metadata={"event_id": "e", "status": "ok"},
        )
        mock_service.store_memory = AsyncMock(return_value=stored)

        from app.agents.tools.memory_tools import add_memory

        await add_memory.coroutine(
            config=_make_config(),
            content="test",
        )

        call_kwargs = mock_service.store_memory.call_args.kwargs
        assert call_kwargs["metadata"] == {}


# ---------------------------------------------------------------------------
# Tests: search_memory
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSearchMemory:
    """Tests for the search_memory tool."""

    @patch(f"{MODULE}.memory_service")
    async def test_happy_path(
        self,
        mock_service: MagicMock,
    ) -> None:
        """Successful search returns formatted results."""
        memories = [
            _make_memory_entry("mem-1", "Likes coffee", 0.95),
            _make_memory_entry("mem-2", "Works at ACME", 0.80),
        ]
        mock_service.search_memories = AsyncMock(
            return_value=MemorySearchResult(memories=memories, total_count=2)
        )

        from app.agents.tools.memory_tools import search_memory

        result = await search_memory.coroutine(
            config=_make_config(),
            query="coffee",
        )

        assert "Likes coffee" in result
        assert "Works at ACME" in result
        assert "0.95" in result
        mock_service.search_memories.assert_awaited_once_with(
            query="coffee",
            user_id=FAKE_USER_ID,
            limit=5,
        )

    @patch(f"{MODULE}.memory_service")
    async def test_custom_limit(
        self,
        mock_service: MagicMock,
    ) -> None:
        """Custom limit is passed to service."""
        mock_service.search_memories = AsyncMock(
            return_value=MemorySearchResult(memories=[], total_count=0)
        )

        from app.agents.tools.memory_tools import search_memory

        await search_memory.coroutine(
            config=_make_config(),
            query="anything",
            limit=10,
        )

        call_kwargs = mock_service.search_memories.call_args.kwargs
        assert call_kwargs["limit"] == 10

    @patch(f"{MODULE}.memory_service")
    async def test_no_results(
        self,
        mock_service: MagicMock,
    ) -> None:
        """Empty search results returns appropriate message."""
        mock_service.search_memories = AsyncMock(
            return_value=MemorySearchResult(memories=[], total_count=0)
        )

        from app.agents.tools.memory_tools import search_memory

        result = await search_memory.coroutine(
            config=_make_config(),
            query="nonexistent",
        )

        assert "No matching memories found" in result

    @patch(f"{MODULE}.memory_service")
    async def test_no_user_id_returns_error(
        self,
        mock_service: MagicMock,
    ) -> None:
        from app.agents.tools.memory_tools import search_memory

        result = await search_memory.coroutine(
            config=_make_config_no_user(),
            query="test",
        )

        assert "User ID is required" in result

    async def test_no_config_returns_error(self) -> None:
        from app.agents.tools.memory_tools import search_memory

        # Empty dict {} is falsy, so the tool returns early with config error
        result = await search_memory.coroutine(
            config={},
            query="test",
        )

        assert "Configuration required" in result

    @patch(f"{MODULE}.memory_service")
    async def test_memory_without_score_omits_score(
        self,
        mock_service: MagicMock,
    ) -> None:
        """Memories without relevance_score don't show score in output."""
        memory = MemoryEntry(
            id="mem-1",
            content="No score memory",
            relevance_score=None,
        )
        mock_service.search_memories = AsyncMock(
            return_value=MemorySearchResult(memories=[memory], total_count=1)
        )

        from app.agents.tools.memory_tools import search_memory

        result = await search_memory.coroutine(
            config=_make_config(),
            query="test",
        )

        assert "No score memory" in result
        assert "score:" not in result

    @patch(f"{MODULE}.memory_service")
    async def test_multiple_results_numbered(
        self,
        mock_service: MagicMock,
    ) -> None:
        """Results are numbered sequentially in the output."""
        memories = [
            _make_memory_entry("m1", "First", 0.9),
            _make_memory_entry("m2", "Second", 0.8),
            _make_memory_entry("m3", "Third", 0.7),
        ]
        mock_service.search_memories = AsyncMock(
            return_value=MemorySearchResult(memories=memories, total_count=3)
        )

        from app.agents.tools.memory_tools import search_memory

        result = await search_memory.coroutine(
            config=_make_config(),
            query="all",
        )

        assert "1." in result
        assert "2." in result
        assert "3." in result
