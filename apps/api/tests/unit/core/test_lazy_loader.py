"""Mutation-verified tests for app/core/lazy_loader.py.

UNIT: app/core/lazy_loader.py :: LazyLoader, ProviderRegistry, lazy_provider, MissingKeyStrategy

EXPECTED: A lazy, thread-safe provider registry. Providers are *registered* (not
    connected) eagerly and *initialized* once on first get()/aget(). Missing required
    keys are handled per MissingKeyStrategy (ERROR raises, WARN/SILENT return None).
    Instance providers cache and return the built instance; global-context providers
    run a side effect once and return True. A registry resolves dependencies first,
    detects cycles, and offers strict/non-strict bulk warmup.

MECHANISM:
    - LazyLoader caches in self._instance (instance) / self._is_configured (global).
    - get() refuses async loaders; aget() handles both. Both use a double-checked
      lock and a cheap fast-path that returns the cached value.
    - _initialize_sync/_initialize_async check keys -> custom validator -> call the
      loader, wrapping failures in ConfigurationError under ERROR strategy.
    - ProviderRegistry.get/aget eagerly resolve each dependency before the target,
      skip already-initialized auto-init deps, and raise on a dependency cycle.
    - initialize_auto_providers / warmup_all init many providers under a semaphore;
      strict mode re-raises aggregated failures, non-strict logs and continues.

MUST-CATCH (each maps to >=1 test + >=1 killed mutant):
    - is_available is False for None / blank-string / failed-custom-validator keys
      (each branch of _is_value_missing and the validator gate).
    - get()/aget() return the REAL built instance on the cold path, the SAME cached
      instance on the warm fast-path, and the loader runs exactly once.
    - global-context get/aget return literal True and set is_initialized, and the
      cached warm path also returns True (not None).
    - get() raises RuntimeError for an async loader; aget() raises if the async lock
      is missing.
    - missing-key and validation-failure paths: ERROR raises ConfigurationError with
      the right diagnostic text; WARN/SILENT return None.
    - loader exceptions become ConfigurationError under ERROR, None under WARN.
    - reset() clears BOTH _instance and _is_configured.
    - custom warning_message is used verbatim instead of the generated default.
    - registry resolves dependencies before the target, detects cycles, re-register
      overwrites, unknown name raises KeyError.
    - dependency skip-logic: an already-initialized auto-init dep is not re-fetched.
    - initialize_auto_providers / warmup_all: skip unavailable, strict raises on
      unavailable-ERROR and on init failure, non-strict swallows failures.
    - lazy_provider decorator threads name/keys/global/async through and does NOT
      auto-initialize by default.

EQUIVALENT MUTANTS (allowed survivors — measured kill 169/214 = 78.97% by mutate.py;
the 45 survivors are all provably equivalent, so the effective kill against behavioural
mutants is 169/169 = 100%):
    - Double-checked-locking INNER guards (get/aget): the under-lock re-checks
      `is_global_context and _is_configured` / `not is_global_context and _instance is
      not None` and their `return True` / `return self._instance` are only reached on
      the COLD path (outer fast-path already returns the warm value). On the cold path
      the cached value is absent, so flipping the `not`, blanking the return, or
      `True->False` cannot change a single-threaded result. Empirically verified:
      flipping the inner `return True` to `return None` breaks zero tests. These guards
      only matter to a second concurrent thread, which a unit test cannot exercise.
    - `_initialize_async` is entered only when `is_async` is True (sync loaders route
      to `_initialize_sync`). Inside, `if self.is_async:` is always True and an
      `async def` always returns a coroutine, so the sync-loader / non-coroutine guard
      branches (and their messages) are dead — unreachable from any public call.
    - reset()'s inner `_async_reset` body (the `self._async_lock is None` check and its
      `_is_configured = False`) is unreachable under pytest: the test event loop is
      always running, so reset() takes the `loop.is_running()` branch and resets
      synchronously. Mutations confined to that inner coroutine cannot change behaviour.
    - `asyncio.Semaphore(max(1, concurrency))` bound and the default concurrency value
      (5): the semaphore only throttles parallelism; with finite providers the final
      state and return value are identical for any positive bound, so 1->2 / 5->6 are
      behaviour-preserving.
    - `_is_value_missing`'s final `return False` -> `return None`: both are falsy and
      callers only branch on truthiness, so the result is identical.
    - Dependency skip-optimization `if dep in auto_init and is_initialized(): continue`
      (And->Or, In->NotIn): redundant with the very next `if not is_initialized():
      self.get(dep)` guard, which produces the same outcome whether or not the
      `continue` fires.
    - Empty-warmup `if strict and errors:` (And->Or): in the no-warmup branch `errors`
      is only ever populated when `strict` is True, so And and Or coincide.
    - Inner ConfigurationError text appended to `errors` (auto-init/warmup unavailable):
      that message never surfaces — the final RuntimeError joins only provider *names*.
    - `skipped_unavailable` counter, per-strategy log *level* (log.error vs log.warning),
      and a stray class-body docstring affect only log text, never control flow.
"""

from unittest.mock import patch
import uuid

import pytest

from app.core.lazy_loader import (
    LazyLoader,
    MissingKeyStrategy,
    ProviderRegistry,
    lazy_provider,
    providers,
)
from app.utils.exceptions import ConfigurationError


def _uid(prefix: str = "test") -> str:
    """Return a unique provider name to avoid cross-test pollution.

    The module-level `providers` registry is a never-reset global singleton, so any
    test touching it must use a unique name or it will collide with siblings.
    """
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# LazyLoader — construction & availability
# ---------------------------------------------------------------------------


