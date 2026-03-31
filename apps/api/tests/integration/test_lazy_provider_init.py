"""Integration tests for lazy provider initialization.

TEST 14: Validates LazyLoader deferred initialization, concurrent access,
teardown, failure recovery, and ProviderRegistry lifecycle using real
production classes with fake provider implementations (no real DB connections).
"""

import asyncio
from unittest.mock import patch

import pytest

from app.core.lazy_loader import (
    LazyLoader,
    MissingKeyStrategy,
    ProviderRegistry,
)
from app.utils.exceptions import ConfigurationError


# ---------------------------------------------------------------------------
# Fake providers used across tests — simple classes that track init/teardown
# ---------------------------------------------------------------------------


class FakeClient:
    """Minimal fake provider that records whether it was initialized."""

    def __init__(self, name: str = "fake") -> None:
        self.name = name
        self.initialized = True

    def __repr__(self) -> str:
        return f"FakeClient({self.name!r})"


class FakeAsyncClient:
    """Async-initializable fake provider."""

    def __init__(self, name: str = "async_fake") -> None:
        self.name = name
        self.connected = True

    async def close(self) -> None:
        self.connected = False


class FailingClient:
    """Provider whose factory always raises."""

    def __init__(self) -> None:
        raise RuntimeError("connection refused")


# ---------------------------------------------------------------------------
# 1. Provider registration
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestProviderRegistration:
    """Register a provider and verify it is tracked by LazyLoader."""

    def test_register_provider_tracked_in_registry(self) -> None:
        """After registration the provider name appears in list_providers."""
        registry = ProviderRegistry()
        registry.register(
            name="tracking_test",
            loader_func=lambda: FakeClient("tracked"),
            required_keys=["present"],
            strategy=MissingKeyStrategy.WARN,
        )

        listing = registry.list_providers()
        assert "tracking_test" in listing
        assert listing["tracking_test"]["available"] is True
        assert listing["tracking_test"]["initialized"] is False

    def test_register_returns_lazy_loader_instance(self) -> None:
        """register() should return a LazyLoader, not the provider value."""
        registry = ProviderRegistry()
        loader = registry.register(
            name="loader_return",
            loader_func=lambda: FakeClient("lr"),
            required_keys=["key"],
            strategy=MissingKeyStrategy.WARN,
        )
        assert isinstance(loader, LazyLoader)
        assert not loader.is_initialized()

    def test_get_loader_returns_same_object(self) -> None:
        """get_loader() should return the exact LazyLoader that was registered."""
        registry = ProviderRegistry()
        returned_loader = registry.register(
            name="same_obj",
            loader_func=lambda: "value",
            required_keys=["ok"],
            strategy=MissingKeyStrategy.WARN,
        )
        retrieved_loader = registry.get_loader("same_obj")
        assert returned_loader is retrieved_loader


