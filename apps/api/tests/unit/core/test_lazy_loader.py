"""Tests for app/core/lazy_loader.py — LazyLoader, ProviderRegistry, lazy_provider."""

import asyncio
from collections.abc import Callable
import threading
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
    """Return a unique provider name to avoid cross-test pollution."""
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


class _AcquireSignalingLock:
    """A `threading.Lock` stand-in that fires an event the instant `acquire()`
    is called, before it blocks on the real lock.

    Used to deterministically prove a second thread has passed its outer
    quick-check and reached `with self._lock:` — without this, a plain
    `threading.Event` set right before the call to `get()`/`aget()` leaves a
    window where the thread hasn't actually reached the lock statement yet,
    so a caller could race past the outer check via ordinary scheduling
    luck rather than the deliberately red/green-checked inner branch.
    """

    def __init__(self, about_to_acquire: threading.Event) -> None:
        self._real_lock = threading.Lock()
        self._about_to_acquire = about_to_acquire

    def acquire(self, blocking: bool = True, timeout: float = -1) -> bool:
        self._about_to_acquire.set()
        return self._real_lock.acquire(blocking, timeout)

    def release(self) -> None:
        self._real_lock.release()

    def __enter__(self) -> "_AcquireSignalingLock":
        self.acquire()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.release()


def _run_two_threaded_lock_race(
    second_call: Callable[[LazyLoader], bool | None],
) -> tuple[bool | None, bool | None, int]:
    """Run the double-checked-locking race deterministically and report both
    callers' results plus how many times the loader actually ran.

    Thread A holds `loader._lock` blocked inside the loader function; thread
    B is proven (via `_AcquireSignalingLock`) to have reached `with
    self._lock:` before A's `_is_configured` flip is released — so `B`'s
    result and the loader call count prove whether B took the inner
    double-check fast path or wastefully re-ran the loader.

    `second_call` is B's actual call (`loader.get()` or
    `asyncio.run(loader.aget())`), so the same race harness proves the fast
    path for both the sync `get()` double-check and the
    `aget()`-on-a-sync-loader double-check without duplicating the
    coordination.
    """
    call_count = 0
    entered_loader = threading.Event()
    release_loader = threading.Event()

    def blocking_loader() -> None:
        nonlocal call_count
        call_count += 1
        entered_loader.set()
        assert release_loader.wait(timeout=5)

    loader = LazyLoader(
        blocking_loader,
        is_global_context=True,
        strategy=MissingKeyStrategy.SILENT,
    )
    b_about_to_acquire = threading.Event()
    loader._lock = _AcquireSignalingLock(b_about_to_acquire)  # type: ignore[assignment]  # test swaps the private lock for a signaling double

    first_result: list[bool | None] = []
    second_result: list[bool | None] = []

    def call_first() -> None:
        first_result.append(loader.get())

    def call_second() -> None:
        second_result.append(second_call(loader))

    thread_a = threading.Thread(target=call_first)
    thread_a.start()
    assert entered_loader.wait(timeout=5)  # A holds the lock, blocked in the loader
    # A's own acquire() already fired the shared event above; clear it so the
    # next wait genuinely observes thread B's (not thread A's) acquire.
    b_about_to_acquire.clear()

    thread_b = threading.Thread(target=call_second)
    thread_b.start()
    assert b_about_to_acquire.wait(timeout=5)  # B is now blocked trying to acquire

    release_loader.set()
    thread_a.join(timeout=5)
    thread_b.join(timeout=5)

    return first_result[0], second_result[0], call_count


# ---------------------------------------------------------------------------
# LazyLoader — basic init & is_available
# ---------------------------------------------------------------------------


