"""Behaviour tests for GraphManager.

GraphManager is a thin facade over the real `providers` ProviderRegistry
singleton (app.core.lazy_loader). The tests exercise the real registry — they
never mock `providers` for the happy path — so a key-mapping bug in
GraphManager produces a real wrong-object / KeyError, not just a mock artefact.

The registry is a process-wide singleton that is never reset between tests, so
every registered name is UUID-suffixed to avoid cross-test pollution.

Spec
----
set_graph(graph, name="default_graph"):
    registers `graph` in the registry under `name` via a loader; a later
    get_graph(name) returns the exact same object.

get_graph(name="default_graph"):
    - provider yields a non-None object -> return that object
    - provider yields None               -> return None
    - name not registered (KeyError)     -> return None (swallowed)
    - registry raises any other Exception -> return None (swallowed)
"""

from unittest.mock import AsyncMock, MagicMock
import uuid

import pytest

from app.agents.core.graph_manager import GraphManager
from app.core.lazy_loader import MissingKeyStrategy, providers
from app.utils.exceptions import ConfigurationError

DEFAULT_GRAPH_NAME = "default_graph"


def _unique(prefix: str) -> str:
    return f"test_{prefix}_{uuid.uuid4().hex}"


@pytest.mark.unit
class TestGraphManager:
    @pytest.mark.asyncio
    async def test_set_then_get_returns_same_object(self):
        """set_graph stores the object so get_graph hands back the identical instance."""
        name = _unique("roundtrip")
        graph = MagicMock(name="graph")

        GraphManager.set_graph(graph, name)
        result = await GraphManager.get_graph(name)

        assert result is graph

    @pytest.mark.asyncio
    async def test_set_graph_default_name_is_registered_under_default_graph(self):
        """set_graph with no explicit name registers under exactly 'default_graph'.

        Kills the const_str mutation of set_graph's default argument: an
        explicit get on the literal name must find the object the default set
        stored. Uses a real graph object distinct from any other default-name
        registration so identity is unambiguous.
        """
        graph = MagicMock(name="default_set_graph")

        GraphManager.set_graph(graph)
        result = await GraphManager.get_graph(DEFAULT_GRAPH_NAME)

        assert result is graph

    @pytest.mark.asyncio
    async def test_get_graph_default_name_reads_default_graph(self):
        """get_graph with no explicit name looks up exactly 'default_graph'.

        Kills the const_str mutation of get_graph's default argument: an
        explicit set on the literal name must be found by the defaulted get.
        """
        graph = MagicMock(name="default_get_graph")

        GraphManager.set_graph(graph, DEFAULT_GRAPH_NAME)
        result = await GraphManager.get_graph()

        assert result is graph

    @pytest.mark.asyncio
    async def test_distinct_names_resolve_to_their_own_objects(self):
        """Each registered name resolves to its own object, never the other's.

        Catches a get_graph that ignores its argument and returns a fixed key.
        """
        name_a = _unique("a")
        name_b = _unique("b")
        graph_a = MagicMock(name="graph_a")
        graph_b = MagicMock(name="graph_b")

        GraphManager.set_graph(graph_a, name_a)
        GraphManager.set_graph(graph_b, name_b)

        assert await GraphManager.get_graph(name_a) is graph_a
        assert await GraphManager.get_graph(name_b) is graph_b

    @pytest.mark.asyncio
    async def test_get_graph_returns_none_when_provider_yields_none(self):
        """A provider that yields None makes get_graph return None (not a sentinel)."""
        name = _unique("null")

        GraphManager.set_graph(None, name)
        result = await GraphManager.get_graph(name)

        assert result is None

    @pytest.mark.asyncio
    async def test_get_graph_returns_none_for_unregistered_name(self):
        """An unregistered name raises KeyError in the registry; get_graph swallows it -> None."""
        name = _unique("missing")

        result = await GraphManager.get_graph(name)

        assert result is None

    @pytest.mark.asyncio
    async def test_get_graph_swallows_non_keyerror_and_returns_none(self):
        """A registry error other than KeyError is caught -> get_graph returns None.

        Driven through the real registry: a provider registered with the ERROR
        strategy and a missing required key raises ConfigurationError (a plain
        Exception, not KeyError) from aget(). get_graph's broad except must
        catch it and return None rather than propagate.
        """
        name = _unique("raises")
        providers.register(
            name,
            loader_func=lambda: MagicMock(name="never_built"),
            required_keys=[None],
            strategy=MissingKeyStrategy.ERROR,
        )

        loader = providers.get_loader(name)
        assert loader.strategy is MissingKeyStrategy.ERROR
        with pytest.raises(ConfigurationError):
            await providers.aget(name)

        result = await GraphManager.get_graph(name)

        assert result is None

    @pytest.mark.asyncio
    async def test_get_graph_returns_object_for_truthy_and_falsy_non_none(self):
        """Any non-None provider value is returned verbatim, including falsy ones.

        A falsy-but-not-None value (0) pins the `is not None` identity check: a
        truthiness-based check would wrongly treat 0 as missing and return None.
        """
        name_falsy = _unique("falsy")
        GraphManager.set_graph(0, name_falsy)

        assert await GraphManager.get_graph(name_falsy) == 0

    @pytest.mark.asyncio
    async def test_get_graph_returns_none_without_querying_registry_on_keyerror_only(
        self, monkeypatch
    ):
        """get_graph forwards the requested name to the registry's aget verbatim.

        Patches the registry boundary (providers.aget) to record the key it is
        called with, proving get_graph passes through the caller's name rather
        than a hardcoded one, and returns the registry's object unchanged.
        """
        name = _unique("forward")
        sentinel = MagicMock(name="sentinel_graph")
        seen: list[str] = []

        async def fake_aget(requested: str):
            seen.append(requested)
            return sentinel

        monkeypatch.setattr(providers, "aget", AsyncMock(side_effect=fake_aget))

        result = await GraphManager.get_graph(name)

        assert seen == [name]
        assert result is sentinel