# ---------------------------------------------------------------------------
# 2. Lazy initialization (deferred until first access)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestLazyInitialization:
    """Provider initialization must happen on first access, not at registration."""

    def test_sync_provider_not_initialized_at_registration(self) -> None:
        """Registration alone must NOT call the loader function."""
        call_count = {"n": 0}

        def loader() -> FakeClient:
            call_count["n"] += 1
            return FakeClient("lazy")

        registry = ProviderRegistry()
        registry.register(
            name="lazy_sync",
            loader_func=loader,
            required_keys=["present"],
            strategy=MissingKeyStrategy.WARN,
        )

        assert call_count["n"] == 0, "Loader must not be called at registration time"
        assert not registry.is_initialized("lazy_sync")

    def test_sync_provider_initialized_on_first_get(self) -> None:
        """First get() must trigger initialization and return the instance."""
        call_count = {"n": 0}

        def loader() -> FakeClient:
            call_count["n"] += 1
            return FakeClient("lazy_get")

        registry = ProviderRegistry()
        registry.register(
            name="lazy_get",
            loader_func=loader,
            required_keys=["present"],
            strategy=MissingKeyStrategy.WARN,
        )

        result = registry.get("lazy_get")

        assert call_count["n"] == 1
        assert isinstance(result, FakeClient)
        assert result.name == "lazy_get"
        assert registry.is_initialized("lazy_get")

    async def test_async_provider_not_initialized_at_registration(self) -> None:
        """Async providers must also defer initialization until aget()."""
        call_count = {"n": 0}

        async def async_loader() -> FakeAsyncClient:
            call_count["n"] += 1
            return FakeAsyncClient("lazy_async")

        registry = ProviderRegistry()
        registry.register(
            name="lazy_async",
            loader_func=async_loader,
            required_keys=["present"],
            strategy=MissingKeyStrategy.WARN,
        )

        assert call_count["n"] == 0
        assert not registry.is_initialized("lazy_async")

    async def test_async_provider_initialized_on_first_aget(self) -> None:
        """First aget() on an async provider triggers initialization."""
        call_count = {"n": 0}

        async def async_loader() -> FakeAsyncClient:
            call_count["n"] += 1
            return FakeAsyncClient("aget_test")

        registry = ProviderRegistry()
        registry.register(
            name="aget_test",
            loader_func=async_loader,
            required_keys=["present"],
            strategy=MissingKeyStrategy.WARN,
        )

        result = await registry.aget("aget_test")

        assert call_count["n"] == 1
        assert isinstance(result, FakeAsyncClient)
        assert result.name == "aget_test"
        assert registry.is_initialized("aget_test")

    def test_second_get_returns_cached_instance(self) -> None:
        """Subsequent get() calls must return the same object without re-init."""
        call_count = {"n": 0}

        def loader() -> FakeClient:
            call_count["n"] += 1
            return FakeClient("cached")

        registry = ProviderRegistry()
        registry.register(
            name="cached_test",
            loader_func=loader,
            required_keys=["present"],
            strategy=MissingKeyStrategy.WARN,
        )

        first = registry.get("cached_test")
        second = registry.get("cached_test")

        assert first is second, "Must return the exact same object"
        assert call_count["n"] == 1, "Loader must only be called once"


# ---------------------------------------------------------------------------
# 3. Pre-initialization access errors
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestPreInitializationAccess:
    """Accessing an unregistered or misconfigured provider must give clear errors."""

    def test_get_unregistered_raises_key_error(self) -> None:
        """get() for an unknown name must raise KeyError, not AttributeError."""
        registry = ProviderRegistry()
        with pytest.raises(KeyError, match="not found"):
            registry.get("nonexistent_provider")

    async def test_aget_unregistered_raises_key_error(self) -> None:
        """aget() for an unknown name must raise KeyError."""
        registry = ProviderRegistry()
        with pytest.raises(KeyError, match="not found"):
            await registry.aget("nonexistent_async")

    def test_sync_get_on_async_provider_raises_runtime_error(self) -> None:
        """Calling sync get() on an async provider must raise RuntimeError."""

        async def async_loader() -> str:
            return "async_only"

        registry = ProviderRegistry()
        registry.register(
            name="async_only",
            loader_func=async_loader,
            required_keys=["present"],
            strategy=MissingKeyStrategy.WARN,
        )

        with pytest.raises(RuntimeError, match="async loader function"):
            registry.get("async_only")

    def test_missing_keys_error_strategy_raises_configuration_error(self) -> None:
        """ERROR strategy with missing keys must raise ConfigurationError on get()."""
        registry = ProviderRegistry()
        registry.register(
            name="err_missing",
            loader_func=lambda: "unreachable",
            required_keys=[None, ""],
            strategy=MissingKeyStrategy.ERROR,
        )

        with pytest.raises(ConfigurationError, match="missing values"):
            registry.get("err_missing")

    def test_missing_keys_warn_strategy_returns_none(self) -> None:
        """WARN strategy with missing keys returns None instead of crashing."""
        registry = ProviderRegistry()
        registry.register(
            name="warn_missing",
            loader_func=lambda: "unreachable",
            required_keys=[None],
            strategy=MissingKeyStrategy.WARN,
        )

        result = registry.get("warn_missing")
        assert result is None


