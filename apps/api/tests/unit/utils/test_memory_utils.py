"""Unit tests for memory utility functions."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.utils.memory_utils import store_user_message_memory

# ---------------------------------------------------------------------------
# store_user_message_memory
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestStoreUserMessageMemory:
    """Tests for storing user messages in the memory service."""

    @patch("app.utils.memory_utils.memory_service")
    async def test_returns_dict_on_success(self, mock_mem_svc: MagicMock) -> None:
        mock_mem_svc.store_memory = AsyncMock(return_value=MagicMock())

        result = await store_user_message_memory("u1", "Hello", "conv_1")

        assert result is not None
        assert result["type"] == "memory_stored"
        assert "Hello" in result["content"]
        assert result["conversation_id"] == "conv_1"
        assert "timestamp" in result

    @patch("app.utils.memory_utils.memory_service")
    async def test_passes_correct_params_to_service(self, mock_mem_svc: MagicMock) -> None:
        mock_mem_svc.store_memory = AsyncMock(return_value=MagicMock())

        await store_user_message_memory("u1", "Hello world", "conv_2")

        mock_mem_svc.store_memory.assert_awaited_once()
        call_kwargs = mock_mem_svc.store_memory.call_args.kwargs
        assert call_kwargs["message"] == "Hello world"
        assert call_kwargs["user_id"] == "u1"
        assert call_kwargs["conversation_id"] == "conv_2"
        assert call_kwargs["async_mode"] is True
        assert call_kwargs["metadata"]["type"] == "user_message"
        assert call_kwargs["metadata"]["conversation_id"] == "conv_2"
        assert "timestamp" in call_kwargs["metadata"]

    @patch("app.utils.memory_utils.memory_service")
    async def test_returns_none_when_store_returns_none(self, mock_mem_svc: MagicMock) -> None:
        mock_mem_svc.store_memory = AsyncMock(return_value=None)

        result = await store_user_message_memory("u1", "msg", "conv_1")
        assert result is None

    @patch("app.utils.memory_utils.memory_service")
    async def test_returns_none_when_store_returns_falsy(self, mock_mem_svc: MagicMock) -> None:
        mock_mem_svc.store_memory = AsyncMock(return_value=0)

        result = await store_user_message_memory("u1", "msg", "conv_1")
        assert result is None

    @patch("app.utils.memory_utils.memory_service")
    async def test_returns_none_on_exception(self, mock_mem_svc: MagicMock) -> None:
        mock_mem_svc.store_memory = AsyncMock(side_effect=Exception("Mem0 down"))

        result = await store_user_message_memory("u1", "msg", "conv_1")
        assert result is None

    @patch("app.utils.memory_utils.memory_service")
    async def test_timestamp_is_utc_iso_format(self, mock_mem_svc: MagicMock) -> None:
        mock_mem_svc.store_memory = AsyncMock(return_value=MagicMock())

        result = await store_user_message_memory("u1", "msg", "conv_1")

        assert result is not None
        # Should be parseable as ISO format
        ts = datetime.fromisoformat(result["timestamp"])
        assert ts.tzinfo is not None or "+" in result["timestamp"] or "Z" in result["timestamp"]
