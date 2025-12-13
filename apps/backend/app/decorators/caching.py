"""
Redis caching decorators with type-safe model support.

Quick Start:
    # Direct Cacheable usage with smart hashing
    @Cacheable(smart_hash=True, ttl=300)  # 5 minutes
    @Cacheable(smart_hash=True, ttl=1800)  # 30 minutes
    @Cacheable(smart_hash=True, ttl=21600)  # 6 hours

Advanced Usage:
    @Cacheable(key_pattern="user:{user_id}", ttl=3600)
    @Cacheable(key_pattern="user:{user_id}", model=User)  # Type-safe
    @Cacheable(key_generator=custom_key_func, ttl=1800)
    @Cacheable(smart_hash=True, ttl=300, namespace="metrics")  # Custom namespace

Cache Invalidation:
    @CacheInvalidator(key_patterns=["user:{user_id}:*"])

Key Features:
- Smart hash-based key generation
- Pattern-based and custom key generation
- Type-safe caching with Pydantic models
- Automatic cache invalidation
- Custom serialization/deserialization
"""

import asyncio
import functools
import inspect
from typing import Any, Awaitable, Callable, Dict, Generic, List, Optional, TypeVar

from app.config.loggers import redis_logger as logger
from app.db.redis import ONE_YEAR_TTL, delete_cache, get_cache, set_cache
from app.utils.cache_utils import create_cache_key_hash

T = TypeVar("T")


