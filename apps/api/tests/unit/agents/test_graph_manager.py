from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.core.graph_manager import GraphManager


@pytest.mark.unit
class TestGraphManager:
    @pytest.mark.asyncio
    async def test_set_graph_registers_provider(self):
        mock_graph = MagicMock(name="test_graph")

        with patch(
            "app.agents.core.graph_manager.providers"
        ) as mock_providers:
            GraphManager.set_graph(mock_graph, "my_graph")

            mock_providers.register.assert_called_once()
            args, kwargs = mock_providers.register.call_args
            assert args[0] == "my_graph"
            assert kwargs["loader_func"]() is mock_graph

    @pytest.mark.asyncio
    async def test_set_and_get_graph_roundtrip(self):
        mock_graph = MagicMock(name="test_graph")

        with patch(
            "app.agents.core.graph_manager.providers"
        ) as mock_providers:
            mock_providers.aget = AsyncMock(return_value=mock_graph)

            GraphManager.set_graph(mock_graph, "my_graph")
            result = await GraphManager.get_graph("my_graph")

            assert result is mock_graph
            mock_providers.aget.assert_awaited_once_with("my_graph")

    @pytest.mark.asyncio
    async def test_get_missing_graph(self):
        with patch(
            "app.agents.core.graph_manager.providers"
        ) as mock_providers:
            mock_providers.aget = AsyncMock(side_effect=KeyError("not found"))

            result = await GraphManager.get_graph("nonexistent")

            assert result is None

    @pytest.mark.asyncio
    async def test_get_graph_error(self):
        with patch(
            "app.agents.core.graph_manager.providers"
        ) as mock_providers:
            mock_providers.aget = AsyncMock(
                side_effect=RuntimeError("provider failed")
            )

            result = await GraphManager.get_graph("broken")

            assert result is None

    @pytest.mark.asyncio
    async def test_get_graph_returns_none_from_provider(self):
        with patch(
            "app.agents.core.graph_manager.providers"
        ) as mock_providers:
            mock_providers.aget = AsyncMock(return_value=None)

            result = await GraphManager.get_graph("null_graph")

            assert result is None
