"""Integration tests for the lazy loader / provider registration system.

Tests ProviderRegistry and LazyLoader behavior including registration,
initialization, missing key handling, and async providers.
"""

import asyncio

import pytest

from app.core.lazy_loader import (
    LazyLoader,
    MissingKeyStrategy,
    ProviderRegistry,
)
from app.utils.exceptions import ConfigurationError


@pytest.mark.integration
class TestProviderRegistry:
    """Test the ProviderRegistry register/get lifecycle."""

    def test_register_and_get_sync_provider(self):
        """Registering a sync provider and getting it should call the loader."""
        registry = ProviderRegistry()
        registry.register(
            name="test_sync",
            loader_func=lambda: "sync-value",
            required_keys=["non-empty"],
            strategy=MissingKeyStrategy.WARN,
        )
        result = registry.get("test_sync")
        assert result == "sync-value"

    def test_get_unregistered_provider_raises(self):
        """Getting an unregistered provider should raise KeyError."""
        registry = ProviderRegistry()
        with pytest.raises(KeyError, match="not found"):
            registry.get("nonexistent")

    async def test_register_and_aget_async_provider(self):
        """Registering an async provider and aget() should await the loader."""
        registry = ProviderRegistry()

        async def async_loader():
            return "async-value"

        registry.register(
            name="test_async",
            loader_func=async_loader,
            required_keys=["non-empty"],
            strategy=MissingKeyStrategy.WARN,
        )
        result = await registry.aget("test_async")
        assert result == "async-value"

    def test_provider_returns_none_when_keys_missing_warn_strategy(self):
        """With WARN strategy and missing keys, get() should return None."""
        registry = ProviderRegistry()
        registry.register(
            name="missing_keys",
            loader_func=lambda: "should-not-run",
            required_keys=[None],  # None is considered missing
            strategy=MissingKeyStrategy.WARN,
        )
        result = registry.get("missing_keys")
        assert result is None

    def test_provider_raises_when_keys_missing_error_strategy(self):
        """With ERROR strategy and missing keys, get() should raise ConfigurationError."""
        registry = ProviderRegistry()
        registry.register(
            name="error_keys",
            loader_func=lambda: "should-not-run",
            required_keys=[None],
            strategy=MissingKeyStrategy.ERROR,
        )
        with pytest.raises(ConfigurationError, match="missing values"):
            registry.get("error_keys")

    def test_provider_silent_returns_none(self):
        """With SILENT strategy and missing keys, get() returns None without logging."""
        registry = ProviderRegistry()
        registry.register(
            name="silent_missing",
            loader_func=lambda: "should-not-run",
            required_keys=["", None],
            strategy=MissingKeyStrategy.SILENT,
        )
        result = registry.get("silent_missing")
        assert result is None

    def test_auto_initialize_sync_provider(self):
        """Auto-initialized sync providers should be ready immediately."""
        registry = ProviderRegistry()
        registry.register(
            name="auto_sync",
            loader_func=lambda: "auto-value",
            required_keys=["present"],
            strategy=MissingKeyStrategy.WARN,
            auto_initialize=True,
        )
        assert registry.is_initialized("auto_sync")
        assert registry.get("auto_sync") == "auto-value"

    def test_provider_caches_after_first_get(self):
        """The loader should only be called once; subsequent gets return cached."""
        call_count = {"n": 0}

        def counting_loader():
            call_count["n"] += 1
            return f"value-{call_count['n']}"

        registry = ProviderRegistry()
        registry.register(
            name="cached",
            loader_func=counting_loader,
            required_keys=["ok"],
            strategy=MissingKeyStrategy.WARN,
        )
        first = registry.get("cached")
        second = registry.get("cached")
        assert first == second == "value-1"
        assert call_count["n"] == 1

    def test_list_providers(self):
        """list_providers should return status for all registered providers."""
        registry = ProviderRegistry()
        registry.register(
            name="p1",
            loader_func=lambda: "v1",
            required_keys=["ok"],
        )
        registry.register(
            name="p2",
            loader_func=lambda: "v2",
            required_keys=[None],
        )
        listing = registry.list_providers()
        assert "p1" in listing
        assert "p2" in listing
        assert listing["p1"]["available"] is True
        assert listing["p2"]["available"] is False

    def test_is_available_checks_keys(self):
        """is_available should reflect whether required keys are present."""
        registry = ProviderRegistry()
        registry.register(
            name="avail",
            loader_func=lambda: "x",
            required_keys=["present"],
        )
        registry.register(
            name="not_avail",
            loader_func=lambda: "x",
            required_keys=[None],
        )
        assert registry.is_available("avail") is True
        assert registry.is_available("not_avail") is False
        assert registry.is_available("unknown") is False