class TestLazyLoaderInit:
    def test_default_provider_name_is_func_name(self):
        def my_func():
            return 42

        loader = LazyLoader(my_func, strategy=MissingKeyStrategy.SILENT)
        assert loader.provider_name == "my_func"

    def test_custom_provider_name_overrides_func_name(self):
        def my_func():
            return 1

        loader = LazyLoader(my_func, provider_name="custom", strategy=MissingKeyStrategy.SILENT)
        assert loader.provider_name == "custom"

    def test_is_available_true_when_all_keys_present(self):
        loader = LazyLoader(
            lambda: 1,
            required_keys=["val1", "val2"],
            strategy=MissingKeyStrategy.SILENT,
        )
        assert loader.is_available() is True

    def test_is_available_false_when_key_is_none(self):
        loader = LazyLoader(
            lambda: 1,
            required_keys=["val1", None],
            strategy=MissingKeyStrategy.SILENT,
        )
        assert loader.is_available() is False

    def test_is_available_false_when_key_is_blank_string(self):
        loader = LazyLoader(
            lambda: 1,
            required_keys=["val1", "  "],
            strategy=MissingKeyStrategy.SILENT,
        )
        assert loader.is_available() is False

    def test_is_available_true_for_present_value_with_no_validator(self):
        # Pins _is_value_missing's final `return False`: a non-None, non-blank value
        # must be treated as present.
        loader = LazyLoader(
            lambda: 1,
            required_keys=["present"],
            strategy=MissingKeyStrategy.SILENT,
        )
        assert loader.is_available() is True

    def test_is_available_true_when_custom_validator_passes(self):
        loader = LazyLoader(
            lambda: 1,
            required_keys=["a"],
            validate_values_func=lambda keys: True,
            strategy=MissingKeyStrategy.SILENT,
        )
        assert loader.is_available() is True

    def test_is_available_false_when_custom_validator_fails(self):
        loader = LazyLoader(
            lambda: 1,
            required_keys=["a"],
            validate_values_func=lambda keys: False,
            strategy=MissingKeyStrategy.SILENT,
        )
        assert loader.is_available() is False

    def test_custom_validator_receives_the_required_keys(self):
        seen: list = []
        loader = LazyLoader(
            lambda: 1,
            required_keys=["x", "y"],
            validate_values_func=lambda keys: seen.append(list(keys)) or True,
            strategy=MissingKeyStrategy.SILENT,
        )
        loader.is_available()
        assert seen[-1] == ["x", "y"]

    def test_is_initialized_false_before_first_get(self):
        loader = LazyLoader(lambda: 1, strategy=MissingKeyStrategy.SILENT)
        assert loader.is_initialized() is False

    def test_is_initialized_false_for_unconfigured_global(self):
        loader = LazyLoader(
            lambda: None,
            is_global_context=True,
            strategy=MissingKeyStrategy.SILENT,
        )
        assert loader.is_initialized() is False

    def test_is_async_detected_from_loader(self):
        async def aloader():
            return 1

        assert LazyLoader(aloader, strategy=MissingKeyStrategy.SILENT).is_async is True
        assert LazyLoader(lambda: 1, strategy=MissingKeyStrategy.SILENT).is_async is False


# ---------------------------------------------------------------------------
# LazyLoader — registration-time warnings
# ---------------------------------------------------------------------------


class TestCheckAvailabilityAndWarn:
    def test_warn_strategy_logs_missing_keys_at_registration(self):
        with patch.object(LazyLoader, "_log_warning") as mock_warn:
            LazyLoader(
                lambda: 1,
                required_keys=[None],
                strategy=MissingKeyStrategy.WARN,
                provider_name="prov",
            )
            assert mock_warn.called

    def test_custom_warning_message_used_verbatim(self):
        # Kills `self.warning_message or <generated>` (Or->And): with And the custom
        # message would be discarded in favour of the generated default.
        with patch.object(LazyLoader, "_log_warning") as mock_warn:
            LazyLoader(
                lambda: 1,
                required_keys=[None],
                strategy=MissingKeyStrategy.WARN,
                warning_message="my custom warning",
                provider_name="prov",
            )
        logged = " ".join(str(c.args[0]) for c in mock_warn.call_args_list)
        assert "my custom warning" in logged
        assert "missing required values" not in logged

    def test_generated_warning_names_provider_and_missing_indices(self):
        # Two missing keys: pins the full generated diagnostic — the "Registration
        # warning:" prefix, the provider name, both indices joined by ", ", and the
        # rendered missing-values payload.
        with patch.object(LazyLoader, "_log_warning") as mock_warn:
            LazyLoader(
                lambda: 1,
                required_keys=[None, None],
                strategy=MissingKeyStrategy.WARN,
                provider_name="named_prov",
            )
        logged = " ".join(str(c.args[0]) for c in mock_warn.call_args_list)
        assert "Registration warning:" in logged
        assert (
            "Provider 'named_prov' missing required values at "
            "index 0, index 1: [None, None]" in logged
        )

    def test_warn_once_records_missing_indices(self):
        loader = LazyLoader(
            lambda: 1,
            required_keys=[None, "valid", None],
            strategy=MissingKeyStrategy.WARN_ONCE,
            provider_name="prov",
        )
        assert loader._warned_indices == {0, 2}

    def test_warn_does_not_record_indices(self):
        # WARN (not WARN_ONCE) must leave _warned_indices empty; pins the
        # `strategy == WARN_ONCE` guard before .update().
        loader = LazyLoader(
            lambda: 1,
            required_keys=[None],
            strategy=MissingKeyStrategy.WARN,
            provider_name="prov",
        )
        assert loader._warned_indices == set()

    def test_silent_strategy_logs_nothing(self):
        with patch.object(LazyLoader, "_log_warning") as mock_warn:
            LazyLoader(
                lambda: 1,
                required_keys=[None],
                strategy=MissingKeyStrategy.SILENT,
            )
            mock_warn.assert_not_called()

    def test_warns_when_custom_validator_fails_with_all_keys_present(self):
        with patch.object(LazyLoader, "_log_warning") as mock_warn:
            LazyLoader(
                lambda: 1,
                required_keys=["a"],
                validate_values_func=lambda keys: False,
                strategy=MissingKeyStrategy.WARN,
                provider_name="prov",
            )
        logged = " ".join(str(c.args[0]) for c in mock_warn.call_args_list)
        # Pin the full validation-failure message incl. the provider name.
        assert "Value validation failed for provider 'prov'" in logged