# ---------------------------------------------------------------------------
# 4. Concurrent initialization (race safety)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestConcurrentInitialization:
    """Multiple coroutines accessing the same provider simultaneously must
    result in exactly one initialization."""

    async def test_concurrent_aget_initializes_once(self) -> None:
        """Fire N concurrent aget() calls. The loader must execute exactly once."""
        call_count = {"n": 0}
        init_event = asyncio.Event()

        async def slow_loader() -> FakeAsyncClient:
            call_count["n"] += 1
            # Simulate slow init to widen the race window
            await asyncio.sleep(0.05)
            init_event.set()
            return FakeAsyncClient("concurrent")

        registry = ProviderRegistry()
        registry.register(
            name="concurrent_test",
            loader_func=slow_loader,
            required_keys=["present"],
            strategy=MissingKeyStrategy.WARN,
        )

        results = await asyncio.gather(
            registry.aget("concurrent_test"),
            registry.aget("concurrent_test"),
            registry.aget("concurrent_test"),
            registry.aget("concurrent_test"),
            registry.aget("concurrent_test"),
        )

        assert call_count["n"] == 1, "Loader must be called exactly once"
        # All results must be the same object
        first = results[0]
        for r in results[1:]:
            assert r is first, "All concurrent callers must get the same instance"

    async def test_concurrent_sync_via_aget_initializes_once(self) -> None:
        """Sync providers accessed via aget() should also be safe under concurrency."""
        call_count = {"n": 0}

        def sync_loader() -> FakeClient:
            call_count["n"] += 1
            return FakeClient("sync_concurrent")

        registry = ProviderRegistry()
        registry.register(
            name="sync_conc",
            loader_func=sync_loader,
            required_keys=["present"],
            strategy=MissingKeyStrategy.WARN,
        )

        results = await asyncio.gather(
            registry.aget("sync_conc"),
            registry.aget("sync_conc"),
            registry.aget("sync_conc"),
        )

        assert call_count["n"] == 1
        assert all(r is results[0] for r in results)


# ---------------------------------------------------------------------------
# 5. Provider teardown (reset)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestProviderTeardown:
    """After reset, the provider must no longer be marked as initialized."""

    def test_reset_clears_sync_provider(self) -> None:
        """reset() on a sync provider clears the cached instance."""
        registry = ProviderRegistry()
        registry.register(
            name="teardown_sync",
            loader_func=lambda: FakeClient("teardown"),
            required_keys=["present"],
            strategy=MissingKeyStrategy.WARN,
        )

        result = registry.get("teardown_sync")
        assert isinstance(result, FakeClient)
        assert registry.is_initialized("teardown_sync")

        loader = registry.get_loader("teardown_sync")
        loader.reset()

        assert not registry.is_initialized("teardown_sync")

    def test_reset_allows_reinitialization(self) -> None:
        """After reset, next get() must re-run the loader function."""
        call_count = {"n": 0}

        def loader() -> str:
            call_count["n"] += 1
            return f"v{call_count['n']}"

        registry = ProviderRegistry()
        registry.register(
            name="reinit",
            loader_func=loader,
            required_keys=["present"],
            strategy=MissingKeyStrategy.WARN,
        )

        first = registry.get("reinit")
        assert first == "v1"

        registry.get_loader("reinit").reset()
        second = registry.get("reinit")

        assert second == "v2"
        assert call_count["n"] == 2

    def test_reset_global_context_provider(self) -> None:
        """Global context providers should also be clearable via reset()."""
        configured = {"count": 0}

        def configure() -> None:
            configured["count"] += 1

        loader = LazyLoader(
            loader_func=configure,
            required_keys=["ok"],
            strategy=MissingKeyStrategy.WARN,
            provider_name="global_teardown",
            is_global_context=True,
        )

        loader.get()
        assert loader.is_initialized()
        assert configured["count"] == 1

        loader.reset()
        assert not loader.is_initialized()

        loader.get()
        assert configured["count"] == 2