class Cacheable(Generic[T]):
    """
    Advanced caching decorator with full control over key generation and data handling.

    Provides comprehensive caching functionality including:
    - Multiple key generation strategies (pattern, generator, static, smart hash)
    - Type-safe caching with Pydantic model support
    - Custom serialization/deserialization hooks
    - Flexible TTL management

    Key Generation Strategies:
        1. Smart hash: Automatic hash-based keys using function name and arguments
        2. Pattern-based: Use function arguments in template strings
        3. Generator function: Custom logic for complex key generation
        4. Static key: Simple fixed key for singleton data

    Type Safety Options:
        1. model: Pydantic model class for automatic validation and typed instances
           - Replaces TypeAdapter(Any) with TypeAdapter(model) for Redis operations
           - Validates data integrity on cache retrieval
           - More efficient than custom serializer/deserializer lambdas
           - Works with complex types: List[Model], Optional[Model], Dict[str, Model]

        2. deserializer: Custom function for data transformation (applied after model validation)
        3. serializer: Custom function for pre-cache processing (applied before model validation)

    Examples:
        # Smart hash-based caching (replaces cache_short/medium/long)
        @Cacheable(smart_hash=True, ttl=300)  # 5 minutes
        async def get_live_metrics():
            return calculate_current_metrics()
            # Key: "api:get_live_metrics:a1b2c3d4e5f6"

        @Cacheable(smart_hash=True, ttl=1800, namespace="user")  # 30 minutes
        async def get_user_stats(user_id: int):
            return calculate_stats(user_id)
            # Key: "user:get_user_stats:hash_of_args"

        # Pattern-based with type safety
        @Cacheable(key_pattern="user:{user_id}:profile", model=User, ttl=1800)
        async def get_user(user_id: int) -> User:
            return User.from_db(user_id)

        # Custom key generator
        def cache_key(func_name, *args, **kwargs):
            return f"custom:{func_name}:{args[0]}:{datetime.now().hour}"

        @Cacheable(key_generator=cache_key, ttl=3600)
        async def time_sensitive_data(item_id: str):
            return fetch_hourly_data(item_id)

        # With custom serialization
        @Cacheable(
            key_pattern="processed:{data_id}",
            serializer=lambda x: x.to_dict(),
            deserializer=lambda x: CustomObject.from_dict(x),
            ttl=7200
        )
        async def get_processed_data(data_id: str):
            return CustomObject(process_data(data_id))
    """

    def __init__(
        self,
        key_pattern: Optional[str] = None,
        key_generator: Optional[Callable] = None,
        key: Optional[str] = None,
        ttl: int = ONE_YEAR_TTL,
        serializer: Optional[Callable[[T], Any]] = None,
        deserializer: Optional[Callable[[Any], T]] = None,
        model: Optional[type] = None,
        smart_hash: bool = False,
        namespace: str = "api",
        ignore_none: bool = False,
    ):
        """
        Initialize the cache decorator.

        Args:
            key_pattern: Optional string template for the cache key (e.g. "{arg1}:{arg2}")
            key_generator: Optional custom function to generate cache keys
            ttl: Time-to-live for cache entries in seconds. None means no expiration
            key: Optional static key for caching
            serializer: Optional function to serialize the value before caching
            deserializer: Optional function to deserialize the value after retrieving from cache
            model: Optional Pydantic model class for type-specific serialization/deserialization.
                   Uses Pydantic TypeAdapter(model) instead of TypeAdapter(Any) for:
                   - Type-safe serialization: Validates data matches model schema before caching
                   - Type-safe deserialization: Returns properly typed model instances from cache
                   - Data integrity: Raises ValidationError if cached data doesn't match schema
                   - Better performance: Model-specific adapters are more efficient than Any

                   Examples:
                   - model=User: For single User objects
                   - model=List[User]: For lists of User objects
                   - model=Optional[User]: For nullable User objects
                   - model=Dict[str, User]: For user mappings

                   When to use:
                   - Always use for Pydantic model return types
                   - Skip for simple types (dict, str, int, bool, List[str], etc.)
                   - Use with List[Model] for paginated endpoints
            smart_hash: Use automatic hash-based key generation with function name and arguments
            namespace: Namespace prefix for smart hash keys (default: "api")
        """
        self.key_pattern = key_pattern
        self.key_generator = key_generator
        self.key = key
        self.smart_hash = smart_hash
        self.namespace = namespace
        self.ignore_none = ignore_none

        if not key and not key_pattern and not key_generator and not smart_hash:
            raise ValueError(
                "Either key, key_pattern, key_generator, or smart_hash must be provided."
            )
        self.ttl = ttl
        self.serializer = serializer
        self.deserializer = deserializer
        self.model = model

    def __call__(self, func: Callable[..., Any]) -> Callable[..., Awaitable[Any]]:
        """
        Apply the cache decorator to a function.

        Args:
            func: The function to be cached (sync or async)

        Returns:
            Wrapped function with caching behavior (always async)
        """

        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            # Generate the cache key
            if self.key:
                cache_key = self.key
            elif self.smart_hash:
                # Use smart hash-based key generation
                base_key = create_cache_key_hash(func.__name__, *args, **kwargs)
                cache_key = f"{self.namespace}:{base_key}"
            elif self.key_generator:
                # Handle both sync and async key generators
                if asyncio.iscoroutinefunction(self.key_generator):
                    cache_key = await self.key_generator(func.__name__, *args, **kwargs)
                else:
                    cache_key = self.key_generator(func.__name__, *args, **kwargs)
            else:
                if not self.key_pattern:
                    raise ValueError(
                        "key_pattern must be provided if key_generator is not used."
                    )

                func_signature = inspect.signature(func)
                bound_args = func_signature.bind(*args, **kwargs)
                bound_args.apply_defaults()

                cache_key = _pattern_to_key(
                    self.key_pattern, arguments=bound_args.arguments
                )

            # Check if the value is already cached
            cached_value = await get_cache(cache_key, self.model)
            if cached_value is not None:
                logger.debug(f"Cache hit for key: {cache_key}")
                if self.deserializer:
                    cached_value = self.deserializer(cached_value)
                return cached_value

            # Call the original function - handle both sync and async
            if asyncio.iscoroutinefunction(func):
                result = await func(*args, **kwargs)
            else:
                result = func(*args, **kwargs)

            if result is None and self.ignore_none:
                return result

            serialized_result = result
            if self.serializer:
                serialized_result = self.serializer(result)

            logger.debug(f"Cache miss for key: {cache_key}")
            logger.debug(f"Setting cache for key: {cache_key}")

            # Let set_cache handle Pydantic serialization
            await set_cache(
                key=cache_key, value=serialized_result, ttl=self.ttl, model=self.model
            )

            return result

        return wrapper