# ---------------------------------------------------------------------------
# LazyLoader — sync get()
# ---------------------------------------------------------------------------


class TestLazyLoaderSyncGet:
    def test_get_returns_built_instance_and_marks_initialized(self):
        loader = LazyLoader(lambda: 42, strategy=MissingKeyStrategy.SILENT)
        assert loader.get() == 42
        assert loader.is_initialized() is True

    def test_get_caches_and_returns_same_instance(self):
        sentinel = object()
        call_count = 0

        def counting_loader():
            nonlocal call_count
            call_count += 1
            return sentinel

        loader = LazyLoader(counting_loader, strategy=MissingKeyStrategy.SILENT)
        first = loader.get()
        second = loader.get()
        assert first is sentinel
        # Warm fast-path must return the SAME cached instance, not rebuild/return None.
        assert second is sentinel
        assert call_count == 1

    def test_get_global_context_returns_true_and_caches_true(self):
        runs = []
        loader = LazyLoader(
            lambda: runs.append(1),
            is_global_context=True,
            strategy=MissingKeyStrategy.SILENT,
        )
        assert loader.get() is True
        assert loader.is_initialized() is True
        # Warm fast-path for a global provider must also return literal True.
        assert loader.get() is True
        assert len(runs) == 1

    def test_get_instance_provider_returns_instance_not_true(self):
        # An instance provider must return the value, never the global-context True.
        loader = LazyLoader(lambda: "value", strategy=MissingKeyStrategy.SILENT)
        assert loader.get() == "value"

    def test_get_missing_key_error_strategy_raises_configuration_error(self):
        # Two missing keys: pins the provider name, BOTH missing indices joined with
        # ", ", and the trailing missing-values payload `[None, None]`.
        loader = LazyLoader(
            lambda: 1,
            required_keys=[None, None],
            provider_name="missprov",
            strategy=MissingKeyStrategy.ERROR,
        )
        with pytest.raises(
            ConfigurationError,
            match=(
                r"Cannot initialize provider 'missprov' - missing values at "
                r"index 0, index 1: \[None, None\]"
            ),
        ):
            loader.get()

    def test_get_missing_key_warn_returns_none(self):
        loader = LazyLoader(
            lambda: 1,
            required_keys=[None],
            strategy=MissingKeyStrategy.WARN,
        )
        assert loader.get() is None

    def test_get_missing_key_silent_returns_none(self):
        loader = LazyLoader(
            lambda: 1,
            required_keys=[None],
            strategy=MissingKeyStrategy.SILENT,
        )
        assert loader.get() is None

    def test_get_validation_failure_error_strategy_raises(self):
        loader = LazyLoader(
            lambda: 1,
            required_keys=["a"],
            validate_values_func=lambda keys: False,
            provider_name="valprov",
            strategy=MissingKeyStrategy.ERROR,
        )
        with pytest.raises(
            ConfigurationError,
            match=r"Cannot initialize provider 'valprov' - value validation failed",
        ):
            loader.get()

    def test_get_validation_failure_warn_returns_none(self):
        loader = LazyLoader(
            lambda: 1,
            required_keys=["a"],
            validate_values_func=lambda keys: False,
            strategy=MissingKeyStrategy.WARN,
        )
        assert loader.get() is None

    def test_get_loader_exception_error_strategy_wraps_in_configuration_error(self):
        def bad_loader():
            raise RuntimeError("init failed")

        loader = LazyLoader(bad_loader, provider_name="badprov", strategy=MissingKeyStrategy.ERROR)
        # Pin provider name + original error text inside the wrapped message.
        with pytest.raises(
            ConfigurationError,
            match=r"Failed to initialize provider 'badprov': init failed",
        ) as exc:
            loader.get()
        # original error chained, not swallowed
        assert isinstance(exc.value.__cause__, RuntimeError)
        assert str(exc.value.__cause__) == "init failed"

    def test_get_loader_exception_warn_strategy_returns_none(self):
        def bad_loader():
            raise RuntimeError("init failed")

        loader = LazyLoader(bad_loader, strategy=MissingKeyStrategy.WARN)
        assert loader.get() is None

    def test_get_raises_runtime_error_for_async_loader(self):
        async def async_loader():
            return 1

        loader = LazyLoader(
            async_loader, provider_name="myprov", strategy=MissingKeyStrategy.SILENT
        )
        # Pin both message fragments: the provider name AND the diagnostic suffix.
        with pytest.raises(
            RuntimeError, match=r"Provider 'myprov' has an async loader function\. Use aget"
        ):
            loader.get()

    def test_get_raises_when_sync_loader_returns_a_coroutine(self):
        # A loader detected as sync but actually returning a coroutine must be caught
        # by _initialize_sync's coroutine guard (not silently cached as the instance).
        created: list = []

        async def _inner():
            return 1

        def sneaky_sync_loader():
            coro = _inner()  # a coroutine, but the loader itself is sync
            created.append(coro)
            return coro

        loader = LazyLoader(
            sneaky_sync_loader, provider_name="sneaky", strategy=MissingKeyStrategy.ERROR
        )
        try:
            with pytest.raises(
                ConfigurationError,
                match=r"Sync initialization called on async loader function for 'sneaky'",
            ):
                loader.get()
            assert loader.is_initialized() is False
        finally:
            for coro in created:
                coro.close()

    def test_initialize_sync_rejects_async_provider_directly(self):
        # Calling the sync initializer on an async provider must raise rather than
        # attempt a synchronous call of the coroutine function.
        async def async_loader():
            return 1

        loader = LazyLoader(
            async_loader, provider_name="asyncprov", strategy=MissingKeyStrategy.SILENT
        )
        with pytest.raises(
            RuntimeError,
            match=r"Cannot synchronously initialize async provider 'asyncprov'",
        ):
            loader._initialize_sync()


