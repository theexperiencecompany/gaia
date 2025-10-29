"""Lazy, safe initialization for external providers (clients, globals).

Why
- Avoid importing/connecting providers at startup; defer until first use.

Flow
- Register providers via `providers.register(...)` or `@lazy_provider(...)`.
- Provide `required_keys` (usually env-backed fields from `settings`).
- On first `get()/aget()`, initialize the provider; warn or error if keys are missing.
- Supports async, sync, and global side-effect configuration (e.g., Cloudinary).

Add a new provider
1) Ensure env fields exist in `app.config.settings` (and optionally groups in `config/settings_validator.py`).
2) Create a factory function and decorate with `@lazy_provider(name=..., required_keys=[...])`.
3) Resolve the provider via `providers.get(...)` or `await providers.aget(...)`.
"""

import asyncio
import inspect
from enum import Enum
from threading import Lock
from typing import (
    Any,
    Awaitable,
    Callable,
    Dict,
    Generic,
    List,
    Optional,
    Set,
    TypeVar,
    Union,
    cast,
)

from app.config.loggers import app_logger as logger
from app.utils.exceptions import ConfigurationError

T = TypeVar("T")


class MissingKeyStrategy(Enum):
    """Strategy for handling missing keys"""

    ERROR = "error"  # Raise exception on get() call
    WARN = "warn"  # Log warning on registration and return None on get()
    WARN_ONCE = "warn_once"  # Log warning once on registration and return None on get()
    SILENT = "silent"  # Return None silently on get()