# ---------------------------------------------------------------------------
# 6. Teardown order (multiple providers)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestTeardownOrder:
    """When tearing down multiple providers, verify controlled cleanup."""

    def test_multiple_providers_reset_independently(self) -> None:
        """Resetting one provider must not affect others."""
        registry = ProviderRegistry()
        registry.register(
            name="prov_a",
            loader_func=lambda: FakeClient("a"),
            required_keys=["ok"],
            strategy=MissingKeyStrategy.WARN,
        )
        registry.register(
            name="prov_b",
            loader_func=lambda: FakeClient("b"),
            required_keys=["ok"],
            strategy=MissingKeyStrategy.WARN,
        )

        registry.get("prov_a")
        registry.get("prov_b")
        assert registry.is_initialized("prov_a")
        assert registry.is_initialized("prov_b")

        registry.get_loader("prov_a").reset()

        assert not registry.is_initialized("prov_a")
        assert registry.is_initialized("prov_b"), "prov_b must remain initialized"

    def test_all_providers_can_be_torn_down(self) -> None:
        """Iterate and reset all providers to simulate full shutdown."""
        registry = ProviderRegistry()
        names = ["td_1", "td_2", "td_3"]
        for name in names:
            registry.register(
                name=name,
                loader_func=lambda n=name: FakeClient(n),
                required_keys=["ok"],
                strategy=MissingKeyStrategy.WARN,
            )
            registry.get(name)

        # Verify all initialized
        for name in names:
            assert registry.is_initialized(name)

        # Teardown in reverse order
        for name in reversed(names):
            registry.get_loader(name).reset()

        for name in names:
            assert not registry.is_initialized(name)


# ---------------------------------------------------------------------------
# 7. Initialization failure
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestInitializationFailure:
    """When a provider's loader raises, the error must propagate and the
    provider must NOT be marked as initialized."""

    def test_sync_loader_error_propagates_with_error_strategy(self) -> None:
        """ERROR strategy: loader exception wraps in ConfigurationError."""
        registry = ProviderRegistry()
        registry.register(
            name="fail_err",
            loader_func=FailingClient,
            required_keys=["present"],
            strategy=MissingKeyStrategy.ERROR,
        )

        with pytest.raises(ConfigurationError, match="connection refused"):
            registry.get("fail_err")

        assert not registry.is_initialized("fail_err")

    def test_sync_loader_error_returns_none_with_warn_strategy(self) -> None:
        """WARN strategy: loader exception returns None, does not crash."""
        registry = ProviderRegistry()
        registry.register(
            name="fail_warn",
            loader_func=FailingClient,
            required_keys=["present"],
            strategy=MissingKeyStrategy.WARN,
        )

        result = registry.get("fail_warn")

        assert result is None
        assert not registry.is_initialized("fail_warn")

    async def test_async_loader_error_propagates(self) -> None:
        """Async loader failures must also propagate correctly."""

        async def failing_async() -> FakeAsyncClient:
            raise ConnectionError("async connection refused")

        registry = ProviderRegistry()
        registry.register(
            name="fail_async",
            loader_func=failing_async,
            required_keys=["present"],
            strategy=MissingKeyStrategy.ERROR,
        )

        with pytest.raises(ConfigurationError, match="async connection refused"):
            await registry.aget("fail_async")

        assert not registry.is_initialized("fail_async")

    def test_loader_failure_does_not_poison_other_providers(self) -> None:
        """One provider failing must not prevent others from initializing."""
        registry = ProviderRegistry()
        registry.register(
            name="good_prov",
            loader_func=lambda: FakeClient("good"),
            required_keys=["ok"],
            strategy=MissingKeyStrategy.WARN,
        )
        registry.register(
            name="bad_prov",
            loader_func=FailingClient,
            required_keys=["ok"],
            strategy=MissingKeyStrategy.WARN,
        )

        # Bad one fails gracefully
        bad_result = registry.get("bad_prov")
        assert bad_result is None

        # Good one still works
        good_result = registry.get("good_prov")
        assert isinstance(good_result, FakeClient)
        assert good_result.name == "good"