# ---------------------------------------------------------------------------
# LazyLoader — async aget()
# ---------------------------------------------------------------------------


class TestLazyLoaderAsyncGet:
    async def test_aget_runs_sync_loader_and_returns_value(self):
        loader = LazyLoader(lambda: 99, strategy=MissingKeyStrategy.SILENT)
        assert await loader.aget() == 99

    async def test_aget_runs_async_loader_and_marks_initialized(self):
        async def async_loader():
            return 77

        loader = LazyLoader(async_loader, strategy=MissingKeyStrategy.SILENT)
        assert await loader.aget() == 77
        assert loader.is_initialized() is True

    async def test_aget_async_global_context_returns_true_and_configures(self):
        runs = []

        async def async_global():
            runs.append(1)

        loader = LazyLoader(
            async_global,
            is_global_context=True,
            strategy=MissingKeyStrategy.SILENT,
        )
        assert await loader.aget() is True
        assert loader.is_initialized() is True
        # warm fast-path for async global returns True without re-running side effect
        assert await loader.aget() is True
        assert len(runs) == 1

    async def test_aget_sync_global_context_returns_true(self):
        runs = []
        loader = LazyLoader(
            lambda: runs.append(1),
            is_global_context=True,
            strategy=MissingKeyStrategy.SILENT,
        )
        assert await loader.aget() is True
        assert await loader.aget() is True
        assert len(runs) == 1

    async def test_aget_instance_provider_returns_instance_not_true(self):
        async def async_loader():
            return "value"

        loader = LazyLoader(async_loader, strategy=MissingKeyStrategy.SILENT)
        assert await loader.aget() == "value"

    async def test_aget_caches_async_result(self):
        call_count = 0

        async def counting_loader():
            nonlocal call_count
            call_count += 1
            return call_count

        loader = LazyLoader(counting_loader, strategy=MissingKeyStrategy.SILENT)
        assert await loader.aget() == 1
        assert await loader.aget() == 1
        assert call_count == 1

    async def test_aget_caches_sync_result(self):
        sentinel = object()
        loader = LazyLoader(lambda: sentinel, strategy=MissingKeyStrategy.SILENT)
        assert await loader.aget() is sentinel
        assert await loader.aget() is sentinel

    async def test_aget_missing_key_error_strategy_raises(self):
        async def loader():
            return 1

        ll = LazyLoader(
            loader,
            required_keys=[None],
            provider_name="amissprov",
            strategy=MissingKeyStrategy.ERROR,
        )
        with pytest.raises(
            ConfigurationError,
            match=r"Cannot initialize provider 'amissprov' - missing values at index 0",
        ):
            await ll.aget()

    async def test_aget_missing_key_silent_returns_none(self):
        async def loader():
            return 1

        ll = LazyLoader(loader, required_keys=[None], strategy=MissingKeyStrategy.SILENT)
        assert await ll.aget() is None

    async def test_aget_validation_failure_error_raises(self):
        async def loader():
            return 1

        ll = LazyLoader(
            loader,
            required_keys=["a"],
            validate_values_func=lambda keys: False,
            provider_name="avalprov",
            strategy=MissingKeyStrategy.ERROR,
        )
        with pytest.raises(
            ConfigurationError,
            match=r"Cannot initialize provider 'avalprov' - value validation failed",
        ):
            await ll.aget()

    async def test_aget_validation_failure_warn_returns_none(self):
        async def loader():
            return 1

        ll = LazyLoader(
            loader,
            required_keys=["a"],
            validate_values_func=lambda keys: False,
            strategy=MissingKeyStrategy.WARN,
        )
        assert await ll.aget() is None

    async def test_aget_exception_error_strategy_raises(self):
        async def bad():
            raise RuntimeError("boom")

        ll = LazyLoader(bad, provider_name="abadprov", strategy=MissingKeyStrategy.ERROR)
        with pytest.raises(
            ConfigurationError, match=r"Failed to initialize provider 'abadprov': boom"
        ):
            await ll.aget()

    async def test_aget_exception_warn_strategy_returns_none(self):
        async def bad():
            raise RuntimeError("boom")

        ll = LazyLoader(bad, strategy=MissingKeyStrategy.WARN)
        assert await ll.aget() is None

    async def test_aget_sync_loader_returning_coroutine_is_rejected(self):
        # aget() on a SYNC-detected loader routes through _initialize_sync; a sync
        # loader that returns a coroutine is caught by the sync coroutine guard and
        # wrapped in ConfigurationError under ERROR strategy (not cached).
        created: list = []

        async def _inner():
            return 1

        def sneaky():
            coro = _inner()
            created.append(coro)
            return coro

        loader = LazyLoader(sneaky, provider_name="asneaky", strategy=MissingKeyStrategy.ERROR)
        try:
            with pytest.raises(
                ConfigurationError,
                match=r"Sync initialization called on async loader function for 'asneaky'",
            ):
                await loader.aget()
            assert loader.is_initialized() is False
        finally:
            for coro in created:
                coro.close()

    async def test_aget_raises_when_async_lock_missing(self):
        async def loader():
            return 1

        ll = LazyLoader(loader, provider_name="lockprov", strategy=MissingKeyStrategy.SILENT)
        # Force the defensive guard: async loader but no async lock.
        ll._async_lock = None
        with pytest.raises(
            RuntimeError, match=r"Async lock not initialized for provider 'lockprov'"
        ):
            await ll.aget()