class TestLazyLoaderInit:
    def test_default_provider_name_is_func_name(self):
        def my_func():
            return 42

        loader = LazyLoader(my_func, strategy=MissingKeyStrategy.SILENT)
        assert loader.provider_name == "my_func"

    def test_custom_provider_name(self):
        loader = LazyLoader(lambda: 1, provider_name="custom", strategy=MissingKeyStrategy.SILENT)
        assert loader.provider_name == "custom"

    def test_is_available_all_keys_present(self):
        loader = LazyLoader(
            lambda: 1,
            required_keys=["val1", "val2"],
            strategy=MissingKeyStrategy.SILENT,
        )
        assert loader.is_available() is True

    def test_is_available_missing_key_none(self):
        loader = LazyLoader(
            lambda: 1,
            required_keys=["val1", None],
            strategy=MissingKeyStrategy.SILENT,
        )
        assert loader.is_available() is False

    def test_is_available_missing_key_empty_string(self):
        loader = LazyLoader(
            lambda: 1,
            required_keys=["val1", "  "],
            strategy=MissingKeyStrategy.SILENT,
        )
        assert loader.is_available() is False

    def test_is_available_with_custom_validator_pass(self):
        loader = LazyLoader(
            lambda: 1,
            required_keys=["a"],
            validate_values_func=lambda keys: True,
            strategy=MissingKeyStrategy.SILENT,
        )
        assert loader.is_available() is True

    def test_is_available_with_custom_validator_fail(self):
        loader = LazyLoader(
            lambda: 1,
            required_keys=["a"],
            validate_values_func=lambda keys: False,
            strategy=MissingKeyStrategy.SILENT,
        )
        assert loader.is_available() is False

    def test_is_initialized_false_initially(self):
        loader = LazyLoader(lambda: 1, strategy=MissingKeyStrategy.SILENT)
        assert loader.is_initialized() is False

    def test_is_initialized_global_context(self):
        loader = LazyLoader(
            lambda: None,
            is_global_context=True,
            strategy=MissingKeyStrategy.SILENT,
        )
        assert loader.is_initialized() is False


# ---------------------------------------------------------------------------
# LazyLoader — sync get()
# ---------------------------------------------------------------------------


class TestLazyLoaderSyncGet:
    def test_get_returns_instance(self):
        loader = LazyLoader(lambda: 42, strategy=MissingKeyStrategy.SILENT)
        assert loader.get() == 42
        assert loader.is_initialized() is True

    def test_get_caches_instance(self):
        call_count = 0

        def counting_loader():
            nonlocal call_count
            call_count += 1
            return 10 * call_count

        loader = LazyLoader(counting_loader, strategy=MissingKeyStrategy.SILENT)
        assert loader.get() == 10
        assert loader.get() == 10  # cached, not called again
        assert call_count == 1

    def test_get_global_context_returns_true(self):
        loader = LazyLoader(
            lambda: None,
            is_global_context=True,
            strategy=MissingKeyStrategy.SILENT,
        )
        assert loader.get() is True
        assert loader.is_initialized() is True

    def test_get_missing_keys_error_strategy(self):
        loader = LazyLoader(
            lambda: 1,
            required_keys=[None],
            strategy=MissingKeyStrategy.ERROR,
        )
        with pytest.raises(ConfigurationError, match="missing values"):
            loader.get()

    def test_get_missing_keys_warn_returns_none(self):
        loader = LazyLoader(
            lambda: 1,
            required_keys=[None],
            strategy=MissingKeyStrategy.WARN,
        )
        assert loader.get() is None

    def test_get_missing_keys_silent_returns_none(self):
        loader = LazyLoader(
            lambda: 1,
            required_keys=[None],
            strategy=MissingKeyStrategy.SILENT,
        )
        assert loader.get() is None

    def test_get_validation_failure_error(self):
        loader = LazyLoader(
            lambda: 1,
            required_keys=["a"],
            validate_values_func=lambda keys: False,
            strategy=MissingKeyStrategy.ERROR,
        )
        with pytest.raises(ConfigurationError, match="validation failed"):
            loader.get()

    def test_get_validation_failure_warn(self):
        loader = LazyLoader(
            lambda: 1,
            required_keys=["a"],
            validate_values_func=lambda keys: False,
            strategy=MissingKeyStrategy.WARN,
        )
        assert loader.get() is None

    def test_get_loader_exception_error_strategy(self):
        def bad_loader():
            raise RuntimeError("init failed")

        loader = LazyLoader(
            bad_loader,
            strategy=MissingKeyStrategy.ERROR,
        )
        with pytest.raises(ConfigurationError, match="Failed to initialize"):
            loader.get()

    def test_get_loader_exception_warn_strategy(self):
        def bad_loader():
            raise RuntimeError("init failed")

        loader = LazyLoader(
            bad_loader,
            strategy=MissingKeyStrategy.WARN,
        )
        assert loader.get() is None

    def test_get_raises_for_async_loader(self):
        async def async_loader():
            return 1

        loader = LazyLoader(async_loader, strategy=MissingKeyStrategy.SILENT)
        with pytest.raises(RuntimeError, match="async loader"):
            loader.get()

    def test_get_global_context_second_call_takes_outer_fast_path(self):
        """A second get() on an already-configured global-context loader hits
        the outer quick-check (no lock) and must not re-run the loader."""
        call_count = 0

        def counting_loader():
            nonlocal call_count
            call_count += 1

        loader = LazyLoader(
            counting_loader,
            is_global_context=True,
            strategy=MissingKeyStrategy.SILENT,
        )
        assert loader.get() is True
        assert loader.get() is True
        assert call_count == 1

    def test_get_double_check_lock_returns_true_without_reinit(self):
        """A caller that loses the race and blocks on the lock sees
        `_is_configured` already flipped to True by the time it acquires the
        lock, and must take the inner double-check fast path instead of
        calling the loader again. See `_run_two_threaded_lock_race` for how
        the race is made deterministic."""
        first, second, call_count = _run_two_threaded_lock_race(lambda loader: loader.get())

        assert first is True
        assert second is True
        assert call_count == 1  # B never re-ran the loader


