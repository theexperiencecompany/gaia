"""Lazy, safe initialization for external providers (clients, globals).

Why
- Avoid importing/connecting providers at startup; defer until first use.

Flow
- Register providers via providers.register(...) or @lazy_provider(...).
- Provide required_keys (usually env-backed fields from settings).
- On first get()/aget(), initialize the provider; warn or error if keys are missing.
- Supports async, sync, and global side-effect configuration (e.g., Cloudinary).

Add a new provider
1) Ensure env fields exist in app.config.settings (and optionally groups in config/settings_validator.py).
2) Create a factory function and decorate with @lazy_provider(name=..., required_keys=[...]).
3) Resolve the provider via providers.get(...) or await providers.aget(...).
"""

import asyncio
from collections.abc import Awaitable, Callable
from enum import Enum
import inspect
from threading import Lock
from typing import (
    Any,
    Generic,
    Protocol,
    TypedDict,
    TypeVar,
    Union,
    Unpack,
    cast,
    overload,
)

from app.constants.log_tags import LogTag
from app.utils.exceptions import ConfigurationError, ProviderNotConfiguredError
from shared.py.wide_events import log

T = TypeVar("T")


class MissingKeyStrategy(Enum):
    """Strategy for handling missing keys."""

    ERROR = "error"  # Raise exception on get() call
    WARN = "warn"  # Log warning on registration and return None on get()
    WARN_ONCE = "warn_once"  # Log warning once on registration and return None on get()
    SILENT = "silent"  # Return None silently on get()


class ProviderOptions(TypedDict, total=False):
    """How a provider is checked and initialized; every key is optional.

    required_keys are already-resolved settings values (API keys, URLs, ints)
    the loader only checks for None/emptiness.
    """

    required_keys: list[object] | None
    strategy: MissingKeyStrategy
    warning_message: str | None
    validate_values_func: Callable[[list[object]], bool] | None
    is_global_context: bool
    auto_initialize: bool
    dependencies: list[str] | None