class LazyLoader(Generic[T]):
    """
    Lazy loader that defers provider initialization until first get() access.
    Supports both sync and async loader functions.

    Features:
    - Thread-safe singleton pattern per loader
    - Configurable error handling for missing values
    - Validation caching to avoid repeated checks
    - Flexible warning system at registration time
    - Type safety with generics
    - Support for global context providers (like Cloudinary)
    - Support for both sync and async loader functions
    """

    def __init__(
        self,
        loader_func: Union[Callable[[], T], Callable[[], Awaitable[T]]],
        required_keys: Optional[List[Any]] = None,
        strategy: MissingKeyStrategy = MissingKeyStrategy.ERROR,
        warning_message: Optional[str] = None,
        provider_name: Optional[str] = None,
        validate_values_func: Optional[Callable[[List[Any]], bool]] = None,
        is_global_context: bool = False,
        auto_initialize: bool = False,
        dependencies: Optional[List[str]] = None,
    ):
        """
        Initialize lazy loader.

        Args:
            loader_func: Function that creates the provider instance or configures global context (can be sync or async)
            required_keys: List of direct values that are required (can be None individually)
            strategy: How to handle missing values
            warning_message: Custom warning message
            provider_name: Name for logging/error messages
            validate_values_func: Custom validation function for the values
            is_global_context: If True, provider configures global context instead of returning instance
            auto_initialize: If True, automatically initialize at registration time when values are available
        """
        self.loader_func = loader_func
        self.required_keys = required_keys or []
        self.strategy = strategy
        self.warning_message = warning_message
        self.provider_name = provider_name or loader_func.__name__
        self.validate_values_func = validate_values_func
        self.is_global_context = is_global_context
        self.auto_initialize = auto_initialize
        self.dependencies = dependencies or []

        # Check if the loader function is async
        self.is_async = inspect.iscoroutinefunction(loader_func)

        self._instance: Optional[T] = None
        self._is_configured = False  # For global context providers
        self._lock = Lock()
        self._async_lock = asyncio.Lock() if self.is_async else None
        self._warned_indices: Set[int] = (
            set()
        )  # Track warned value indices for WARN_ONCE

        # Check availability at registration time and log warnings
        self._check_availability_and_warn()

        # Auto-initialize if enabled and values are available
        if self.auto_initialize and self.is_available():
            try:
                if self.is_async:
                    # For async functions, we can't auto-initialize during __init__
                    # Log a message and defer initialization to first get() call
                    logger.info(
                        f"Async provider '{self.provider_name}' will be auto-initialized on first access"
                    )
                else:
                    self._initialize_sync()
                    logger.info(
                        f"Auto-initialized provider '{self.provider_name}' at registration time"
                    )
            except Exception as e:
                if self.strategy == MissingKeyStrategy.ERROR:
                    raise
                else:
                    logger.warning(
                        f"Auto-initialization failed for '{self.provider_name}': {e}"
                    )

    def _check_availability_and_warn(self):
        """Check availability at registration time and log warnings if needed."""
        missing_indices = self._check_required_keys()

        if not missing_indices:
            # All values available
            if self.validate_values_func and not self.validate_values_func(
                self.required_keys
            ):
                # Custom validation failed
                message = f"Value validation failed for provider '{self.provider_name}'"
                if self.strategy in [
                    MissingKeyStrategy.WARN,
                    MissingKeyStrategy.WARN_ONCE,
                ]:
                    self._log_warning(message)
            else:
                if not self.auto_initialize:
                    loader_type = "async" if self.is_async else "sync"
                    logger.info(
                        f"Provider '{self.provider_name}' ({loader_type}) is ready for lazy initialization"
                    )
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
        elif not self.auto_initialize:
            # Only log info about readiness if not auto-initializing
            loader_type = "async" if self.is_async else "sync"
            logger.info(
                f"Provider '{self.provider_name}' ({loader_type}) registered but will initialize on first access"
            )

    def get(self) -> Optional[T]:
        """Get the provider instance synchronously. Only works for sync loader functions."""
        if self.is_async and not self.auto_initialize:
            raise RuntimeError(
                f"Provider '{self.provider_name}' has an async loader function. Use aget() instead."
            )

        # Quick check without lock for already initialized instances
        if self.is_global_context and self._is_configured:
            return True  # type: ignore
        elif not self.is_global_context and self._instance is not None:
            return self._instance

        with self._lock:
            # Double-check locking pattern
            if self.is_global_context and self._is_configured:
                return True  # type: ignore
            elif not self.is_global_context and self._instance is not None:
                return self._instance

            return self._initialize_sync()

    async def aget(self) -> Optional[T]:
        """Get the provider instance asynchronously. Works for both sync and async loader functions."""
        # Quick check without lock for already initialized instances
        if self.is_global_context and self._is_configured:
            return True  # type: ignore
        elif not self.is_global_context and self._instance is not None:
            return self._instance

        if self.is_async:
            if self._async_lock is None:
                raise RuntimeError(
                    f"Async lock not initialized for provider '{self.provider_name}'"
                )
            async with self._async_lock:
                # Double-check locking pattern
                if self.is_global_context and self._is_configured:
                    return True  # type: ignore
                elif not self.is_global_context and self._instance is not None:
                    return self._instance

                return await self._initialize_async()
        else:
            # For sync functions, we can still use async interface
            with self._lock:
                # Double-check locking pattern
                if self.is_global_context and self._is_configured:
                    return True  # type: ignore
                elif not self.is_global_context and self._instance is not None:
                    return self._instance

                return self._initialize_sync()

    def _initialize_sync(self) -> Optional[T]:
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
            if self.is_global_context:
                # For global context providers, call the function for side effects
                self.loader_func()
                self._is_configured = True
                logger.info(
                    f"Successfully configured global provider: {self.provider_name}"
                )
                return True  # type: ignore
            else:
                # For instance-based providers, store and return the instance
                result = self.loader_func()
                if inspect.iscoroutine(result):
                    raise RuntimeError(
                        f"Sync initialization called on async loader function for '{self.provider_name}'"
                    )
                self._instance = cast(T, result)
                logger.info(f"Successfully initialized provider: {self.provider_name}")
                return self._instance

        except Exception as e:
            error_msg = (
                f"Failed to initialize provider '{self.provider_name}': {str(e)}"
            )
            logger.error(error_msg)

            if self.strategy == MissingKeyStrategy.ERROR:
                raise ConfigurationError(error_msg) from e
            else:
                return None

    async def _initialize_async(self) -> Optional[T]:
        """Initialize the provider instance or configure global context asynchronously."""
        # Check if required values are valid
        missing_indices = self._check_required_keys()
        if missing_indices:
            return self._handle_missing_values_on_get(missing_indices)

        # Validate values if custom validator provided
        if self.validate_values_func:
            if not self.validate_values_func(self.required_keys):
                return self._handle_validation_failure_on_get()

        try:
            if self.is_global_context:
                # For global context providers, call the function for side effects
                if self.is_async:
                    result = self.loader_func()
                    if inspect.iscoroutine(result):
                        await result
                    else:
                        raise RuntimeError(
                            f"Expected coroutine from async loader function for '{self.provider_name}'"
                        )
                else:
                    result = self.loader_func()
                    if inspect.iscoroutine(result):
                        raise RuntimeError(
                            f"Unexpected coroutine from sync loader function for '{self.provider_name}'"
                        )
                self._is_configured = True
                logger.info(
                    f"Successfully configured global provider: {self.provider_name}"
                )
                return True  # type: ignore
            else:
                # For instance-based providers, store and return the instance
                if self.is_async:
                    result = self.loader_func()
                    if inspect.iscoroutine(result):
                        self._instance = await result
                    else:
                        raise RuntimeError(
                            f"Expected coroutine from async loader function for '{self.provider_name}'"
                        )
                else:
                    result = self.loader_func()
                    if inspect.iscoroutine(result):
                        raise RuntimeError(
                            f"Unexpected coroutine from sync loader function for '{self.provider_name}'"
                        )
                    self._instance = cast(T, result)
                logger.info(f"Successfully initialized provider: {self.provider_name}")
                return self._instance

        except Exception as e:
            error_msg = (
                f"Failed to initialize provider '{self.provider_name}': {str(e)}"
            )
            logger.error(error_msg)

            if self.strategy == MissingKeyStrategy.ERROR:
                raise ConfigurationError(error_msg) from e
            else:
                return None

    def _check_required_keys(self) -> Set[int]:
        """Check which required values are missing/invalid."""
        missing_indices = set()
        for i, value in enumerate(self.required_keys):
            if self._is_value_missing(value):
                missing_indices.add(i)
        return missing_indices

    def _is_value_missing(self, value: Any) -> bool:
        """Check if a value is considered missing/invalid."""
        if value is None:
            return True
        if isinstance(value, str) and value.strip() == "":
            return True
        return False

    def _handle_missing_values_on_get(self, missing_indices: Set[int]) -> Optional[T]:
        """Handle missing values when get() is called."""
        if self.strategy == MissingKeyStrategy.ERROR:
            indices_str = ", ".join(f"index {i}" for i in missing_indices)
            missing_values = [self.required_keys[i] for i in missing_indices]
            raise ConfigurationError(
                f"Cannot initialize provider '{self.provider_name}' - missing values at {indices_str}: {missing_values}"
            )

        # For non-error strategies, just return None (warning already logged at registration)
        return None

    def _handle_validation_failure_on_get(self) -> Optional[T]:
        """Handle custom validation failure when get() is called."""
        if self.strategy == MissingKeyStrategy.ERROR:
            raise ConfigurationError(
                f"Cannot initialize provider '{self.provider_name}' - value validation failed"
            )

        # For non-error strategies, just return None (warning already logged at registration)
        return None

    def _log_warning(self, message: str):
        """Log warning message."""
        logger.warning(f"[LazyLoader] {message}")

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
        else:
            return self._instance is not None

    def reset(self):
        """Reset the loader (useful for testing)."""
        if self.is_async:
            # For async loaders, we need to handle the async lock
            async def _async_reset():
                if self._async_lock is None:
                    raise RuntimeError(
                        f"Async lock not initialized for provider '{self.provider_name}'"
                    )
                async with self._async_lock:
                    self._instance = None
                    self._is_configured = False

            # If we're in an async context, this should be awaited
            # Otherwise, we'll do our best with sync reset
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # We're in an async context, but we can't await here
                    # Just reset synchronously and hope for the best
                    self._instance = None
                    self._is_configured = False
                else:
                    loop.run_until_complete(_async_reset())
            except RuntimeError:
                # No event loop, just reset synchronously
                self._instance = None
                self._is_configured = False
        else:
            with self._lock:
                self._instance = None
                self._is_configured = False