# ---------------------------------------------------------------------------
# LazyLoader — reset
# ---------------------------------------------------------------------------


class TestLazyLoaderReset:
    def test_reset_clears_sync_instance(self):
        loader = LazyLoader(lambda: 42, strategy=MissingKeyStrategy.SILENT)
        loader.get()
        assert loader.is_initialized() is True
        loader.reset()
        assert loader.is_initialized() is False
        assert loader._instance is None

    def test_reset_clears_global_configured_flag(self):
        loader = LazyLoader(
            lambda: None,
            is_global_context=True,
            strategy=MissingKeyStrategy.SILENT,
        )
        loader.get()
        assert loader.is_initialized() is True
        loader.reset()
        assert loader.is_initialized() is False
        assert loader._is_configured is False

    async def test_reset_async_loader_clears_state(self):
        async def loader():
            return 1

        ll = LazyLoader(loader, strategy=MissingKeyStrategy.SILENT)
        ll._instance = "cached"
        ll._is_configured = True
        ll.reset()
        # Under a running loop reset() resets synchronously.
        assert ll._instance is None
        assert ll._is_configured is False


# ---------------------------------------------------------------------------
# LazyLoader — auto_initialize at construction
# ---------------------------------------------------------------------------


class TestAutoInitialize:
    def test_auto_init_sync_available_initializes_eagerly(self):
        loader = LazyLoader(
            lambda: 100,
            auto_initialize=True,
            strategy=MissingKeyStrategy.SILENT,
        )
        assert loader.is_initialized() is True
        assert loader.get() == 100

    def test_auto_init_skipped_when_not_available(self):
        loader = LazyLoader(
            lambda: 100,
            required_keys=[None],
            auto_initialize=True,
            strategy=MissingKeyStrategy.SILENT,
        )
        assert loader.is_initialized() is False

    def test_auto_init_async_is_deferred_not_run_in_init(self):
        async def loader():
            return 1

        ll = LazyLoader(
            loader,
            auto_initialize=True,
            strategy=MissingKeyStrategy.SILENT,
        )
        # Async loaders can't run in __init__ — deferred to first aget().
        assert ll.is_initialized() is False

    def test_auto_init_failure_error_strategy_raises(self):
        def bad():
            raise RuntimeError("fail")

        with pytest.raises(ConfigurationError, match="Failed to initialize"):
            LazyLoader(bad, auto_initialize=True, strategy=MissingKeyStrategy.ERROR)

    def test_auto_init_failure_warn_strategy_continues(self):
        def bad():
            raise RuntimeError("fail")

        loader = LazyLoader(bad, auto_initialize=True, strategy=MissingKeyStrategy.WARN)
        assert loader.is_initialized() is False


# ---------------------------------------------------------------------------
# ProviderRegistry — register / get / introspection
# ---------------------------------------------------------------------------


class TestProviderRegistry:
    def test_register_then_get_returns_value(self):
        reg = ProviderRegistry()
        name = _uid("reg")
        reg.register(name, lambda: 42, strategy=MissingKeyStrategy.SILENT)
        assert reg.get(name) == 42

    def test_get_unknown_raises_keyerror(self):
        reg = ProviderRegistry()
        with pytest.raises(KeyError, match=r"Provider 'ghost_sync' not found in registry"):
            reg.get("ghost_sync")

    async def test_aget_unknown_raises_keyerror(self):
        reg = ProviderRegistry()
        with pytest.raises(KeyError, match=r"Provider 'ghost_async' not found in registry"):
            await reg.aget("ghost_async")

    async def test_aget_sync_provider_returns_value(self):
        reg = ProviderRegistry()
        name = _uid("areg")
        reg.register(name, lambda: 55, strategy=MissingKeyStrategy.SILENT)
        assert await reg.aget(name) == 55

    async def test_aget_async_provider_returns_value(self):
        reg = ProviderRegistry()
        name = _uid("areg_async")

        async def loader():
            return 88

        reg.register(name, loader, strategy=MissingKeyStrategy.SILENT)
        assert await reg.aget(name) == 88

    def test_get_loader_returns_the_loader_for_that_name(self):
        reg = ProviderRegistry()
        name = _uid("gl")
        reg.register(name, lambda: 1, strategy=MissingKeyStrategy.SILENT)
        loader = reg.get_loader(name)
        assert isinstance(loader, LazyLoader)
        assert loader.provider_name == name

    def test_get_loader_unknown_raises_keyerror(self):
        reg = ProviderRegistry()
        with pytest.raises(KeyError, match=r"Provider 'ghost_loader' not found in registry"):
            reg.get_loader("ghost_loader")

    def test_is_available_true_for_registered_false_for_unknown(self):
        reg = ProviderRegistry()
        name = _uid("avail")
        reg.register(name, lambda: 1, strategy=MissingKeyStrategy.SILENT)
        assert reg.is_available(name) is True
        assert reg.is_available("nonexistent") is False

    def test_is_available_false_for_registered_with_missing_keys(self):
        reg = ProviderRegistry()
        name = _uid("avail_missing")
        reg.register(name, lambda: 1, required_keys=[None], strategy=MissingKeyStrategy.SILENT)
        assert reg.is_available(name) is False

    def test_is_initialized_tracks_first_get_and_unknown_is_false(self):
        reg = ProviderRegistry()
        name = _uid("init")
        reg.register(name, lambda: 1, strategy=MissingKeyStrategy.SILENT)
        assert reg.is_initialized(name) is False
        reg.get(name)
        assert reg.is_initialized(name) is True
        assert reg.is_initialized("nonexistent") is False

    def test_list_providers_reports_status_flags(self):
        reg = ProviderRegistry()
        sync_name = _uid("list_sync")
        async_name = _uid("list_async")
        global_name = _uid("list_global")

        async def aloader():
            return 1

        reg.register(sync_name, lambda: 1, strategy=MissingKeyStrategy.SILENT)
        reg.register(async_name, aloader, strategy=MissingKeyStrategy.SILENT)
        reg.register(
            global_name,
            lambda: None,
            is_global_context=True,
            strategy=MissingKeyStrategy.SILENT,
        )
        reg.get(sync_name)

        listing = reg.list_providers()
        assert listing[sync_name] == {
            "available": True,
            "initialized": True,
            "is_global_context": False,
            "is_async": False,
        }
        assert listing[async_name]["is_async"] is True
        assert listing[async_name]["initialized"] is False
        assert listing[global_name]["is_global_context"] is True

    def test_re_register_overwrites_previous_loader(self):
        reg = ProviderRegistry()
        name = _uid("reregister")
        reg.register(name, lambda: 1, strategy=MissingKeyStrategy.SILENT)
        reg.register(name, lambda: 2, strategy=MissingKeyStrategy.SILENT)
        assert reg.get(name) == 2

    def test_re_register_logs_warning(self):
        reg = ProviderRegistry()
        name = _uid("reregister_warn")
        reg.register(name, lambda: 1, strategy=MissingKeyStrategy.SILENT)
        with patch("app.core.lazy_loader.log.warning") as mock_warn:
            reg.register(name, lambda: 2, strategy=MissingKeyStrategy.SILENT)
        logged = " ".join(str(c.args[0]) for c in mock_warn.call_args_list)
        assert "re-registered" in logged
        assert name in logged