class LazyLoader(Generic[T]):
    """Defers provider initialization until first get() access.

    Thread-safe singleton per loader; supports sync/async loaders, global-context
    providers (e.g. Cloudinary), and configurable missing-key handling.
    """

    def __init__(
        self,
        loader_func: Union[Callable[[], T], Callable[[], Awaitable[T]]],
        provider_name: str | None = None,
        **options: Unpack[ProviderOptions],
    ) -> None:
        """Initialize the lazy loader; strategy defaults to ERROR."""
        self.loader_func = loader_func
        self.required_keys = options.get("required_keys") or []
        self.strategy = options.get("strategy", MissingKeyStrategy.ERROR)
        self.warning_message = options.get("warning_message")
        self.provider_name = provider_name or loader_func.__name__
        self.validate_values_func = options.get("validate_values_func")
        self.is_global_context = options.get("is_global_context", False)
        self.auto_initialize = options.get("auto_initialize", False)
        self.dependencies = options.get("dependencies") or []

        # Check if the loader function is async
        self.is_async = inspect.iscoroutinefunction(loader_func)

        self._instance: T | None = None
        self._is_configured = False  # For global context providers
        self._lock = Lock()
        self._async_lock = asyncio.Lock() if self.is_async else None
        self._warned_indices: set[int] = set()  # Track warned value indices for WARN_ONCE
        self._warned_not_configured = False  # pragma: no mutate — only read as `not ...`

        # Check availability at registration time and log warnings
        self._check_availability_and_warn()

        # Auto-initialize if enabled and values are available
        if self.auto_initialize and self.is_available():
            try:
                if self.is_async:
                    # For async functions, we can't auto-initialize during __init__
                    # Log a message and defer initialization to first get() call
                    log.info(
                        f"{LogTag.STARTUP} Async provider will be auto-initialized on first access",
                        provider_name=self.provider_name,
                    )
                else:
                    self._initialize_sync()
                    # Only claim success if it actually initialized — a non-ERROR
                    # provider whose loader raised is swallowed to None by
                    # _initialize_sync, which already logged the failure.
                    if self.is_initialized():
                        log.info(
                            f"{LogTag.STARTUP} Auto-initialized provider at registration time",
                            provider_name=self.provider_name,
                        )
            except Exception as e:
                if self.strategy == MissingKeyStrategy.ERROR:
                    raise
                log.warning(
                    f"{LogTag.STARTUP} Auto-initialization failed for",
                    provider_name=self.provider_name,
                    error=str(e),
                    error_type=type(e).__name__,
                )

    def _check_availability_and_warn(self) -> None:
        """Check availability at registration time and log warnings if needed."""
        missing_indices = self._check_required_keys()

        if not missing_indices:
            # All values available
            if self.validate_values_func and not self.validate_values_func(self.required_keys):
                # Custom validation failed
                message = f"Value validation failed for provider '{self.provider_name}'"
                if self.strategy in [
                    MissingKeyStrategy.WARN,
                    MissingKeyStrategy.WARN_ONCE,
                ]:
                    self._log_warning(message)
            return

        # Missing values found - handle according to strategy
        if self.strategy == MissingKeyStrategy.SILENT:
            # Don't log anything
            return

        indices_str = ", ".join(f"index {i}" for i in missing_indices)
        missing_values = [self.required_keys[i] for i in missing_indices]

        message = (
            self.warning_message
            or f"Provider '{self.provider_name}' missing required values at {indices_str}: {missing_values}"
        )

        if self.strategy in [MissingKeyStrategy.WARN, MissingKeyStrategy.WARN_ONCE]:
            self._log_warning(f"Registration warning: {message}")
            if self.strategy == MissingKeyStrategy.WARN_ONCE:
                self._warned_indices.update(missing_indices)

    def get(self) -> Union[T, bool] | None:
        """Get the provider instance synchronously. Only works for sync loader functions."""
        if self.is_async and not self.auto_initialize:
            raise RuntimeError(
                f"Provider '{self.provider_name}' has an async loader function. Use aget() instead."
            )

        # Quick check without lock for already initialized instances
        if self.is_global_context and self._is_configured:
            return True
        if not self.is_global_context and self._instance is not None:
            return self._instance

        with self._lock:
            # Double-check locking pattern
            if self.is_global_context and self._is_configured:
                return True
            if not self.is_global_context and self._instance is not None:
                return self._instance

            return self._initialize_sync()

    async def aget(self) -> Union[T, bool] | None:
        """Get the provider instance asynchronously. Works for both sync and async loader functions."""
        # Quick check without lock for already initialized instances
        if self.is_global_context and self._is_configured:
            return True
        if not self.is_global_context and self._instance is not None:
            return self._instance

        if self.is_async:
            if self._async_lock is None:
                raise RuntimeError(
                    f"Async lock not initialized for provider '{self.provider_name}'"
                )
            async with self._async_lock:
                # Double-check locking pattern
                if self.is_global_context and self._is_configured:
                    return True
                if not self.is_global_context and self._instance is not None:
                    return self._instance

                return await self._initialize_async()
        else:
            # For sync functions, we can still use async interface
            with self._lock:
                # Double-check locking pattern
                if self.is_global_context and self._is_configured:
                    return True
                if not self.is_global_context and self._instance is not None:
                    return self._instance

                return self._initialize_sync()

    def _initialize_sync(self) -> Union[T, bool] | None:
        """Initialize the provider instance or configure global context synchronously."""
        if self.is_async:
            raise RuntimeError(
                f"Cannot synchronously initialize async provider '{self.provider_name}'"
            )

        # Check if required values are valid
        missing_indices = self._check_required_keys()
        if missing_indices:
            return self._handle_missing_values_on_get(missing_indices)

        # Validate values if custom validator provided
        if self.validate_values_func:
            if not self.validate_values_func(self.required_keys):
                return self._handle_validation_failure_on_get()

        try:
            result = self.loader_func()
            # A global provider is called for its side effects; its result is unused.
            if not self.is_global_context and inspect.iscoroutine(result):
                raise RuntimeError(
                    f"Sync initialization called on async loader function for '{self.provider_name}'"
                )
            return self._store_loaded(result)

        except ProviderNotConfiguredError as e:
            self._handle_not_configured(e)
            return None
        except Exception as e:
            error_msg = f"Failed to initialize provider '{self.provider_name}': {e!s}"
            log.error(
                f"{LogTag.STARTUP} Failed to initialize provider",
                provider_name=self.provider_name,
                error_type=type(e).__name__,
                error=str(e),
            )

            if self.strategy == MissingKeyStrategy.ERROR:
                raise ConfigurationError(error_msg) from e
            return None

    async def _initialize_async(self) -> Union[T, bool] | None:
        """Initialize an async provider instance or configure its global context."""
        # Check if required values are valid
        missing_indices = self._check_required_keys()
        if missing_indices:
            return self._handle_missing_values_on_get(missing_indices)

        # Validate values if custom validator provided
        if self.validate_values_func:
            if not self.validate_values_func(self.required_keys):
                return self._handle_validation_failure_on_get()

        try:
            result = self.loader_func()
            if not inspect.iscoroutine(result):
                raise RuntimeError(
                    f"Expected coroutine from async loader function for '{self.provider_name}'"
                )
            return self._store_loaded(await result)

        except ProviderNotConfiguredError as e:
            self._handle_not_configured(e)
            return None
        except Exception as e:
            error_msg = f"Failed to initialize provider '{self.provider_name}': {e!s}"
            log.error(
                f"{LogTag.STARTUP} Failed to initialize provider",
                provider_name=self.provider_name,
                error_type=type(e).__name__,
                error=str(e),
            )

            if self.strategy == MissingKeyStrategy.ERROR:
                raise ConfigurationError(error_msg) from e
            return None

    def _store_loaded(self, result: object) -> Union[T, bool]:
        """Record a successful load: a global provider is configured, any other keeps its instance."""
        if self.is_global_context:
            self._is_configured = True
            log.info(
                f"{LogTag.STARTUP} Successfully configured global provider",
                provider_name=self.provider_name,
            )
            return True
        self._instance = cast(T, result)
        log.info(
            f"{LogTag.STARTUP} Successfully initialized provider",
            provider_name=self.provider_name,
        )
        return self._instance

    def _check_required_keys(self) -> set[int]:
        """Check which required values are missing/invalid."""
        missing_indices = set()
        for i, value in enumerate(self.required_keys):
            if self._is_value_missing(value):
                missing_indices.add(i)
        return missing_indices

    def _is_value_missing(self, value: object) -> bool:
        """Check if a value is considered missing/invalid."""
        return value is None or (isinstance(value, str) and value.strip() == "")

    def _handle_missing_values_on_get(self, missing_indices: set[int]) -> Union[T, bool] | None:
        """Handle missing values when get() is called."""
        if self.strategy == MissingKeyStrategy.ERROR:
            indices_str = ", ".join(f"index {i}" for i in missing_indices)
            missing_values = [self.required_keys[i] for i in missing_indices]
            raise ConfigurationError(
                f"Cannot initialize provider '{self.provider_name}' - missing values at {indices_str}: {missing_values}"
            )

        # For non-error strategies, just return None (warning already logged at registration)
        return None

    def _handle_not_configured(self, error: ProviderNotConfiguredError) -> None:
        """Warn once for an optional provider with no credentials; raise for a required one."""
        if self.strategy == MissingKeyStrategy.ERROR:
            raise ConfigurationError(
                f"Provider '{self.provider_name}' is not configured: {error.message}"
            ) from error
        if self.strategy != MissingKeyStrategy.SILENT and not self._warned_not_configured:
            self._warned_not_configured = True
            log.warning(
                f"{LogTag.STARTUP} Provider not configured",
                provider_name=self.provider_name,
                reason=self.warning_message or error.message,
            )

    def _handle_validation_failure_on_get(self) -> Union[T, bool] | None:
        """Handle custom validation failure when get() is called."""
        if self.strategy == MissingKeyStrategy.ERROR:
            raise ConfigurationError(
                f"Cannot initialize provider '{self.provider_name}' - value validation failed"
            )

        # For non-error strategies, just return None (warning already logged at registration)
        return None

    def _log_warning(self, message: str) -> None:
        """Log warning message."""
        log.warning(f"{LogTag.STARTUP} [LazyLoader]", reason=message)

    def is_available(self) -> bool:
        """Check if the provider is available without initializing it."""
        missing_indices = self._check_required_keys()
        if missing_indices:
            return False

        # If custom validator exists, check it too
        if self.validate_values_func:
            return self.validate_values_func(self.required_keys)

        return True

    def is_initialized(self) -> bool:
        """Check if the provider is already initialized."""
        if self.is_global_context:
            return self._is_configured
        return self._instance is not None

    async def areset(self) -> None:
        """Awaitable reset that takes the async lock, so it cannot race aget().

        The async initializer holds _async_lock while loader_func runs;
        clearing the fields without that lock lets an in-flight initialization
        repopulate the instance after the reset, silently undoing it. Await this
        whenever a loop is already running.
        """
        if self._async_lock is None:
            raise RuntimeError(f"Async lock not initialized for provider '{self.provider_name}'")
        async with self._async_lock:
            self._instance = None
            self._is_configured = False

    def reset(self) -> None:
        """Reset the loader (useful for testing)."""
        if self.is_async:
            # get_running_loop() succeeds only inside a running loop, where a
            # sync clear races any in-flight aget() and could be silently
            # overwritten. Fail loud and require the awaited API instead.
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                asyncio.run(self.areset())
            else:
                raise RuntimeError(
                    f"reset() for async provider '{self.provider_name}' called inside a "
                    "running event loop, where it could be overwritten by an in-flight "
                    "initialization — await areset() instead, which takes the async lock"
                )
        else:
            with self._lock:
                self._instance = None
                self._is_configured = False