# ---------------------------------------------------------------------------
# LazyLoader — async aget()
# ---------------------------------------------------------------------------


class TestLazyLoaderAsyncGet:
    async def test_aget_sync_loader(self):
        loader = LazyLoader(lambda: 99, strategy=MissingKeyStrategy.SILENT)
        result = await loader.aget()
        assert result == 99

    async def test_aget_async_loader(self):
        async def async_loader():
            return 77

        loader = LazyLoader(async_loader, strategy=MissingKeyStrategy.SILENT)
        result = await loader.aget()
        assert result == 77
        assert loader.is_initialized()

    async def test_aget_async_global_context(self):
        async def async_global():
            pass  # side effect only

        loader = LazyLoader(
            async_global,
            is_global_context=True,
            strategy=MissingKeyStrategy.SILENT,
        )
        result = await loader.aget()
        assert result is True

    async def test_aget_caches_result(self):
        call_count = 0

        async def counting_loader():
            nonlocal call_count
            call_count += 1
            return call_count

        loader = LazyLoader(counting_loader, strategy=MissingKeyStrategy.SILENT)
        r1 = await loader.aget()
        r2 = await loader.aget()
        assert r1 == r2 == 1

    async def test_aget_missing_keys_error(self):
        async def loader():
            return 1

        ll = LazyLoader(loader, required_keys=[None], strategy=MissingKeyStrategy.ERROR)
        with pytest.raises(ConfigurationError):
            await ll.aget()

    async def test_aget_missing_keys_silent(self):
        async def loader():
            return 1

        ll = LazyLoader(loader, required_keys=[None], strategy=MissingKeyStrategy.SILENT)
        assert await ll.aget() is None

    async def test_aget_exception_error_strategy(self):
        async def bad():
            raise RuntimeError("boom")

        ll = LazyLoader(bad, strategy=MissingKeyStrategy.ERROR)
        with pytest.raises(ConfigurationError):
            await ll.aget()

    async def test_aget_exception_warn_strategy(self):
        async def bad():
            raise RuntimeError("boom")

        ll = LazyLoader(bad, strategy=MissingKeyStrategy.WARN)
        assert await ll.aget() is None

    async def test_aget_sync_global_context(self):
        loader = LazyLoader(
            lambda: None,
            is_global_context=True,
            strategy=MissingKeyStrategy.SILENT,
        )
        result = await loader.aget()
        assert result is True

    async def test_aget_global_context_second_call_takes_outer_fast_path(self):
        """A second aget() on an already-configured global-context loader
        hits the outer quick-check and must not re-run the async loader."""
        call_count = 0

        async def counting_loader():
            nonlocal call_count
            call_count += 1

        loader = LazyLoader(
            counting_loader,
            is_global_context=True,
            strategy=MissingKeyStrategy.SILENT,
        )
        assert await loader.aget() is True
        assert await loader.aget() is True
        assert call_count == 1

    async def test_aget_async_double_check_lock_returns_true_without_reinit(self):
        """Task B, which loses the race for the async lock while task A is
        still initializing, must see `_is_configured` already True on the
        inner double-check and return without re-running the loader.

        Coordinated purely with `asyncio.Event` and `asyncio.sleep(0)` yields
        — deterministic cooperative scheduling, not a wall-clock race: only
        one coroutine ever runs at a time, and control only passes at an
        explicit `await`.
        """
        call_count = 0
        release_loader = asyncio.Event()

        async def blocking_loader():
            nonlocal call_count
            call_count += 1
            await release_loader.wait()

        loader = LazyLoader(
            blocking_loader,
            is_global_context=True,
            strategy=MissingKeyStrategy.SILENT,
        )

        task_a = asyncio.create_task(loader.aget())
        # Let task A run until it awaits release_loader inside the loader,
        # which it can only do while holding the async lock.
        for _ in range(3):
            await asyncio.sleep(0)

        task_b = asyncio.create_task(loader.aget())
        # Let task B run its outer check (sees _is_configured False, since
        # task A hasn't finished) and start waiting on the still-held lock.
        for _ in range(3):
            await asyncio.sleep(0)

        release_loader.set()
        result_a = await task_a
        result_b = await task_b

        assert result_a is True
        assert result_b is True
        assert call_count == 1  # task B never re-ran the loader

    async def test_aget_sync_loader_double_check_lock_returns_true_without_reinit(self):
        """A sync loader accessed only via `aget()`: a second caller that
        blocks on `self._lock` (the branch at line ~213-222, taken when
        `is_async` is False) must see `_is_configured` already True on the
        inner double-check and skip re-initialization. Same
        `_AcquireSignalingLock`-coordinated race as the sync `get()`
        double-check test (both share `self._lock`) — see
        `_run_two_threaded_lock_race`; only B's call differs here
        (`asyncio.run(loader.aget())` instead of `loader.get()`)."""
        first, second, call_count = _run_two_threaded_lock_race(
            lambda loader: asyncio.run(loader.aget())
        )

        assert first is True
        assert second is True
        assert call_count == 1  # B never re-ran the loader