# ---------------------------------------------------------------------------
# ProviderRegistry — dependencies
# ---------------------------------------------------------------------------


class TestProviderRegistryDependencies:
    def test_dependency_initialized_before_target(self):
        reg = ProviderRegistry()
        dep_name = _uid("dep")
        main_name = _uid("main")
        call_order: list[str] = []

        reg.register(
            dep_name,
            lambda: call_order.append("dep") or "dep_val",
            strategy=MissingKeyStrategy.SILENT,
        )
        reg.register(
            main_name,
            lambda: call_order.append("main") or "main_val",
            strategy=MissingKeyStrategy.SILENT,
            dependencies=[dep_name],
        )

        result = reg.get(main_name)
        assert call_order == ["dep", "main"]
        assert result == "main_val"
        assert reg.is_initialized(dep_name) is True

    def test_already_initialized_auto_init_dependency_not_re_fetched(self):
        # Pins the skip-branch: an auto-init dep that is already initialized must be
        # skipped (continue), so its loader runs exactly once.
        reg = ProviderRegistry()
        dep_name = _uid("autodep")
        main_name = _uid("usesauto")
        dep_calls = []

        reg.register(
            dep_name,
            lambda: dep_calls.append(1) or "dep_val",
            strategy=MissingKeyStrategy.SILENT,
            auto_initialize=True,
        )
        # auto_initialize ran the dep once at registration
        assert dep_calls == [1]
        assert reg.is_initialized(dep_name) is True

        reg.register(
            main_name,
            lambda: "main_val",
            strategy=MissingKeyStrategy.SILENT,
            dependencies=[dep_name],
        )
        assert reg.get(main_name) == "main_val"
        # dep must NOT have been re-initialized
        assert dep_calls == [1]

    def test_cyclic_dependency_raises(self):
        reg = ProviderRegistry()
        a = _uid("a")
        b = _uid("b")

        reg.register(a, lambda: 1, strategy=MissingKeyStrategy.SILENT, dependencies=[b])
        reg.register(b, lambda: 2, strategy=MissingKeyStrategy.SILENT, dependencies=[a])

        # Pin the rendered cycle path, incl. the " -> " join separator between hops.
        with pytest.raises(
            ConfigurationError,
            match=rf"Cyclic dependency detected: {a} -> {b} -> {a}",
        ):
            reg.get(a)

    async def test_async_dependency_initialized_before_target(self):
        reg = ProviderRegistry()
        dep_name = _uid("adep")
        main_name = _uid("amain")

        async def dep_loader():
            return "dep_val"

        async def main_loader():
            return "main_val"

        reg.register(dep_name, dep_loader, strategy=MissingKeyStrategy.SILENT)
        reg.register(
            main_name,
            main_loader,
            strategy=MissingKeyStrategy.SILENT,
            dependencies=[dep_name],
        )

        assert await reg.aget(main_name) == "main_val"
        assert reg.is_initialized(dep_name) is True


# ---------------------------------------------------------------------------
# ProviderRegistry — initialize_auto_providers
# ---------------------------------------------------------------------------


