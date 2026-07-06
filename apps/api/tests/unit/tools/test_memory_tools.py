"""Unit tests for app.agents.tools.memory_tools."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.constants.memory import MemorySourceType, ReconcileOutcome
from app.models.memory_models import MemoryEntry, MemorySearchResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FAKE_USER_ID = "507f1f77bcf86cd799439011"

MODULE = "app.agents.tools.memory_tools"


def _make_config(user_id: str = FAKE_USER_ID) -> dict[str, Any]:
    """Return a minimal RunnableConfig-like dict with metadata.user_id."""
    return {"metadata": {"user_id": user_id}}


def _make_config_no_user() -> dict[str, Any]:
    """Config with no user_id to trigger auth errors."""
    return {"metadata": {}}


def _make_empty_config() -> None:
    """Falsy config to trigger the early 'config required' check."""
    return


def _make_memory_entry(
    memory_id: str = "mem-1",
    content: str = "Test memory",
    score: float = 0.95,
) -> MemoryEntry:
    """Create a real MemoryEntry for use in test results."""
    return MemoryEntry(
        id=memory_id,
        content=content,
        relevance_score=score,
    )


# ---------------------------------------------------------------------------
# Tests: add_memory
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAddMemory:
    """Tests for the add_memory tool."""

    @patch(f"{MODULE}.memory_engine")
    async def test_happy_path(
        self,
        mock_engine: MagicMock,
    ) -> None:
        """Successful memory storage returns the ID and folder."""
        stored = MemoryEntry(
            id="mem-1",
            content="User likes coffee",
            category_path="food-preferences",
        )
        retained_mock = MagicMock()
        retained_mock.entry = stored
        retained_mock.outcome = ReconcileOutcome.NEW
        mock_engine.retain_single = AsyncMock(return_value=retained_mock)

        from app.agents.tools.memory_tools import add_memory

        result = await add_memory.coroutine(
            config=_make_config(),
            content="User likes coffee",
        )

        assert "mem-1" in result
        assert "food-preferences" in result
        mock_engine.retain_single.assert_awaited_once_with(
            FAKE_USER_ID,
            "User likes coffee",
            category_path=None,
            source_type=MemorySourceType.TOOL,
        )

    async def test_no_user_id_returns_error(self) -> None:
        from app.agents.tools.memory_tools import add_memory

        result = await add_memory.coroutine(
            config=_make_config_no_user(),
            content="data",
        )

        assert "user_id not found in config" in result

    async def test_no_config_returns_error(self) -> None:
        """Falsy config triggers the early guard."""
        from app.agents.tools.memory_tools import add_memory

        # Empty dict {} is falsy; get_user_id_from_config returns "" → no user_id error
        result = await add_memory.coroutine(
            config={},
            content="data",
        )

        assert "user_id not found in config" in result

    @patch(f"{MODULE}.memory_engine")
    async def test_store_failure_returns_error_message(
        self,
        mock_engine: MagicMock,
    ) -> None:
        """When the engine raises an exception, tool returns a failure message."""
        mock_engine.retain_single = AsyncMock(side_effect=Exception("storage failed"))

        from app.agents.tools.memory_tools import add_memory

        result = await add_memory.coroutine(
            config=_make_config(),
            content="data",
        )

        assert "Error storing memory" in result


# ---------------------------------------------------------------------------
# Tests: search_memory
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSearchMemory:
    """Tests for the search_memory tool."""

    @patch(f"{MODULE}.memory_engine")
    async def test_happy_path(
        self,
        mock_engine: MagicMock,
    ) -> None:
        """Successful search returns formatted results."""
        memories = [
            _make_memory_entry("mem-1", "Likes coffee", 0.95),
            _make_memory_entry("mem-2", "Works at ACME", 0.80),
        ]
        mock_engine.recall = AsyncMock(
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
        mock_engine.recall.assert_awaited_once_with(
            FAKE_USER_ID, "coffee", limit=5, category_prefix=None
        )

    @patch(f"{MODULE}.memory_engine")
    async def test_custom_limit(
        self,
        mock_engine: MagicMock,
    ) -> None:
        """Custom limit is passed to service."""
        mock_engine.recall = AsyncMock(return_value=MemorySearchResult(memories=[], total_count=0))

        from app.agents.tools.memory_tools import search_memory

        await search_memory.coroutine(
            config=_make_config(),
            query="anything",
            limit=10,
        )

        call_kwargs = mock_engine.recall.call_args.kwargs
        assert call_kwargs["limit"] == 10

    @patch(f"{MODULE}.memory_engine")
    async def test_no_results(
        self,
        mock_engine: MagicMock,
    ) -> None:
        """Empty search results returns appropriate message."""
        mock_engine.recall = AsyncMock(return_value=MemorySearchResult(memories=[], total_count=0))

        from app.agents.tools.memory_tools import search_memory

        result = await search_memory.coroutine(
            config=_make_config(),
            query="nonexistent",
        )

        assert "No matching memories found" in result

    async def test_no_user_id_returns_error(self) -> None:
        from app.agents.tools.memory_tools import search_memory

        result = await search_memory.coroutine(
            config=_make_config_no_user(),
            query="test",
        )

        assert "user_id not found in config" in result

    async def test_no_config_returns_error(self) -> None:
        from app.agents.tools.memory_tools import search_memory

        # Empty dict {} is falsy; get_user_id_from_config returns "" → no user_id error
        result = await search_memory.coroutine(
            config={},
            query="test",
        )

        assert "user_id not found in config" in result

    @patch(f"{MODULE}.memory_engine")
    async def test_memory_without_score_omits_score(
        self,
        mock_engine: MagicMock,
    ) -> None:
        """Memories without relevance_score don't show score in output."""
        memory = MemoryEntry(
            id="mem-1",
            content="No score memory",
            relevance_score=None,
        )
        mock_engine.recall = AsyncMock(
            return_value=MemorySearchResult(memories=[memory], total_count=1)
        )

        from app.agents.tools.memory_tools import search_memory

        result = await search_memory.coroutine(
            config=_make_config(),
            query="test",
        )

        assert "No score memory" in result
        assert "score:" not in result

    @patch(f"{MODULE}.memory_engine")
    async def test_multiple_results_numbered(
        self,
        mock_engine: MagicMock,
    ) -> None:
        """Results are numbered sequentially in the output."""
        memories = [
            _make_memory_entry("m1", "First", 0.9),
            _make_memory_entry("m2", "Second", 0.8),
            _make_memory_entry("m3", "Third", 0.7),
        ]
        mock_engine.recall = AsyncMock(
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
