import uuid
from unittest.mock import MagicMock

import pytest

from app.agents.core.graph_manager import GraphManager


@pytest.mark.unit
class TestGraphManager:
    """Behavioural tests for GraphManager using the real ProviderRegistry.

    All tests use UUID-suffixed names to avoid cross-test pollution in the
    shared registry singleton.  No mocking of `providers` — if GraphManager
    passes the wrong key to the registry, the real registry will either raise
    KeyError (returning None via get_graph's except branch) or return the
    wrong object, and the assertion will fail.
    """

    @pytest.mark.asyncio
    async def test_set_graph_registers_provider(self):
        unique_name = f"test_sg_register_{uuid.uuid4().hex}"
        mock_graph = MagicMock(name="test_graph")

        GraphManager.set_graph(mock_graph, unique_name)
        result = await GraphManager.get_graph(unique_name)

        assert result is mock_graph, (
            f"get_graph('{unique_name}') returned {result!r} instead of the "
            "registered mock_graph. Fails if set_graph uses the wrong registry key."
        )

    @pytest.mark.asyncio
    async def test_get_graph_calls_provider_with_correct_key(self):
        unique_name = f"test_sg_key_{uuid.uuid4().hex}"
        mock_graph = MagicMock(name="test_graph")

        GraphManager.set_graph(mock_graph, unique_name)
        result = await GraphManager.get_graph(unique_name)

        assert result is mock_graph, (
            f"get_graph('{unique_name}') returned {result!r}. "
            "Fails if get_graph forwards a different key to the registry than the one supplied."
        )

    @pytest.mark.asyncio
    async def test_get_missing_graph(self):
        unregistered_name = f"test_sg_missing_{uuid.uuid4().hex}"

        result = await GraphManager.get_graph(unregistered_name)

        assert result is None

    @pytest.mark.asyncio
    async def test_get_graph_returns_none_not_sentinel_when_provider_returns_none(self):
        """get_graph must return exactly None — not a wrapper — when the provider
        yields None, and must look up the correct key in the registry."""
        unique_name = f"test_sg_null_{uuid.uuid4().hex}"

        GraphManager.set_graph(None, unique_name)
        result = await GraphManager.get_graph(unique_name)

        assert result is None


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