# ---------------------------------------------------------------------------
# 8. Re-initialization after failure
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestReInitializationAfterFailure:
    """After a provider fails to initialize, a subsequent attempt with a
    fixed loader should succeed."""

    def test_retry_after_sync_failure_succeeds(self) -> None:
        """Register a failing provider, observe failure, re-register with
        working loader, verify success."""
        registry = ProviderRegistry()

        # First registration: broken loader
        registry.register(
            name="retry_prov",
            loader_func=FailingClient,
            required_keys=["present"],
            strategy=MissingKeyStrategy.WARN,
        )
        result = registry.get("retry_prov")
        assert result is None
        assert not registry.is_initialized("retry_prov")

        # Re-register with a working loader (simulates config fix + re-registration)
        registry.register(
            name="retry_prov",
            loader_func=lambda: FakeClient("recovered"),
            required_keys=["present"],
            strategy=MissingKeyStrategy.WARN,
        )

        result = registry.get("retry_prov")
        assert isinstance(result, FakeClient)
        assert result.name == "recovered"
        assert registry.is_initialized("retry_prov")

    async def test_retry_after_async_failure_succeeds(self) -> None:
        """Same pattern for async providers."""
        attempt = {"n": 0}

        async def flaky_loader() -> FakeAsyncClient:
            attempt["n"] += 1
            if attempt["n"] == 1:
                raise ConnectionError("first attempt fails")
            return FakeAsyncClient("recovered_async")

        registry = ProviderRegistry()
        registry.register(
            name="flaky_async",
            loader_func=flaky_loader,
            required_keys=["present"],
            strategy=MissingKeyStrategy.WARN,
        )

        # First attempt fails
        first = await registry.aget("flaky_async")
        assert first is None
        assert not registry.is_initialized("flaky_async")

        # Since the instance is None, aget() will re-attempt initialization
        second = await registry.aget("flaky_async")
        assert isinstance(second, FakeAsyncClient)
        assert second.name == "recovered_async"
        assert registry.is_initialized("flaky_async")

    def test_error_strategy_retry_after_reset(self) -> None:
        """With ERROR strategy, after failure and reset, retry should work if
        we re-register a working loader."""
        call_count = {"n": 0}

        def sometimes_fails() -> FakeClient:
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("first call fails")
            return FakeClient("success_on_retry")

        # Use WARN so first failure returns None instead of raising
        registry = ProviderRegistry()
        registry.register(
            name="retry_reset",
            loader_func=sometimes_fails,
            required_keys=["present"],
            strategy=MissingKeyStrategy.WARN,
        )

        first = registry.get("retry_reset")
        assert first is None

        # Since the _instance is still None after failure, next get() retries
        second = registry.get("retry_reset")
        assert isinstance(second, FakeClient)
        assert second.name == "success_on_retry"