# ---------------------------------------------------------------------------
# LazyLoader — reset
# ---------------------------------------------------------------------------


class TestLazyLoaderReset:
    def test_reset_sync_loader(self):
        loader = LazyLoader(lambda: 42, strategy=MissingKeyStrategy.SILENT)
        loader.get()
        assert loader.is_initialized()
        loader.reset()
        assert not loader.is_initialized()

    def test_reset_async_loader(self):
        async def loader():
            return 1

        ll = LazyLoader(loader, strategy=MissingKeyStrategy.SILENT)
        ll._instance = "cached"
        ll.reset()
        assert ll._instance is None

    def test_reset_async_loader_inside_a_running_loop_fails_loud(self):
        """Inside a running loop a sync clear races any in-flight aget() —
        fail loud instead of resetting something the initializer overwrites."""

        async def loader():
            return 1

        async def scenario():
            ll = LazyLoader(loader, strategy=MissingKeyStrategy.SILENT)
            ll._instance = "cached"
            ll._is_configured = True
            with pytest.raises(RuntimeError) as exc_info:
                ll.reset()
            # Exact message: it is the migration instruction for callers.
            assert str(exc_info.value) == (
                f"reset() for async provider '{ll.provider_name}' called inside a "
                "running event loop, where it could be overwritten by an in-flight "
                "initialization — await areset() instead, which takes the async lock"
            )
            # Fail loud must not half-reset behind the caller's back.
            assert ll._instance == "cached"
            assert ll._is_configured is True

        asyncio.run(scenario())

    async def test_areset_cannot_be_overwritten_by_an_in_flight_initialization(self):
        """The awaited reset takes the async lock, so an initialization that is
        still inside loader_func cannot repopulate the instance after it."""
        gate = asyncio.Event()
        release = asyncio.Event()

        async def loader():
            gate.set()
            await release.wait()
            return 1

        ll = LazyLoader(loader, strategy=MissingKeyStrategy.SILENT)
        init_task = asyncio.create_task(ll.aget())
        await gate.wait()  # loader_func running, holding _async_lock

        reset_task = asyncio.create_task(ll.areset())
        await asyncio.sleep(0)  # let areset block on the held lock
        assert not reset_task.done()  # it did NOT barge in and clear early

        release.set()
        await asyncio.gather(init_task, reset_task)

        # The initializer ran to completion, but the reset happened AFTER it:
        # nothing survived.
        assert ll._instance is None
        assert ll._is_configured is False
        assert not ll.is_initialized()

    def test_reset_async_loader_without_a_loop_takes_the_async_lock(self):
        """No running loop: the reset goes through areset(), which demands the
        provider's async lock."""

        async def loader():
            return 1

        ll = LazyLoader(loader, strategy=MissingKeyStrategy.SILENT)
        ll._async_lock = None
        ll._instance = "cached"
        with pytest.raises(RuntimeError, match="Async lock not initialized"):
            ll.reset()

    def test_reset_global_context(self):
        loader = LazyLoader(
            lambda: None,
            is_global_context=True,
            strategy=MissingKeyStrategy.SILENT,
        )
        loader.get()
        assert loader.is_initialized()
        loader.reset()
        assert not loader.is_initialized()