class TestInitializeAutoProviders:
    async def test_initializes_registered_auto_provider(self):
        reg = ProviderRegistry()
        name = _uid("auto")

        async def loader():
            return "val"

        reg.register(name, loader, strategy=MissingKeyStrategy.SILENT, auto_initialize=True)
        await reg.initialize_auto_providers()
        assert reg.is_initialized(name) is True

    async def test_non_auto_provider_left_uninitialized(self):
        # Only providers in the auto-init set are warmed.
        reg = ProviderRegistry()
        auto_name = _uid("auto_yes")
        plain_name = _uid("auto_no")

        async def loader():
            return 1

        reg.register(auto_name, loader, strategy=MissingKeyStrategy.SILENT, auto_initialize=True)
        reg.register(plain_name, loader, strategy=MissingKeyStrategy.SILENT)
        await reg.initialize_auto_providers()
        assert reg.is_initialized(auto_name) is True
        assert reg.is_initialized(plain_name) is False

    async def test_skips_unavailable_in_non_strict_mode(self):
        reg = ProviderRegistry()
        name = _uid("auto_unavail")

        async def loader():
            return 1

        reg.register(
            name,
            loader,
            required_keys=[None],
            strategy=MissingKeyStrategy.WARN,
            auto_initialize=True,
        )
        await reg.initialize_auto_providers()
        assert reg.is_initialized(name) is False

    async def test_strict_does_not_raise_for_unavailable_warn_strategy(self):
        # Pins `strict and strategy == ERROR` (And->Or): a WARN-strategy unavailable
        # provider must NOT raise even under strict.
        reg = ProviderRegistry()
        name = _uid("auto_unavail_warn")

        async def loader():
            return 1

        reg.register(
            name,
            loader,
            required_keys=[None],
            strategy=MissingKeyStrategy.WARN,
            auto_initialize=True,
        )
        await reg.initialize_auto_providers(strict=True)  # must not raise
        assert reg.is_initialized(name) is False

    async def test_strict_raises_for_unavailable_error_strategy(self):
        reg = ProviderRegistry()
        name = _uid("strict_unavail")

        async def loader():
            return 1

        reg.register(
            name,
            loader,
            required_keys=[None],
            strategy=MissingKeyStrategy.ERROR,
            auto_initialize=True,
        )
        # Pin both the failure-message prefix and the failing provider's name.
        with pytest.raises(RuntimeError, match=rf"Auto-initialization failed for: {name}"):
            await reg.initialize_auto_providers(strict=True)

    async def test_strict_raises_on_init_failure(self):
        reg = ProviderRegistry()
        name = _uid("strict_fail")

        async def bad():
            raise RuntimeError("boom")

        reg.register(name, bad, strategy=MissingKeyStrategy.ERROR, auto_initialize=True)
        with pytest.raises(RuntimeError, match=rf"Auto-initialization failed for: {name}"):
            await reg.initialize_auto_providers(strict=True)

    async def test_strict_aggregates_multiple_failing_providers(self):
        # Two failing providers -> the RuntimeError must list BOTH, comma-joined.
        # Pins the `", ".join(...)` separator (blanking it would concatenate names).
        reg = ProviderRegistry()
        name_a = _uid("multi_a")
        name_b = _uid("multi_b")

        async def bad():
            raise RuntimeError("boom")

        reg.register(name_a, bad, strategy=MissingKeyStrategy.ERROR, auto_initialize=True)
        reg.register(name_b, bad, strategy=MissingKeyStrategy.ERROR, auto_initialize=True)
        with pytest.raises(RuntimeError) as exc:
            await reg.initialize_auto_providers(strict=True)
        message = str(exc.value)
        assert name_a in message
        assert name_b in message
        # the two names are separated by ", " — they are never adjacent
        assert f"{name_a}{name_b}" not in message
        assert f"{name_b}{name_a}" not in message

    async def test_default_is_non_strict_and_swallows_init_failure(self):
        # Pins `strict and errors` (And->Or) at the tail AND the `strict=False`
        # default: called with NO strict arg, a failing provider must not raise.
        reg = ProviderRegistry()
        name = _uid("nonstrict_fail")

        async def bad():
            raise RuntimeError("boom")

        reg.register(name, bad, strategy=MissingKeyStrategy.ERROR, auto_initialize=True)
        await reg.initialize_auto_providers()  # default strict=False -> must not raise
        assert reg.is_initialized(name) is False

    async def test_no_auto_providers_is_noop(self):
        reg = ProviderRegistry()
        await reg.initialize_auto_providers()  # should not raise


# ---------------------------------------------------------------------------
# ProviderRegistry — warmup_all
# ---------------------------------------------------------------------------