class ProviderRegistry:
    def _check_cyclic_dependency(self, name: str, visited: list[str] | None = None) -> None:
        """Check for cyclic dependencies starting from provider 'name'. Raises ConfigurationError if a cycle is found."""
        if visited is None:
            visited = []
        if name in visited:
            cycle_path = visited + [name]
            raise ConfigurationError(f"Cyclic dependency detected: {' -> '.join(cycle_path)}")
        visited.append(name)
        loader = self._providers.get(name)
        if loader:
            for dep in loader.dependencies:
                self._check_cyclic_dependency(dep, visited.copy())

    """
    Registry for managing multiple lazy-loaded providers.
    Provides a centralized way to configure and access providers.
    Supports both sync and async providers.
    """

    def __init__(self) -> None:
        self._providers: dict[str, LazyLoader[Any]] = {}
        self._lock = Lock()
        self._auto_init_providers: set[str] = set()

    def register(
        self,
        name: str,
        loader_func: Union[Callable[[], T], Callable[[], Awaitable[T]]],
        **options: Unpack[ProviderOptions],
    ) -> LazyLoader[T]:
        """Register a new provider; strategy defaults to WARN."""
        options.setdefault("strategy", MissingKeyStrategy.WARN)
        with self._lock:
            if name in self._providers:
                log.warning(f"{LogTag.STARTUP} Provider is being re-registered", name=name)

            provider = LazyLoader(loader_func=loader_func, provider_name=name, **options)

            if provider.auto_initialize:
                self._auto_init_providers.add(name)

            self._providers[name] = provider
            return provider

    async def initialize_auto_providers(
        self,
        *,
        concurrency: int = 5,
        strict: bool = False,
    ) -> None:
        """Initialize all providers marked for auto-initialization.

        Unavailable providers are skipped; in strict mode, any failure (or
        unavailable ERROR-strategy provider) raises after all tasks complete.
        """

        semaphore = asyncio.Semaphore(max(1, concurrency))
        errors: list[tuple[str, Exception]] = []

        async def _init_provider(name: str) -> None:
            async with semaphore:
                try:
                    provider = self._providers.get(name)
                    if provider and not provider.is_available():
                        if strict and provider.strategy == MissingKeyStrategy.ERROR:
                            raise ConfigurationError(
                                f"Provider '{name}' is not available for auto-initialization"
                            )
                        return

                    await self.aget(name)
                    # aget returns None (no raise) for a WARN/SILENT provider that is
                    # unavailable or whose loader failed — don't log success for those.
                    if provider is not None and provider.is_initialized():
                        log.info(f"{LogTag.STARTUP} Auto-initialized provider", name=name)
                except asyncio.CancelledError:
                    # Propagate cancellation so shutdown can stop warmup promptly.
                    raise
                except Exception as e:
                    errors.append((name, e))
                    provider = self._providers.get(name)
                    provider_strategy = provider.strategy if provider else MissingKeyStrategy.WARN
                    if provider_strategy == MissingKeyStrategy.ERROR:
                        log.error(
                            f"{LogTag.STARTUP} Auto-initialization failed for",
                            name=name,
                            error=str(e),
                            error_type=type(e).__name__,
                        )
                    else:
                        log.warning(
                            f"{LogTag.STARTUP} Auto-initialization failed for",
                            name=name,
                            error=str(e),
                            error_type=type(e).__name__,
                        )

        with self._lock:
            names = [name for name in self._auto_init_providers if name in self._providers]
        if not names:
            return

        await asyncio.gather(*[_init_provider(name) for name in names])
        log.info(
            f"{LogTag.STARTUP} Completed auto-initialization for providers", names_count=len(names)
        )

        if strict and errors:
            failed = ", ".join(name for name, _ in errors)
            raise RuntimeError(f"Auto-initialization failed for: {failed}")

    async def warmup_all(
        self,
        *,
        concurrency: int = 5,
        strict: bool = False,
    ) -> None:
        """Warm up (initialize) all registered providers, for background warmup in production.

        Uses aget(), so a concurrent request for the same provider waits on its
        lock instead of double-initializing. Unavailable providers are skipped.
        """

        semaphore = asyncio.Semaphore(max(1, concurrency))
        errors: list[tuple[str, Exception]] = []

        with self._lock:
            snapshot = list(self._providers.items())

        warmup_names: list[str] = []
        skipped_unavailable = 0
        for name, loader in snapshot:
            if loader.is_available():
                warmup_names.append(name)
            else:
                skipped_unavailable += 1
                if strict and loader.strategy == MissingKeyStrategy.ERROR:
                    errors.append(
                        (
                            name,
                            ConfigurationError(f"Provider '{name}' is not available for warmup"),
                        )
                    )

        async def _warm(name: str) -> None:
            async with semaphore:
                try:
                    await self.aget(name)
                except asyncio.CancelledError:
                    # Propagate cancellation so shutdown can stop warmup promptly.
                    raise
                except Exception as e:
                    errors.append((name, e))
                    log.error(
                        f"{LogTag.STARTUP} Provider warmup failed for",
                        name=name,
                        error=str(e),
                        error_type=type(e).__name__,
                    )

        if not warmup_names:
            if strict and errors:
                failed = ", ".join(name for name, _ in errors)
                raise RuntimeError(f"Provider warmup failed for: {failed}")
            return

        await asyncio.gather(*[_warm(name) for name in warmup_names])

        if errors:
            log.warning(
                f"{LogTag.STARTUP} Provider warmup completed with errors ( unavailable providers skipped)",
                errors_count=len(errors),
                skipped_unavailable=skipped_unavailable,
            )
        else:
            log.info(
                f"{LogTag.STARTUP} Provider warmup completed for providers ( unavailable providers skipped)",
                warmup_names_count=len(warmup_names),
                skipped_unavailable=skipped_unavailable,
            )

        if strict and errors:
            failed = ", ".join(name for name, _ in errors)
            raise RuntimeError(f"Provider warmup failed for: {failed}")

    def get(self, name: str) -> Any | None:  # noqa: ANN401 -- framework contract
        """Get a provider instance by name synchronously - only works for sync providers.

        Returns Any because the registry is keyed by name, not by type: the
        concrete provider type is only knowable at the call site. Callers narrow
        with cast(TheProvider, ...) rather than isinstance (Type Safety
        item 12) — the registered value is correct by construction.
        """
        if name not in self._providers:
            raise KeyError(f"Provider '{name}' not found in registry")
        self._check_cyclic_dependency(name)
        loader = self._providers[name]
        for dep in loader.dependencies:
            if dep in self._providers:
                dep_loader = self._providers[dep]
                # Skip if dependency is auto-initialized and already initialized
                if dep in self._auto_init_providers and dep_loader.is_initialized():
                    continue
                if not dep_loader.is_initialized():
                    self.get(dep)
        return loader.get()

    async def aget(self, name: str) -> Any | None:  # noqa: ANN401 -- framework contract
        """Get a provider instance by name asynchronously - works for both sync and async providers.

        Returns Any for the same reason as get(); narrow with cast.
        """
        if name not in self._providers:
            raise KeyError(f"Provider '{name}' not found in registry")
        self._check_cyclic_dependency(name)
        loader = self._providers[name]
        for dep in loader.dependencies:
            if dep in self._providers:
                dep_loader = self._providers[dep]
                # Skip if dependency is auto-initialized and already initialized
                if dep in self._auto_init_providers and dep_loader.is_initialized():
                    continue
                if not dep_loader.is_initialized():
                    if dep_loader.is_async:
                        await self.aget(dep)
                    else:
                        self.get(dep)
        return await loader.aget()

    def is_available(self, name: str) -> bool:
        """Check if a provider is available."""
        if name not in self._providers:
            return False
        return self._providers[name].is_available()

    def is_initialized(self, name: str) -> bool:
        """Check if a provider is already initialized."""
        if name not in self._providers:
            return False
        return self._providers[name].is_initialized()

    def reset(self, name: str) -> None:
        """Reset a provider so the next aget()/get() re-initializes it from scratch.

        Testing only: a disposed process-lifetime resource (e.g. an asyncpg
        engine) would otherwise be handed back already-closed to a later test.
        Inside a running event loop use areset() instead, to avoid an
        in-flight init overwriting it.
        """
        if name in self._providers:
            self._providers[name].reset()

    async def areset(self, name: str) -> None:
        """Awaited variant of reset() — safe inside a running event loop."""
        if name in self._providers:
            await self._providers[name].areset()


