"""Redis caching decorators with type-safe model support.

Cacheable: key_pattern/key_generator/smart_hash pick how the key is built;
model gives typed serialization via Pydantic; a result that reports itself
degraded is returned but never stored. CacheInvalidator:
key_patterns/key_generator/key clear related entries after a write.
"""

import asyncio
from collections.abc import Awaitable, Callable, Coroutine, Mapping
import functools
import inspect
from typing import ParamSpec, Protocol, TypeVar, cast, overload, runtime_checkable

from app.constants.cache import ONE_YEAR_TTL
from app.constants.log_tags import LogTag
from app.db.redis import delete_cache, get_cache, set_cache
from app.utils.cache_utils import create_cache_key_hash
from shared.py.wide_events import log

P = ParamSpec("P")
R = TypeVar("R")

# A single Callable[P, R] would bind R to the *coroutine* for an already-async
# callee (measured: 105 errors across 45 files), so the overload pair splits
# sync/async cases to keep R the awaited value in both.
_SyncOrAsync = Callable[P, Coroutine[object, object, R]] | Callable[P, R]

# A key generator receives the function's name plus its call args/kwargs and
# returns the cache key, sync or async — matching the two real key generators
# in this codebase (_recall_cache_key and CacheInvalidator's custom-key use).
_KeyGenerator = Callable[..., str] | Callable[..., Coroutine[object, object, str]]

# CacheInvalidator's generator may bust one key or several (e.g. a function
# whose invalidation needs multiple key_patterns but whose signature doesn't
# expose a flat argument per placeholder -- see install_skill).
_InvalidationKeyGenerator = (
    Callable[..., str | list[str]] | Callable[..., Coroutine[object, object, str | list[str]]]
)


@runtime_checkable
class DegradableResult(Protocol):
    """A result that can say it came from a fallback path.

    A degraded result is worse than what the full path returns once its cause
    clears, so caching it would keep serving the fallback long after that.
    """

    degraded: bool


class Cacheable:
    """Caching decorator with three key-generation strategies: smart_hash, key_pattern, or key_generator.

    model swaps TypeAdapter(Any) for TypeAdapter(model), validating and
    typing cached data (works with List[Model], Optional[Model], etc.).
    """

    def __init__(
        self,
        key_pattern: str | None = None,
        key_generator: _KeyGenerator | None = None,
        ttl: int = ONE_YEAR_TTL,
        model: type[object] | None = None,
        smart_hash: bool = False,
        namespace: str = "api",
    ):
        """Initialize the cache decorator.

        key_pattern: a literal without placeholders acts as a static key.
        model: uses TypeAdapter(model) instead of TypeAdapter(Any) for typed
        (de)serialization.
        """
        if not key_pattern and not key_generator and not smart_hash:
            raise ValueError("Either key_pattern, key_generator, or smart_hash must be provided.")
        self.key_pattern = key_pattern
        self.key_generator = key_generator
        self.smart_hash = smart_hash
        self.namespace = namespace
        self.ttl = ttl
        self.model = model

    async def _cache_key(
        self,
        func_name: str,
        func: Callable[P, R],
        args: tuple[object, ...],
        kwargs: Mapping[str, object],
    ) -> str:
        """Resolve the cache key from the configured strategy."""
        if self.smart_hash:
            base_key = create_cache_key_hash(func_name, *args, **kwargs)
            return f"{self.namespace}:{base_key}"
        if self.key_generator:
            # Handle both sync and async key generators
            if asyncio.iscoroutinefunction(self.key_generator):
                return cast(str, await self.key_generator(func_name, *args, **kwargs))
            return cast(str, self.key_generator(func_name, *args, **kwargs))
        if not self.key_pattern:
            raise ValueError("key_pattern must be provided if key_generator is not used.")
        bound_args = inspect.signature(func).bind(*args, **kwargs)
        bound_args.apply_defaults()
        return _pattern_to_key(self.key_pattern, arguments=bound_args.arguments)

    @overload
    def __call__(
        self, func: Callable[P, Coroutine[object, object, R]]
    ) -> Callable[P, Awaitable[R]]: ...

    @overload
    def __call__(self, func: Callable[P, R]) -> Callable[P, Awaitable[R]]: ...

    def __call__(self, func: _SyncOrAsync[P, R]) -> Callable[P, Awaitable[R]]:
        """Wrap func with caching, always returning an async callable."""

        @functools.wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            cache_key = await self._cache_key(func.__name__, func, args, kwargs)

            cached_value = await get_cache(cache_key, self.model)
            if cached_value is not None:
                log.debug(f"{LogTag.API} Cache hit for key", cache_key=cache_key)
                # What went into the cache came out of this same `func`.
                return cast(R, cached_value)

            result: R
            if asyncio.iscoroutinefunction(func):
                result = await func(*args, **kwargs)
            else:
                result = cast(R, func(*args, **kwargs))

            log.debug(f"{LogTag.API} Cache miss for key", cache_key=cache_key)
            if isinstance(result, DegradableResult) and result.degraded:
                log.debug(f"{LogTag.API} Not caching a degraded result", cache_key=cache_key)
                return result
            log.debug(f"{LogTag.API} Setting cache for key", cache_key=cache_key)

            await set_cache(key=cache_key, value=result, ttl=self.ttl, model=self.model)

            return result

        return wrapper