class ProviderRegistry:
    def _check_cyclic_dependency(self, name: str, visited: Optional[list] = None):
        """Check for cyclic dependencies starting from provider 'name'. Raises ConfigurationError if a cycle is found."""
        if visited is None:
            visited = []
        if name in visited:
            cycle_path = visited + [name]
            raise ConfigurationError(
                f"Cyclic dependency detected: {' -> '.join(cycle_path)}"
            )
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

    def __init__(self):
        self._providers: Dict[str, LazyLoader] = {}
        self._lock = Lock()
        self._auto_init_providers: Set[str] = set()

    def register(
        self,
        name: str,
        loader_func: Union[Callable[[], T], Callable[[], Awaitable[T]]],
        required_keys: Optional[List[Any]] = None,
        strategy: MissingKeyStrategy = MissingKeyStrategy.WARN,
        warning_message: Optional[str] = None,
        validate_values_func: Optional[Callable[[List[Any]], bool]] = None,
        is_global_context: bool = False,
        auto_initialize: bool = False,
        dependencies: Optional[List[str]] = None,
    ) -> LazyLoader[T]:
        """Register a new provider."""
        with self._lock:
            if name in self._providers:
                logger.warning(f"Provider '{name}' is being re-registered")

            provider = LazyLoader(
                loader_func=loader_func,
                required_keys=required_keys,
                strategy=strategy,
                warning_message=warning_message,
                provider_name=name,
                validate_values_func=validate_values_func,
                is_global_context=is_global_context,
                auto_initialize=auto_initialize,
                dependencies=dependencies,
            )

            if auto_initialize:
                self._auto_init_providers.add(name)

            self._providers[name] = provider
            return provider

    async def initialize_auto_providers(self):
        """Initialize all providers marked for auto-initialization concurrently."""

        async def _init_provider(name: str):
            """Initialize a single provider with error handling."""
            try:
                await self.aget(name)
                logger.info(f"Auto-initialized provider '{name}'")
            except Exception as e:
                provider = self._providers[name]
                if provider.strategy == MissingKeyStrategy.ERROR:
                    raise
                else:
                    logger.warning(f"Auto-initialization failed for '{name}': {e}")

        # Create tasks for all auto-init providers
        tasks = [
            _init_provider(name)
            for name in self._auto_init_providers
            if name in self._providers
        ]

        if tasks:
            # Run all initializations concurrently
            await asyncio.gather(*tasks, return_exceptions=True)
            logger.info(f"Completed auto-initialization for {len(tasks)} providers")

    def get(self, name: str) -> Optional[Any]:
        """Get a provider instance by name synchronously - only works for sync providers."""
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

    async def aget(self, name: str) -> Optional[Any]:
        """Get a provider instance by name asynchronously - works for both sync and async providers."""
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

    def get_loader(self, name: str) -> LazyLoader:
        """Get the loader itself (not the instance)."""
        if name not in self._providers:
            raise KeyError(f"Provider '{name}' not found in registry")
        return self._providers[name]

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

    def list_providers(self) -> Dict[str, Dict[str, bool]]:
        """List all providers with their status."""
        return {
            name: {
                "available": loader.is_available(),
                "initialized": loader.is_initialized(),
                "is_global_context": loader.is_global_context,
                "is_async": loader.is_async,
            }
            for name, loader in self._providers.items()
        }