# ---------------------------------------------------------------------------
# LazyLoader — auto_initialize
# ---------------------------------------------------------------------------


class TestAutoInitialize:
    def test_auto_init_sync_available(self):
        loader = LazyLoader(
            lambda: 100,
            auto_initialize=True,
            strategy=MissingKeyStrategy.SILENT,
        )
        assert loader.is_initialized()
        assert loader.get() == 100

    def test_auto_init_sync_not_available(self):
        loader = LazyLoader(
            lambda: 100,
            required_keys=[None],
            auto_initialize=True,
            strategy=MissingKeyStrategy.SILENT,
        )
        assert not loader.is_initialized()

    def test_auto_init_async_deferred(self):
        """Async providers can't be auto-initialized in __init__, just logged."""

        async def loader():
            return 1

        ll = LazyLoader(
            loader,
            auto_initialize=True,
            strategy=MissingKeyStrategy.SILENT,
        )
        # Not initialized yet (async can't run in __init__)
        assert not ll.is_initialized()

    def test_auto_init_failure_error_strategy_raises(self):
        def bad():
            raise RuntimeError("fail")

        with pytest.raises(ConfigurationError, match="Failed to initialize"):
            LazyLoader(
                bad,
                auto_initialize=True,
                strategy=MissingKeyStrategy.ERROR,
            )

    def test_auto_init_failure_warn_strategy_continues(self):
        def bad():
            raise RuntimeError("fail")

        loader = LazyLoader(
            bad,
            auto_initialize=True,
            strategy=MissingKeyStrategy.WARN,
        )
        assert not loader.is_initialized()