@pytest.mark.integration
class TestLazyLoader:
    """Test LazyLoader directly."""

    def test_reset_clears_cached_instance(self):
        """reset() should clear the cached instance so next get() re-initializes."""
        loader = LazyLoader(
            loader_func=lambda: "initial",
            required_keys=["ok"],
            strategy=MissingKeyStrategy.WARN,
            provider_name="resettable",
        )
        first = loader.get()
        assert first == "initial"
        assert loader.is_initialized()

        loader.reset()
        assert not loader.is_initialized()

    def test_global_context_provider(self):
        """Global context providers should return True after configuration."""
        configured = {"done": False}

        def configure():
            configured["done"] = True

        loader = LazyLoader(
            loader_func=configure,
            required_keys=["ok"],
            strategy=MissingKeyStrategy.WARN,
            provider_name="global_ctx",
            is_global_context=True,
        )
        result = loader.get()
        assert result is True
        assert configured["done"] is True

    @pytest.mark.asyncio
    async def test_concurrent_aget_initializes_once(self):
        """aget() called concurrently from many tasks must run the loader exactly once.

        This test is the canonical guard for the async double-checked locking
        in LazyLoader.aget().  If the asyncio.Lock is removed from the hot path
        this test will fail because init_count will be > 1.
        """
        init_count = {"n": 0}

        async def counting_loader():
            # Yield control so that all tasks are truly concurrent before any
            # one of them finishes, making the race window as wide as possible.
            await asyncio.sleep(0)
            init_count["n"] += 1
            return object()

        loader = LazyLoader(
            loader_func=counting_loader,
            required_keys=["present"],
            strategy=MissingKeyStrategy.ERROR,
            provider_name="concurrent_test",
        )

        results = await asyncio.gather(*[loader.aget() for _ in range(10)])

        assert init_count["n"] == 1, (
            f"Loader was called {init_count['n']} times; expected exactly 1. "
            "The async lock is likely missing or broken."
        )
        # All callers must receive the same instance.
        first = results[0]
        assert all(r is first for r in results), (
            "Not all concurrent callers received the same instance."
        )

    @pytest.mark.asyncio
    async def test_aget_returns_same_instance(self):
        """Two sequential aget() calls must return the identical object (not just equal)."""
        sentinel = object()

        async def loader():
            return sentinel

        lazy = LazyLoader(
            loader_func=loader,
            required_keys=["ok"],
            strategy=MissingKeyStrategy.ERROR,
            provider_name="identity_test",
        )

        first = await lazy.aget()
        second = await lazy.aget()

        assert first is second, (
            "aget() returned different objects on successive calls; "
            "the loader must only run once and cache its result."
        )
        assert first is sentinel

    @pytest.mark.asyncio
    async def test_exception_during_init_propagates(self):
        """An exception raised inside the loader must propagate to the caller.

        Additionally, after a failed initialisation the provider must NOT be
        marked as initialised — the next call must re-attempt (and fail again),
        not silently return None.
        """

        async def failing_loader():
            raise ValueError("boom")

        loader = LazyLoader(
            loader_func=failing_loader,
            required_keys=["present"],
            strategy=MissingKeyStrategy.ERROR,
            provider_name="failing_provider",
        )

        # First call — must propagate the error wrapped in ConfigurationError.
        with pytest.raises(ConfigurationError):
            await loader.aget()

        # Provider must not be marked as initialised after a failure.
        assert not loader.is_initialized(), (
            "Provider should not be marked as initialized after a failed init."
        )

        # Second call — must also fail, not return None or a stale value.
        with pytest.raises(ConfigurationError):
            await loader.aget()

    @pytest.mark.asyncio
    async def test_dependency_resolution_order(self):
        """ProviderRegistry.aget() must initialise dependencies before dependents.

        Provider A declares a dependency on B.  We verify that B's loader runs
        before A's loader, which mirrors the real-world need to e.g. connect a
        database before a service that wraps it.
        """
        init_order: list[str] = []

        async def load_b():
            init_order.append("B")
            return "b-instance"

        async def load_a():
            init_order.append("A")
            return "a-instance"

        registry = ProviderRegistry()
        registry.register(
            name="B",
            loader_func=load_b,
            required_keys=["ok"],
            strategy=MissingKeyStrategy.ERROR,
        )
        registry.register(
            name="A",
            loader_func=load_a,
            required_keys=["ok"],
            strategy=MissingKeyStrategy.ERROR,
            dependencies=["B"],
        )

        result = await registry.aget("A")

        assert result == "a-instance"
        assert init_order == ["B", "A"], (
            f"Expected B to be initialized before A, got order: {init_order}"
        )