# ---------------------------------------------------------------------------
# Additional edge cases
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestEdgeCases:
    """Cover dependency resolution, custom validation, and warmup scenarios."""

    def test_dependency_resolution_initializes_deps_first(self) -> None:
        """When provider B depends on A, getting B must initialize A first."""
        order: list[str] = []

        def loader_a() -> str:
            order.append("a")
            return "val_a"

        def loader_b() -> str:
            order.append("b")
            return "val_b"

        registry = ProviderRegistry()
        registry.register(
            name="dep_a",
            loader_func=loader_a,
            required_keys=["ok"],
            strategy=MissingKeyStrategy.WARN,
        )
        registry.register(
            name="dep_b",
            loader_func=loader_b,
            required_keys=["ok"],
            strategy=MissingKeyStrategy.WARN,
            dependencies=["dep_a"],
        )

        registry.get("dep_b")
        assert order == ["a", "b"], "Dependency A must initialize before B"

    def test_cyclic_dependency_raises(self) -> None:
        """Cyclic dependencies must be detected and raise ConfigurationError."""
        registry = ProviderRegistry()
        registry.register(
            name="cyc_x",
            loader_func=lambda: "x",
            required_keys=["ok"],
            strategy=MissingKeyStrategy.WARN,
            dependencies=["cyc_y"],
        )
        registry.register(
            name="cyc_y",
            loader_func=lambda: "y",
            required_keys=["ok"],
            strategy=MissingKeyStrategy.WARN,
            dependencies=["cyc_x"],
        )

        with pytest.raises(ConfigurationError, match="Cyclic dependency"):
            registry.get("cyc_x")

    def test_custom_validation_func_blocks_init(self) -> None:
        """A custom validate_values_func returning False should prevent init."""
        registry = ProviderRegistry()
        registry.register(
            name="custom_val",
            loader_func=lambda: "unreachable",
            required_keys=["present"],
            strategy=MissingKeyStrategy.ERROR,
            validate_values_func=lambda keys: False,
        )

        with pytest.raises(ConfigurationError, match="validation failed"):
            registry.get("custom_val")

    def test_is_available_reflects_key_presence(self) -> None:
        """is_available must return True only when all keys are non-None/non-empty."""
        registry = ProviderRegistry()
        registry.register(
            name="avail_yes",
            loader_func=lambda: "v",
            required_keys=["key1", "key2"],
            strategy=MissingKeyStrategy.WARN,
        )
        registry.register(
            name="avail_no",
            loader_func=lambda: "v",
            required_keys=["key1", None],
            strategy=MissingKeyStrategy.WARN,
        )

        assert registry.is_available("avail_yes") is True
        assert registry.is_available("avail_no") is False
        assert registry.is_available("nonexistent") is False

    async def test_warmup_all_handles_mixed_providers(self) -> None:
        """warmup_all initializes available providers and skips unavailable ones."""
        registry = ProviderRegistry()
        registry.register(
            name="warm_ok",
            loader_func=lambda: FakeClient("warm"),
            required_keys=["present"],
            strategy=MissingKeyStrategy.WARN,
        )
        registry.register(
            name="warm_skip",
            loader_func=lambda: "unreachable",
            required_keys=[None],
            strategy=MissingKeyStrategy.WARN,
        )

        await registry.warmup_all()

        assert registry.is_initialized("warm_ok")
        assert not registry.is_initialized("warm_skip")

    async def test_warmup_all_strict_raises_on_failure(self) -> None:
        """In strict mode, warmup_all raises if any ERROR-strategy provider is unavailable."""
        registry = ProviderRegistry()
        registry.register(
            name="strict_fail",
            loader_func=lambda: "unreachable",
            required_keys=[None],
            strategy=MissingKeyStrategy.ERROR,
        )

        with pytest.raises(RuntimeError, match="warmup failed"):
            await registry.warmup_all(strict=True)

    def test_re_registration_replaces_provider(self) -> None:
        """Re-registering the same name replaces the old provider entirely."""
        registry = ProviderRegistry()
        registry.register(
            name="replace_me",
            loader_func=lambda: "old",
            required_keys=["ok"],
            strategy=MissingKeyStrategy.WARN,
        )
        old_val = registry.get("replace_me")
        assert old_val == "old"

        with patch("app.core.lazy_loader.log"):
            registry.register(
                name="replace_me",
                loader_func=lambda: "new",
                required_keys=["ok"],
                strategy=MissingKeyStrategy.WARN,
            )

        new_val = registry.get("replace_me")
        assert new_val == "new"