# ---------------------------------------------------------------------------
# LazyLoader — _check_availability_and_warn
# ---------------------------------------------------------------------------


class TestCheckAvailabilityAndWarn:
    def test_warn_strategy_logs_missing(self):
        with patch.object(LazyLoader, "_log_warning") as mock_warn:
            LazyLoader(
                lambda: 1,
                required_keys=[None],
                strategy=MissingKeyStrategy.WARN,
                provider_name="test_prov",
            )
            assert mock_warn.called

    def test_warn_once_sets_warned_indices(self):
        loader = LazyLoader(
            lambda: 1,
            required_keys=[None, "valid", None],
            strategy=MissingKeyStrategy.WARN_ONCE,
            provider_name="test_prov",
        )
        assert 0 in loader._warned_indices
        assert 2 in loader._warned_indices

    def test_silent_does_not_log(self):
        with patch.object(LazyLoader, "_log_warning") as mock_warn:
            LazyLoader(
                lambda: 1,
                required_keys=[None],
                strategy=MissingKeyStrategy.SILENT,
            )
            mock_warn.assert_not_called()

    def test_custom_validation_failure_warns(self):
        with patch.object(LazyLoader, "_log_warning") as mock_warn:
            LazyLoader(
                lambda: 1,
                required_keys=["a"],
                validate_values_func=lambda keys: False,
                strategy=MissingKeyStrategy.WARN,
                provider_name="test_prov",
            )
            assert mock_warn.called


# ---------------------------------------------------------------------------
# ProviderRegistry
# ---------------------------------------------------------------------------


class TestProviderRegistry:
    def test_register_and_get(self):
        reg = ProviderRegistry()
        name = _uid("reg")
        reg.register(name, lambda: 42, strategy=MissingKeyStrategy.SILENT)
        assert reg.get(name) == 42

    def test_get_unknown_raises(self):
        reg = ProviderRegistry()
        with pytest.raises(KeyError, match="not found"):
            reg.get("nonexistent")

    async def test_aget_unknown_raises(self):
        reg = ProviderRegistry()
        with pytest.raises(KeyError, match="not found"):
            await reg.aget("nonexistent")

    async def test_aget_sync_provider(self):
        reg = ProviderRegistry()
        name = _uid("areg")
        reg.register(name, lambda: 55, strategy=MissingKeyStrategy.SILENT)
        assert await reg.aget(name) == 55

    async def test_aget_async_provider(self):
        reg = ProviderRegistry()
        name = _uid("areg_async")

        async def loader():
            return 88

        reg.register(name, loader, strategy=MissingKeyStrategy.SILENT)
        assert await reg.aget(name) == 88

    def test_is_available(self):
        reg = ProviderRegistry()
        name = _uid("avail")
        reg.register(name, lambda: 1, strategy=MissingKeyStrategy.SILENT)
        assert reg.is_available(name) is True
        assert reg.is_available("nonexistent") is False

    def test_is_initialized(self):
        reg = ProviderRegistry()
        name = _uid("init")
        reg.register(name, lambda: 1, strategy=MissingKeyStrategy.SILENT)
        assert reg.is_initialized(name) is False
        reg.get(name)
        assert reg.is_initialized(name) is True
        assert reg.is_initialized("nonexistent") is False

    def test_re_register_overwrites(self):
        reg = ProviderRegistry()
        name = _uid("reregister")
        reg.register(name, lambda: 1, strategy=MissingKeyStrategy.SILENT)
        reg.register(name, lambda: 2, strategy=MissingKeyStrategy.SILENT)
        assert reg.get(name) == 2


# ---------------------------------------------------------------------------
# ProviderRegistry — dependencies
# ---------------------------------------------------------------------------