# Global registry instance
providers = ProviderRegistry()


# Decorator for easy provider registration
def lazy_provider(
    name: str,
    required_keys: Optional[List[Any]] = None,
    strategy: MissingKeyStrategy = MissingKeyStrategy.WARN,
    warning_message: Optional[str] = None,
    validate_values_func: Optional[Callable[[List[Any]], bool]] = None,
    is_global_context: bool = False,
    auto_initialize: bool = False,
    dependencies: Optional[List[str]] = None,
):
    """
    Decorator to register a function as a lazy provider.
    Supports both sync and async functions.

    Returns a callable that, when called, registers the provider.
    This allows you to control when registration happens (e.g., in FastAPI lifespan).

    Examples:
        # Sync instance-based provider
        @lazy_provider("gemini", required_keys=[settings.GOOGLE_API_KEY])
        def create_gemini_client():
            return GeminiClient(api_key=settings.GOOGLE_API_KEY)

        # Async instance-based provider
        @lazy_provider("async_db", required_keys=[settings.DATABASE_URL])
        async def create_async_db():
            db = AsyncDatabase(settings.DATABASE_URL)
            await db.connect()
            return db

        # Global context provider (configures global state) with auto-initialization
        @lazy_provider(
            "cloudinary",
            required_keys=[settings.CLOUDINARY_CLOUD_NAME, settings.CLOUDINARY_API_KEY],
            is_global_context=True,
            auto_initialize=True
        )
        def configure_cloudinary():
            import cloudinary
            cloudinary.config(
                cloud_name=settings.CLOUDINARY_CLOUD_NAME,
                api_key=settings.CLOUDINARY_API_KEY,
                api_secret=settings.CLOUDINARY_API_SECRET
            )

        # Async global context provider
        @lazy_provider(
            "async_cache",
            required_keys=[settings.REDIS_URL],
            is_global_context=True,
        )
        async def configure_async_cache():
            import aioredis
            global redis_client
            redis_client = await aioredis.from_url(settings.REDIS_URL)

        # Usage:
        # Sync providers:
        client = providers.get("gemini")

        # Async providers:
        db = await providers.aget("async_db")
        cache_configured = await providers.aget("async_cache")
    """

    def decorator(
        func: Union[Callable[[], T], Callable[[], Awaitable[T]]],
    ) -> Callable[[], LazyLoader[T]]:
        def register_provider() -> LazyLoader[T]:
            return providers.register(
                name=name,
                loader_func=func,
                required_keys=required_keys,
                strategy=strategy,
                warning_message=warning_message,
                validate_values_func=validate_values_func,
                is_global_context=is_global_context,
                auto_initialize=auto_initialize,
                dependencies=dependencies,
            )

        return register_provider

    return decorator