class CacheInvalidator:
    """Clear related cache entries via key_patterns, key_generator, or a static key, before calling func.

    Wildcard patterns are expensive on large Redis instances — prefer specific keys.
    """

    def __init__(
        self,
        key_patterns: list[str] | None = None,
        key_generator: _InvalidationKeyGenerator | None = None,
        key: str | None = None,
    ):
        """Initialize the cache invalidator.

        key_generator may return one key or several to invalidate.
        """
        self.key_patterns = key_patterns
        self.key_generator = key_generator
        self.key = key
        if not key and not key_patterns and not key_generator:
            raise ValueError("Either key, key_patterns, or key_generator must be provided.")

    @overload
    def __call__(
        self, func: Callable[P, Coroutine[object, object, R]]
    ) -> Callable[P, Awaitable[R]]: ...

    @overload
    def __call__(self, func: Callable[P, R]) -> Callable[P, Awaitable[R]]: ...

    def __call__(self, func: _SyncOrAsync[P, R]) -> Callable[P, Awaitable[R]]:
        """Wrap func with cache invalidation, always returning an async callable."""

        @functools.wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            cache_keys: list[str] = []
            if self.key:
                cache_keys = [self.key]
            elif self.key_generator:
                if asyncio.iscoroutinefunction(self.key_generator):
                    generated = await self.key_generator(func.__name__, *args, **kwargs)
                else:
                    generated = self.key_generator(func.__name__, *args, **kwargs)
                cache_keys = generated if isinstance(generated, list) else [generated]
            else:
                if not self.key_patterns:
                    raise ValueError("key_pattern must be provided if key_generator is not used.")

                func_signature = inspect.signature(func)
                bound_args = func_signature.bind(*args, **kwargs)
                bound_args.apply_defaults()

                cache_keys = [
                    _pattern_to_key(pattern, arguments=bound_args.arguments)
                    for pattern in self.key_patterns
                ]

            log.debug(f"{LogTag.API} Cache invalidation for keys", cache_keys=cache_keys)

            await asyncio.gather(*[delete_cache(key) for key in cache_keys])

            if asyncio.iscoroutinefunction(func):
                return cast(R, await func(*args, **kwargs))
            return cast(R, func(*args, **kwargs))

        return wrapper


def _pattern_to_key(pattern: str, arguments: Mapping[str, object]) -> str:
    """Fill a key pattern template's placeholders from bound function arguments.

    Raises:
        ValueError: If pattern contains placeholders not found in arguments.
    """
    try:
        return pattern.format(**arguments)
    except KeyError as e:
        raise ValueError(f"Missing key in pattern: {e}") from e
    except Exception as e:
        raise ValueError(f"Error generating key from pattern: {e}") from e