class TestProviderRegistryDependencies:
    def test_dependency_initialized_first(self):
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

    def test_cyclic_dependency_raises(self):
        reg = ProviderRegistry()
        a = _uid("a")
        b = _uid("b")

        reg.register(a, lambda: 1, strategy=MissingKeyStrategy.SILENT, dependencies=[b])
        reg.register(b, lambda: 2, strategy=MissingKeyStrategy.SILENT, dependencies=[a])

        with pytest.raises(ConfigurationError, match="Cyclic dependency"):
            reg.get(a)

    async def test_async_dependency_initialized_first(self):
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

        result = await reg.aget(main_name)
        assert result == "main_val"
        assert reg.is_initialized(dep_name)


# ---------------------------------------------------------------------------
# ProviderRegistry — initialize_auto_providers
# ---------------------------------------------------------------------------


class TestInitializeAutoProviders:
    async def test_initializes_auto_providers(self):
        reg = ProviderRegistry()
        name = _uid("auto")

        async def loader():
            return "val"

        reg.register(name, loader, strategy=MissingKeyStrategy.SILENT, auto_initialize=True)
        await reg.initialize_auto_providers()
        assert reg.is_initialized(name)

    async def test_skips_unavailable_non_strict(self):
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
        assert not reg.is_initialized(name)

    async def test_strict_mode_raises_on_unavailable_error_strategy(self):
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
        with pytest.raises(RuntimeError, match="Auto-initialization failed"):
            await reg.initialize_auto_providers(strict=True)

    async def test_strict_mode_raises_on_init_failure(self):
        reg = ProviderRegistry()
        name = _uid("strict_fail")

        async def bad():
            raise RuntimeError("boom")

        reg.register(name, bad, strategy=MissingKeyStrategy.ERROR, auto_initialize=True)
        with pytest.raises(RuntimeError, match="Auto-initialization failed"):
            await reg.initialize_auto_providers(strict=True)

    async def test_no_auto_providers_is_noop(self):
        reg = ProviderRegistry()
        await reg.initialize_auto_providers()  # should not raise

    async def test_strict_mode_does_not_raise_on_non_error_loader_failure(self):
        # Honor strategy: strict aborts on ERROR providers only. A WARN/SILENT
        # provider whose loader raises must degrade (return None), never abort a
        # strict boot — this is what makes strict safe as the blocking-startup mode.
        reg = ProviderRegistry()

        async def bad():
            raise RuntimeError("optional dependency down")

        for strategy in (MissingKeyStrategy.WARN, MissingKeyStrategy.SILENT):
            reg.register(_uid("degrade"), bad, strategy=strategy, auto_initialize=True)

        await reg.initialize_auto_providers(strict=True)  # must not raise


# ---------------------------------------------------------------------------
# LazyLoader — registration-time auto-init does not fake success
# ---------------------------------------------------------------------------


class TestAutoInitDoesNotFakeSuccess:
    @staticmethod
    def _info_messages(mock_log) -> list[str]:
        return [call.args[0] for call in mock_log.info.call_args_list if call.args]

    def test_a_swallowed_sync_failure_is_not_logged_as_initialized(self):
        # The langfuse shape: a SILENT sync auto provider whose loader raises a real
        # bug is swallowed to None. It must not also log "Auto-initialized ... at
        # registration time" — that false success is how a broken provider reads as up.
        def bad_sync():
            raise RuntimeError("name 'threading' is not defined")

        with patch("app.core.lazy_loader.log") as mock_log:
            loader = LazyLoader(
                bad_sync,
                strategy=MissingKeyStrategy.SILENT,
                auto_initialize=True,
                provider_name=_uid("silent_bad"),
            )

        assert loader.is_initialized() is False
        assert not any("Auto-initialized" in m for m in self._info_messages(mock_log))

    def test_a_real_sync_success_still_logs_initialized(self):
        with patch("app.core.lazy_loader.log") as mock_log:
            loader = LazyLoader(
                lambda: "value",
                strategy=MissingKeyStrategy.SILENT,
                auto_initialize=True,
                provider_name=_uid("good"),
            )

        assert loader.is_initialized() is True
        assert any("Auto-initialized" in m for m in self._info_messages(mock_log))


