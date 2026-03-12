"""Integration tests for the lazy loader / provider registration system.

Tests ProviderRegistry and LazyLoader behavior including registration,
initialization, missing key handling, and async providers.
"""

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

        async def async_loader():  # NOSONAR — intentionally async to test registry awaits the loader
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


@pytest.mark.integration
class TestProviderRegistryExtended:
    """Additional coverage for ProviderRegistry methods not covered above."""

    async def test_aget_missing_key_raises(self):
        """aget() for an unregistered provider name should raise KeyError."""
        registry = ProviderRegistry()
        with pytest.raises(KeyError, match="not found"):
            await registry.aget("does_not_exist")

    def test_warn_once_strategy_logs_once(self):
        """WARN_ONCE strategy should emit the warning exactly once at registration.

        The warning is emitted in _check_availability_and_warn() during
        LazyLoader.__init__. Registering twice (re-registering) should still
        only ever call _log_warning once per LazyLoader instance because the
        second instance is a brand-new object.  What we verify here is that a
        single LazyLoader with WARN_ONCE only logs one warning at construction
        time rather than logging on every get() call.

        The app uses loguru (not stdlib logging), so we mock `logger.warning`
        at the module level rather than using pytest's caplog fixture.
        """
        from unittest.mock import patch

        registry = ProviderRegistry()
        with patch("app.core.lazy_loader.log") as mock_logger:
            registry.register(
                name="warn_once_provider",
                loader_func=lambda: "value",
                required_keys=[None],  # None triggers the missing-key warning
                strategy=MissingKeyStrategy.WARN_ONCE,
            )
            # Calling get() twice should NOT produce additional warnings.
            registry.get("warn_once_provider")
            registry.get("warn_once_provider")

        # The registration-time warning fires exactly once; get() is silent.
        warn_calls = [
            call
            for call in mock_logger.warning.call_args_list
            if "warn_once_provider" in str(call)
        ]
        assert len(warn_calls) == 1

    def test_cyclic_dependency_detected(self):
        """_check_cyclic_dependency should raise ConfigurationError for A -> B -> A."""
        from app.utils.exceptions import ConfigurationError

        registry = ProviderRegistry()
        # Register A depending on B, and B depending on A.
        registry.register(
            name="dep_a",
            loader_func=lambda: "a",
            required_keys=["ok"],
            strategy=MissingKeyStrategy.WARN,
            dependencies=["dep_b"],
        )
        registry.register(
            name="dep_b",
            loader_func=lambda: "b",
            required_keys=["ok"],
            strategy=MissingKeyStrategy.WARN,
            dependencies=["dep_a"],
        )
        with pytest.raises(ConfigurationError, match="Cyclic dependency detected"):
            registry._check_cyclic_dependency("dep_a")

    async def test_initialize_auto_providers_initializes_registered(self):
        """initialize_auto_providers should call aget() for auto-init providers."""
        registry = ProviderRegistry()
        registry.register(
            name="auto_p",
            loader_func=lambda: "auto-result",
            required_keys=["present"],
            strategy=MissingKeyStrategy.WARN,
            auto_initialize=True,
        )
        # Reset so initialize_auto_providers has something to do.
        registry._providers["auto_p"].reset()
        assert not registry.is_initialized("auto_p")

        await registry.initialize_auto_providers()

        assert registry.is_initialized("auto_p")
        assert registry.get("auto_p") == "auto-result"

    async def test_warmup_all_initializes_available_providers(self):
        """warmup_all should initialize every available provider."""
        registry = ProviderRegistry()
        registry.register(
            name="warm_p",
            loader_func=lambda: "warm-result",
            required_keys=["present"],
            strategy=MissingKeyStrategy.WARN,
        )
        # Provider should not be initialized yet.
        assert not registry.is_initialized("warm_p")

        await registry.warmup_all()

        assert registry.is_initialized("warm_p")

    async def test_warmup_all_skips_unavailable_providers(self):
        """warmup_all should skip (not raise for) unavailable providers."""
        registry = ProviderRegistry()
        registry.register(
            name="unavail_p",
            loader_func=lambda: "should-not-run",
            required_keys=[None],  # missing -> unavailable
            strategy=MissingKeyStrategy.WARN,
        )
        # Should complete without raising even though the provider is unavailable.
        await registry.warmup_all()
        assert not registry.is_initialized("unavail_p")