# Global registry instance
providers = ProviderRegistry()


class _ProviderDecorator(Protocol):
    """What lazy_provider(...) hands back — a decorator that keeps T.

    A Protocol with an overloaded __call__ rather than a plain
    Callable[...] return: a two-step decorator factory has nothing to solve
    T against at the *outer* call, so a plain annotation collapses every
    decorated provider to LazyLoader[Any] (Type Safety item 9). Deferring
    inference to __call__ recovers the provider's real type. The overloads
    (async first — a coroutine function also matches the sync form, with
    T bound to the coroutine) are what makes async def factories infer;
    a single union parameter leaves mypy solving T to Never.
    """

    @overload
    def __call__(self, func: Callable[[], Awaitable[T]]) -> Callable[[], LazyLoader[T]]: ...

    @overload
    def __call__(self, func: Callable[[], T]) -> Callable[[], LazyLoader[T]]: ...


# Decorator for easy provider registration
def lazy_provider(name: str, **options: Unpack[ProviderOptions]) -> _ProviderDecorator:
    """Decorate a function to register it as a lazy provider (sync or async).

    Returns a callable that performs the registration when called, so callers
    control when that happens (e.g. during FastAPI lifespan).
    """

    def decorator(
        func: Union[Callable[[], T], Callable[[], Awaitable[T]]],
    ) -> Callable[[], LazyLoader[T]]:
        def register_provider() -> LazyLoader[T]:
            return providers.register(name=name, loader_func=func, **options)

        return register_provider

    return decorator
