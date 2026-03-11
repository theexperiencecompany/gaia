"""Unit tests for GraphManager that exercise real production code paths.

Each test uses a fresh ProviderRegistry injected via monkeypatch so the
global `providers` singleton is never mutated between tests.  Because the
registry is real (not mocked), deleting or breaking any method under test
will cause the relevant assertion to fail.
"""

from unittest.mock import MagicMock

import pytest

from app.agents.core.graph_manager import GraphManager
from app.core.lazy_loader import ProviderRegistry


@pytest.mark.unit
class TestGraphManager:
    """Tests for GraphManager using real ProviderRegistry instances."""

    @pytest.fixture(autouse=True)
    def isolated_registry(self, monkeypatch: pytest.MonkeyPatch) -> ProviderRegistry:
        """Replace the module-level `providers` singleton with a fresh registry.

        This prevents test pollution and ensures each test starts with an
        empty registry while still exercising real ProviderRegistry logic.
        """
        registry = ProviderRegistry()
        monkeypatch.setattr(
            "app.agents.core.graph_manager.providers",
            registry,
        )
        return registry

    # ------------------------------------------------------------------
    # set_graph registers a provider that returns the graph object
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_set_graph_registers_provider(
        self, isolated_registry: ProviderRegistry
    ):
        mock_graph = MagicMock(name="test_graph")

        GraphManager.set_graph(mock_graph, "my_graph")

        assert isolated_registry.is_initialized("my_graph") is False
        # Provider must be present in the registry after set_graph
        assert "my_graph" in isolated_registry._providers

    # ------------------------------------------------------------------
    # get_graph returns the exact object that was registered
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_get_graph_returns_registered_object(self):
        mock_graph = MagicMock(name="test_graph")

        GraphManager.set_graph(mock_graph, "my_graph")
        result = await GraphManager.get_graph("my_graph")

        # Real ProviderRegistry.aget -> LazyLoader.aget -> loader_func()
        assert result is mock_graph

    # ------------------------------------------------------------------
    # get_graph returns None (not KeyError) for an unregistered name
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_get_missing_graph_returns_none(self):
        result = await GraphManager.get_graph("nonexistent")

        assert result is None

    # ------------------------------------------------------------------
    # Caching: the same instance is returned on every subsequent call
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_get_graph_returns_same_instance_on_repeated_calls(self):
        mock_graph = MagicMock(name="cached_graph")
        GraphManager.set_graph(mock_graph, "cached")

        first = await GraphManager.get_graph("cached")
        second = await GraphManager.get_graph("cached")
        third = await GraphManager.get_graph("cached")

        assert first is mock_graph
        assert second is mock_graph
        assert third is mock_graph
        # All three calls must return the identical object (LazyLoader caches it)
        assert first is second is third

    # ------------------------------------------------------------------
    # Caching: loader_func is only invoked once even on multiple gets
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_loader_func_called_only_once(
        self, isolated_registry: ProviderRegistry
    ):
        mock_graph = MagicMock(name="expensive_graph")
        call_count = 0

        def counting_loader():
            nonlocal call_count
            call_count += 1
            return mock_graph

        isolated_registry.register("counted", loader_func=counting_loader)

        await GraphManager.get_graph("counted")
        await GraphManager.get_graph("counted")
        await GraphManager.get_graph("counted")

        assert call_count == 1

    # ------------------------------------------------------------------
    # set_graph a second time replaces the previous graph
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_set_graph_replaces_previous_graph(self):
        graph_v1 = MagicMock(name="graph_v1")
        graph_v2 = MagicMock(name="graph_v2")

        GraphManager.set_graph(graph_v1, "replaceable")
        result_v1 = await GraphManager.get_graph("replaceable")
        assert result_v1 is graph_v1

        # Register a new graph under the same name
        GraphManager.set_graph(graph_v2, "replaceable")
        result_v2 = await GraphManager.get_graph("replaceable")
        assert result_v2 is graph_v2
        # Must be the new object, not the old one
        assert result_v2 is not graph_v1

    # ------------------------------------------------------------------
    # default graph name is "default_graph" when none is supplied
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_default_graph_name(self):
        mock_graph = MagicMock(name="default")

        GraphManager.set_graph(mock_graph)  # no explicit name
        result = await GraphManager.get_graph()  # no explicit name

        assert result is mock_graph

    # ------------------------------------------------------------------
    # Multiple graphs coexist under different names
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_multiple_graphs_are_independent(self):
        graph_a = MagicMock(name="graph_a")
        graph_b = MagicMock(name="graph_b")

        GraphManager.set_graph(graph_a, "agent_a")
        GraphManager.set_graph(graph_b, "agent_b")

        result_a = await GraphManager.get_graph("agent_a")
        result_b = await GraphManager.get_graph("agent_b")

        assert result_a is graph_a
        assert result_b is graph_b
        assert result_a is not result_b

    # ------------------------------------------------------------------
    # get_graph returns None when the provider's loader raises an error
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_get_graph_returns_none_when_loader_raises(
        self, isolated_registry: ProviderRegistry
    ):
        def failing_loader():
            raise RuntimeError("provider exploded")

        isolated_registry.register("broken", loader_func=failing_loader)

        result = await GraphManager.get_graph("broken")

        assert result is None