class TestWarmupAll:
    async def test_warmup_initializes_available_provider(self):
        reg = ProviderRegistry()
        name = _uid("warm")
        reg.register(name, lambda: 42, strategy=MissingKeyStrategy.SILENT)
        await reg.warmup_all()
        assert reg.is_initialized(name) is True

    async def test_warmup_skips_unavailable_provider(self):
        reg = ProviderRegistry()
        name = _uid("warm_unavail")
        reg.register(name, lambda: 1, required_keys=[None], strategy=MissingKeyStrategy.SILENT)
        await reg.warmup_all()
        assert reg.is_initialized(name) is False

    async def test_warmup_strict_raises_for_unavailable_error_strategy(self):
        reg = ProviderRegistry()
        name = _uid("warm_strict")
        reg.register(name, lambda: 1, required_keys=[None], strategy=MissingKeyStrategy.ERROR)
        with pytest.raises(RuntimeError, match=rf"Provider warmup failed for: {name}"):
            await reg.warmup_all(strict=True)

    async def test_warmup_strict_does_not_raise_for_unavailable_warn_strategy(self):
        # Pins `strict and strategy == ERROR` in warmup (And->Or): WARN unavailable
        # must not be treated as a strict failure.
        reg = ProviderRegistry()
        good_name = _uid("warm_strict_good")
        warn_name = _uid("warm_strict_warn")
        reg.register(good_name, lambda: 1, strategy=MissingKeyStrategy.SILENT)
        reg.register(warn_name, lambda: 1, required_keys=[None], strategy=MissingKeyStrategy.WARN)
        await reg.warmup_all(strict=True)  # must not raise
        assert reg.is_initialized(good_name) is True
        assert reg.is_initialized(warn_name) is False

    async def test_warmup_strict_raises_on_init_failure(self):
        reg = ProviderRegistry()
        name = _uid("warm_fail")

        async def bad():
            raise RuntimeError("init fail")

        reg.register(name, bad, strategy=MissingKeyStrategy.ERROR)
        with pytest.raises(RuntimeError, match=rf"Provider warmup failed for: {name}"):
            await reg.warmup_all(strict=True)

    async def test_warmup_default_is_non_strict_swallows_propagating_failure(self):
        # An ERROR-strategy available provider raises out of aget() during warmup.
        # With the default (strict=False) the aggregated error must be swallowed, so
        # warmup_all() called with NO strict arg must NOT raise. Pins `strict=False`
        # default (L533): flipping it to True would re-raise here.
        reg = ProviderRegistry()
        good_name = _uid("warm_good")
        bad_name = _uid("warm_bad")

        async def bad():
            raise RuntimeError("fail")

        reg.register(good_name, lambda: 1, strategy=MissingKeyStrategy.SILENT)
        reg.register(bad_name, bad, strategy=MissingKeyStrategy.ERROR)

        await reg.warmup_all()  # default strict=False -> must not raise
        assert reg.is_initialized(good_name) is True

    async def test_warmup_strict_aggregates_multiple_failures(self):
        # Two failing providers -> the warmup RuntimeError lists both, comma-joined.
        # Pins the `", ".join(...)` separator in the warmup failure path.
        reg = ProviderRegistry()
        name_a = _uid("warm_multi_a")
        name_b = _uid("warm_multi_b")

        async def bad():
            raise RuntimeError("fail")

        reg.register(name_a, bad, strategy=MissingKeyStrategy.ERROR)
        reg.register(name_b, bad, strategy=MissingKeyStrategy.ERROR)
        with pytest.raises(RuntimeError) as exc:
            await reg.warmup_all(strict=True)
        message = str(exc.value)
        assert name_a in message
        assert name_b in message
        assert f"{name_a}{name_b}" not in message
        assert f"{name_b}{name_a}" not in message

    async def test_warmup_empty_registry_is_noop(self):
        reg = ProviderRegistry()
        await reg.warmup_all()  # noop, should not raise

    async def test_warmup_strict_empty_after_skips_raises_on_collected_error(self):
        # Every provider unavailable -> warmup_names empty -> the early-return branch
        # must still re-raise under strict when ERROR providers were collected.
        # Pins `strict and errors` (And->Or) and the `", ".join` separator in the
        # empty-warmup branch (two names comma-joined, never concatenated).
        reg = ProviderRegistry()
        name_a = _uid("warm_skip_a")
        name_b = _uid("warm_skip_b")
        reg.register(name_a, lambda: 1, required_keys=[None], strategy=MissingKeyStrategy.ERROR)
        reg.register(name_b, lambda: 1, required_keys=[None], strategy=MissingKeyStrategy.ERROR)
        with pytest.raises(RuntimeError, match="Provider warmup failed for:") as exc:
            await reg.warmup_all(strict=True)
        message = str(exc.value)
        assert name_a in message
        assert name_b in message
        assert f"{name_a}{name_b}" not in message
        assert f"{name_b}{name_a}" not in message


# ---------------------------------------------------------------------------
# lazy_provider decorator
# ---------------------------------------------------------------------------


class TestLazyProviderDecorator:
    def test_decorator_registers_and_resolves_value(self):
        name = _uid("deco")

        @lazy_provider(name=name, strategy=MissingKeyStrategy.SILENT)
        def my_provider():
            return 99

        loader = my_provider()
        assert isinstance(loader, LazyLoader)
        # not initialized until first get()
        assert loader.is_initialized() is False
        assert providers.get(name) == 99

    def test_decorator_does_not_auto_initialize_by_default(self):
        # Pins the decorator's `auto_initialize=False` default: registering must NOT
        # initialize the provider.
        name = _uid("deco_no_auto")
        runs = []

        @lazy_provider(name=name, strategy=MissingKeyStrategy.SILENT)
        def my_provider():
            runs.append(1)
            return 1

        my_provider()
        assert providers.is_initialized(name) is False
        assert runs == []

    def test_decorator_preserves_async_nature(self):
        name = _uid("deco_async")

        @lazy_provider(name=name, strategy=MissingKeyStrategy.SILENT)
        async def my_async_provider():
            return 77

        loader = my_async_provider()
        assert loader.is_async is True

    def test_decorator_threads_required_keys(self):
        name = _uid("deco_keys")

        @lazy_provider(name=name, required_keys=[None], strategy=MissingKeyStrategy.SILENT)
        def my_provider():
            return 1

        loader = my_provider()
        assert loader.is_available() is False

    def test_decorator_global_context_returns_true_once(self):
        name = _uid("deco_global")
        configured = []

        @lazy_provider(
            name=name,
            is_global_context=True,
            strategy=MissingKeyStrategy.SILENT,
        )
        def configure_global():
            configured.append(True)

        configure_global()
        assert providers.get(name) is True
        assert configured == [True]


# ---------------------------------------------------------------------------
# MissingKeyStrategy enum
# ---------------------------------------------------------------------------


class TestMissingKeyStrategy:
    def test_enum_values(self):
        assert MissingKeyStrategy.ERROR.value == "error"
        assert MissingKeyStrategy.WARN.value == "warn"
        assert MissingKeyStrategy.WARN_ONCE.value == "warn_once"
        assert MissingKeyStrategy.SILENT.value == "silent"