class CacheInvalidator:
    """
    Decorator for automatic cache invalidation when data changes.

    Automatically clears related cache entries when functions that modify data
    are called. Supports multiple invalidation patterns and custom key generation.

    Use Cases:
        - Clear user cache when profile is updated
        - Invalidate search results when content changes
        - Remove related cached data after bulk operations

    Invalidation Strategies:
        1. Pattern-based: List of key patterns to clear
        2. Generator function: Custom logic for determining keys to clear
        3. Static key: Simple fixed key invalidation

    Examples:
        # Clear specific user cache
        @CacheInvalidator(key_patterns=["user:{user_id}:profile", "user:{user_id}:stats"])
        async def update_user_profile(user_id: int, data: dict):
            return save_user_profile(user_id, data)

        # Pattern-based bulk invalidation (use with caution)
        @CacheInvalidator(key_patterns=["search:*", "categories:*"])
        async def rebuild_search_index():
            return regenerate_search_data()

        # Custom invalidation logic
        def invalidation_keys(func_name, *args, **kwargs):
            user_id = kwargs['user_id']
            team_id = get_user_team(user_id)
            return f"team:{team_id}:members"

        @CacheInvalidator(key_generator=invalidation_keys)
        async def remove_user_from_team(user_id: int, team_id: int):
            return update_team_membership(user_id, team_id)

    Warning:
        Pattern-based invalidation using wildcards (*) can be expensive
        on large Redis instances. Use specific keys when possible.
    """

    def __init__(
        self,
        key_patterns: Optional[List[str]] = None,
        key_generator: Optional[Callable] = None,
        key: Optional[str] = None,
    ):
        """
        Initialize the cache decorator.

        Args:
            key_pattern: Optional string template for the cache key (e.g. "{arg1}:{arg2}")
            key_generator: Optional custom function to generate cache keys
            ttl: Time-to-live for cache entries in seconds. None means no expiration
            key: Optional static key for caching
        """
        self.key_patterns = key_patterns
        self.key_generator = key_generator
        self.key = key
        if not key and not key_patterns and not key_generator:
            raise ValueError(
                "Either key, key_patterns, or key_generator must be provided."
            )

    def __call__(self, func: Callable[..., Any]) -> Callable[..., Awaitable[Any]]:
        """
        Apply the cache invalidator to a function.

        Args:
            func: The function to be invalidated (sync or async)

        Returns:
            Wrapped function with cache invalidation behavior (always async)
        """

        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            # Generate the cache key
            cache_keys: List[str] = []
            if self.key:
                cache_keys = [self.key]
            elif self.key_generator:
                # Handle both sync and async key generators
                if asyncio.iscoroutinefunction(self.key_generator):
                    key = await self.key_generator(func.__name__, *args, **kwargs)
                else:
                    key = self.key_generator(func.__name__, *args, **kwargs)
                cache_keys = [key]
            else:
                if not self.key_patterns:
                    raise ValueError(
                        "key_pattern must be provided if key_generator is not used."
                    )

                func_signature = inspect.signature(func)
                bound_args = func_signature.bind(*args, **kwargs)
                bound_args.apply_defaults()

                # Generate the cache key
                cache_keys = [
                    _pattern_to_key(pattern, arguments=bound_args.arguments)
                    for pattern in self.key_patterns
                ]

            logger.debug(f"Cache invalidation for keys: {cache_keys}")

            # Invalidate the cache
            await asyncio.gather(*[delete_cache(key) for key in cache_keys])

            # Call the original function - handle both sync and async
            if asyncio.iscoroutinefunction(func):
                return await func(*args, **kwargs)
            else:
                return func(*args, **kwargs)

        return wrapper


def _pattern_to_key(pattern: str, arguments: Dict[str, Any]) -> str:
    """
    Convert key pattern template to actual cache key using function arguments.

    Replaces placeholders in pattern strings with actual values from function calls.
    Supports standard Python string formatting with named placeholders.

    Args:
        pattern: Template string with placeholders (e.g., "user:{user_id}:data:{type}")
        arguments: Function arguments dictionary from inspect.signature.bind()

    Returns:
        Formatted cache key string

    Raises:
        ValueError: If pattern contains placeholders not found in arguments

    Examples:
        pattern = "user:{user_id}:profile:{version}"
        arguments = {"user_id": 123, "version": "v2", "extra": "ignored"}
        result = "user:123:profile:v2"

    Note:
        This is an internal utility function used by the Cacheable decorator.
        Arguments must match the pattern placeholders exactly.
    """
    try:
        return pattern.format(**arguments)
    except KeyError as e:
        raise ValueError(f"Missing key in pattern: {e}")
    except Exception as e:
        raise ValueError(f"Error generating key from pattern: {e}")
