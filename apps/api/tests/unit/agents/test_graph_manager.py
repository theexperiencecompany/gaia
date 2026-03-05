import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.core.graph_manager import GraphManager


@pytest.mark.unit
class TestGraphManager:
    @pytest.mark.asyncio
    async def test_set_graph_registers_provider(self):
        mock_graph = MagicMock(name="test_graph")

        with patch("app.agents.core.graph_manager.providers") as mock_providers:
            GraphManager.set_graph(mock_graph, "my_graph")

            mock_providers.register.assert_called_once()
            args, kwargs = mock_providers.register.call_args
            assert args[0] == "my_graph"
            assert kwargs["loader_func"]() is mock_graph

    @pytest.mark.asyncio
    async def test_get_graph_calls_provider_with_correct_key(self):
        mock_graph = MagicMock(name="test_graph")

        with patch("app.agents.core.graph_manager.providers") as mock_providers:
            mock_providers.aget = AsyncMock(return_value=mock_graph)

            GraphManager.set_graph(mock_graph, "my_graph")
            result = await GraphManager.get_graph("my_graph")

            assert result is mock_graph
            mock_providers.aget.assert_awaited_once_with("my_graph")

    @pytest.mark.asyncio
    async def test_get_missing_graph(self):
        with patch("app.agents.core.graph_manager.providers") as mock_providers:
            mock_providers.aget = AsyncMock(side_effect=KeyError("not found"))

            result = await GraphManager.get_graph("nonexistent")

            assert result is None

    @pytest.mark.asyncio
    async def test_get_graph_error(self):
        with patch("app.agents.core.graph_manager.providers") as mock_providers:
            mock_providers.aget = AsyncMock(side_effect=RuntimeError("provider failed"))

            result = await GraphManager.get_graph("broken")

            assert result is None

    @pytest.mark.asyncio
    async def test_get_graph_returns_none_not_sentinel_when_provider_returns_none(self):
        """get_graph must return exactly None — not a wrapper — when the provider returns None,
        and must forward the correct key to the provider."""
        with patch("app.agents.core.graph_manager.providers") as mock_providers:
            mock_providers.aget = AsyncMock(return_value=None)

            result = await GraphManager.get_graph("null_graph")

            assert result is None
            assert type(result) is type(None)
            mock_providers.aget.assert_awaited_once_with("null_graph")


@pytest.mark.unit
class TestGraphManagerRoundTrip:
    """Verify the real set_graph → get_graph round-trip using the actual providers registry.

    These tests do NOT mock providers. They exercise the real ProviderRegistry singleton
    so that key-mapping bugs in GraphManager are caught — not just mock call patterns.
    Each test uses a UUID-suffixed name to avoid cross-test pollution in the shared registry.
    """

    @pytest.mark.asyncio
    async def test_set_then_get_returns_same_object(self):
        """set_graph then get_graph must return the exact same object."""
        unique_name = f"test_rt_graph_{uuid.uuid4().hex}"
        mock_graph = MagicMock(name="round_trip_graph")

        GraphManager.set_graph(mock_graph, unique_name)
        result = await GraphManager.get_graph(unique_name)

        assert result is mock_graph, (
            f"get_graph('{unique_name}') returned {result!r}, expected the mock_graph "
            "passed to set_graph. Fails if GraphManager uses the wrong key internally."
        )

    @pytest.mark.asyncio
    async def test_different_names_return_different_objects(self):
        """Two distinct graph names must each return their own registered object."""
        name_a = f"test_rt_a_{uuid.uuid4().hex}"
        name_b = f"test_rt_b_{uuid.uuid4().hex}"
        graph_a = MagicMock(name="graph_a")
        graph_b = MagicMock(name="graph_b")

        GraphManager.set_graph(graph_a, name_a)
        GraphManager.set_graph(graph_b, name_b)

        result_a = await GraphManager.get_graph(name_a)
        result_b = await GraphManager.get_graph(name_b)

        assert result_a is graph_a
        assert result_b is graph_b
        assert result_a is not result_b