# ---------------------------------------------------------------------------
# ProviderRegistry — warmup_all
# ---------------------------------------------------------------------------


class TestWarmupAll:
    async def test_warmup_all_initializes_available(self):
        reg = ProviderRegistry()
        name = _uid("warm")
        reg.register(name, lambda: 42, strategy=MissingKeyStrategy.SILENT)
        await reg.warmup_all()
        assert reg.is_initialized(name)

    async def test_warmup_all_skips_unavailable(self):
        reg = ProviderRegistry()
        name = _uid("warm_unavail")
        reg.register(
            name,
            lambda: 1,
            required_keys=[None],
            strategy=MissingKeyStrategy.SILENT,
        )
        await reg.warmup_all()
        assert not reg.is_initialized(name)

    async def test_warmup_all_strict_raises_for_unavailable_error(self):
        reg = ProviderRegistry()
        name = _uid("warm_strict")
        reg.register(
            name,
            lambda: 1,
            required_keys=[None],
            strategy=MissingKeyStrategy.ERROR,
        )
        with pytest.raises(RuntimeError, match="warmup failed"):
            await reg.warmup_all(strict=True)

    async def test_warmup_all_strict_raises_on_init_failure(self):
        reg = ProviderRegistry()
        name = _uid("warm_fail")

        async def bad():
            raise RuntimeError("init fail")

        reg.register(name, bad, strategy=MissingKeyStrategy.ERROR)
        with pytest.raises(RuntimeError, match="warmup failed"):
            await reg.warmup_all(strict=True)

    async def test_warmup_all_non_strict_continues_on_failure(self):
        reg = ProviderRegistry()
        good_name = _uid("warm_good")
        bad_name = _uid("warm_bad")

        async def bad():
            raise RuntimeError("fail")

        reg.register(good_name, lambda: 1, strategy=MissingKeyStrategy.SILENT)
        reg.register(bad_name, bad, strategy=MissingKeyStrategy.WARN)

        await reg.warmup_all()  # should not raise
        assert reg.is_initialized(good_name)

    async def test_warmup_empty_registry(self):
        reg = ProviderRegistry()
        await reg.warmup_all()  # noop, should not raise


# ---------------------------------------------------------------------------
# lazy_provider decorator
# ---------------------------------------------------------------------------


class TestLazyProviderDecorator:
    def test_decorator_returns_registrar(self):
        name = _uid("deco")

        @lazy_provider(name=name, strategy=MissingKeyStrategy.SILENT)
        def my_provider():
            return 99

        # my_provider is now a registrar function
        loader = my_provider()
        assert isinstance(loader, LazyLoader)
        assert providers.get(name) == 99

    def test_decorator_async_provider(self):
        name = _uid("deco_async")

        @lazy_provider(name=name, strategy=MissingKeyStrategy.SILENT)
        async def my_async_provider():
            return 77

        loader = my_async_provider()
        assert isinstance(loader, LazyLoader)
        assert loader.is_async

    def test_decorator_with_required_keys(self):
        name = _uid("deco_keys")

        @lazy_provider(
            name=name,
            required_keys=[None],
            strategy=MissingKeyStrategy.SILENT,
        )
        def my_provider():
            return 1

        loader = my_provider()
        assert not loader.is_available()

    def test_decorator_global_context(self):
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
        result = providers.get(name)
        assert result is True
        assert len(configured) == 1


# ---------------------------------------------------------------------------
# MissingKeyStrategy enum
# ---------------------------------------------------------------------------


class TestMissingKeyStrategy:
    def test_values(self):
        assert MissingKeyStrategy.ERROR.value == "error"
        assert MissingKeyStrategy.WARN.value == "warn"
        assert MissingKeyStrategy.WARN_ONCE.value == "warn_once"
        assert MissingKeyStrategy.SILENT.value == "silent"
