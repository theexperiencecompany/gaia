"""Unit tests for the Redis caching decorators (app/decorators/caching.py)."""

import re
from typing import Any
from unittest.mock import AsyncMock, patch

from pydantic import BaseModel
import pytest

from app.decorators.caching import Cacheable, CacheInvalidator, _pattern_to_key
from app.utils.cache_utils import create_cache_key_hash

pytestmark = pytest.mark.unit


class TestPatternToKeyErrors:
    async def test_missing_placeholder_raises_with_exact_message_and_cause(self):
        with pytest.raises(ValueError) as exc_info:
            _pattern_to_key("user:{user_id}:profile", arguments={"other": 1})

        assert str(exc_info.value) == "Missing key in pattern: 'user_id'"
        assert isinstance(exc_info.value.__cause__, KeyError)
        assert exc_info.value.__cause__.args == ("user_id",)

    async def test_format_failure_raises_with_exact_message_and_cause(self):
        class BadFormat:
            def __format__(self, format_spec: str) -> str:
                raise RuntimeError("boom")

        with pytest.raises(ValueError) as exc_info:
            _pattern_to_key("value:{val}", arguments={"val": BadFormat()})

        assert str(exc_info.value) == "Error generating key from pattern: boom"
        assert isinstance(exc_info.value.__cause__, RuntimeError)
        assert str(exc_info.value.__cause__) == "boom"


class TestPatternToKeyFormatting:
    def test_multiple_placeholders_are_filled_in_order_and_extra_args_ignored(self):
        assert (
            _pattern_to_key(
                "user:{user_id}:data:{type}",
                arguments={"user_id": 123, "type": "summary", "extra": "ignored"},
            )
            == "user:123:data:summary"
        )

    def test_literal_pattern_without_placeholders_is_returned_verbatim(self):
        assert _pattern_to_key("static:key:v2", arguments={}) == "static:key:v2"


class TestCacheableSmartHash:
    async def test_smart_hash_key_is_namespace_function_and_full_sha256(self):
        @Cacheable(smart_hash=True, ttl=300)
        async def get_live_metrics() -> str:
            return "value"

        with (
            patch(
                "app.decorators.caching.get_cache", new_callable=AsyncMock, return_value=None
            ) as mock_get,
            patch("app.decorators.caching.set_cache", new_callable=AsyncMock),
        ):
            await get_live_metrics()

        cache_key = mock_get.await_args.args[0]
        # The key is namespace + function name + full sha256 over the args.
        assert re.fullmatch(r"api:get_live_metrics:[0-9a-f]{64}", cache_key)

    async def test_smart_hash_covers_positional_and_keyword_args_exactly(self):
        @Cacheable(smart_hash=True, ttl=300)
        async def fetch(item_id: str, limit: int = 5) -> str:
            return "value"

        with (
            patch(
                "app.decorators.caching.get_cache", new_callable=AsyncMock, return_value=None
            ) as mock_get,
            patch("app.decorators.caching.set_cache", new_callable=AsyncMock),
        ):
            await fetch("item-1", limit=7)

        expected = f"api:{create_cache_key_hash('fetch', 'item-1', limit=7)}"
        assert mock_get.await_args.args[0] == expected


class TestCacheableKeyPattern:
    async def test_pattern_resolves_against_bound_args_including_defaults(self):
        @Cacheable(key_pattern="user:{user_id}:profile:{version}", ttl=60)
        async def get_user(user_id: int, version: str = "v1") -> str:
            return "fresh"

        with (
            patch(
                "app.decorators.caching.get_cache", new_callable=AsyncMock, return_value=None
            ) as mock_get,
            patch("app.decorators.caching.set_cache", new_callable=AsyncMock),
        ):
            result = await get_user(7)

        assert mock_get.await_args.args[0] == "user:7:profile:v1"
        assert result == "fresh"

    async def test_kwargs_bind_by_name_into_the_pattern(self):
        @Cacheable(key_pattern="search:{query}:page:{page}", ttl=30)
        async def search(query: str, page: int = 0) -> str:
            return "results"

        with (
            patch(
                "app.decorators.caching.get_cache", new_callable=AsyncMock, return_value=None
            ) as mock_get,
            patch("app.decorators.caching.set_cache", new_callable=AsyncMock),
        ):
            await search("weather", page=3)

        assert mock_get.await_args.args[0] == "search:weather:page:3"


class TestCacheableHitMissFlow:
    async def test_cache_hit_returns_cached_value_without_calling_the_function(self):
        calls: list[Any] = []

        @Cacheable(key_pattern="static-key", ttl=120)
        async def compute(value: str) -> str:
            calls.append(value)
            return "computed"

        with (
            patch(
                "app.decorators.caching.get_cache",
                new_callable=AsyncMock,
                return_value="cached",
            ) as mock_get,
            patch("app.decorators.caching.set_cache", new_callable=AsyncMock) as mock_set,
        ):
            result = await compute("input")

        assert mock_get.await_args.args[0] == "static-key"
        assert result == "cached"
        assert calls == []
        mock_set.assert_not_called()

    async def test_cache_miss_calls_the_function_then_stores_with_ttl(self):
        calls: list[str] = []

        @Cacheable(key_pattern="static-key", ttl=120)
        async def compute(value: str) -> str:
            calls.append(value)
            return "computed"

        with (
            patch("app.decorators.caching.get_cache", new_callable=AsyncMock, return_value=None),
            patch("app.decorators.caching.set_cache", new_callable=AsyncMock) as mock_set,
        ):
            result = await compute("input")

        assert result == "computed"
        assert calls == ["input"]
        mock_set.assert_awaited_once_with(key="static-key", value="computed", ttl=120, model=None)

    async def test_sync_function_is_cached_through_the_same_async_wrapper(self):
        calls: list[str] = []

        @Cacheable(key_pattern="sync-key", ttl=10)
        def compute_sync(value: str) -> str:
            calls.append(value)
            return "sync-result"

        with (
            patch("app.decorators.caching.get_cache", new_callable=AsyncMock, return_value=None),
            patch("app.decorators.caching.set_cache", new_callable=AsyncMock),
        ):
            result = await compute_sync("x")

        assert result == "sync-result"
        assert calls == ["x"]


class TestCacheableValidation:
    def test_no_key_strategy_raises_at_construction(self):
        with pytest.raises(
            ValueError,
            match=r"^Either key_pattern, key_generator, or smart_hash must be provided\.$",
        ):
            Cacheable()


class TestCacheableKeyGeneratorArgs:
    """The generator is called with (func_name, *args, **kwargs) — every part
    load-bearing, since two call sites share the helper."""

    async def test_sync_generator_receives_func_name_args_and_kwargs(self):
        seen: dict[str, Any] = {}

        def key_gen(func_name: str, *args: Any, **kwargs: Any) -> str:
            seen["call"] = (func_name, args, kwargs)
            return f"gen:{func_name}:{args[0]}:{kwargs['page']}"

        @Cacheable(key_generator=key_gen, ttl=60)
        async def fetch(item_id: str, page: int = 0) -> str:
            return "fresh"

        with (
            patch(
                "app.decorators.caching.get_cache", new_callable=AsyncMock, return_value=None
            ) as mock_get,
            patch("app.decorators.caching.set_cache", new_callable=AsyncMock),
        ):
            await fetch("item-1", page=2)

        assert seen["call"] == ("fetch", ("item-1",), {"page": 2})
        assert mock_get.await_args.args[0] == "gen:fetch:item-1:2"

    async def test_async_generator_receives_func_name_args_and_kwargs(self):
        seen: dict[str, Any] = {}

        async def key_gen(func_name: str, *args: Any, **kwargs: Any) -> str:
            seen["call"] = (func_name, args, kwargs)
            return f"agen:{func_name}:{args[0]}:{kwargs['page']}"

        @Cacheable(key_generator=key_gen, ttl=60)
        async def fetch(item_id: str, page: int = 0) -> str:
            return "fresh"

        with (
            patch(
                "app.decorators.caching.get_cache", new_callable=AsyncMock, return_value=None
            ) as mock_get,
            patch("app.decorators.caching.set_cache", new_callable=AsyncMock),
        ):
            await fetch("item-1", page=3)

        assert seen["call"] == ("fetch", ("item-1",), {"page": 3})
        assert mock_get.await_args.args[0] == "agen:fetch:item-1:3"


class TestCacheableModelSerialization:
    async def test_a_miss_stores_through_the_configured_model(self):
        class CachedUser(BaseModel):
            name: str

        @Cacheable(key_pattern="u:{user_id}", ttl=60, model=CachedUser)
        async def get_user(user_id: int) -> CachedUser:
            return CachedUser(name="n")

        with (
            patch(
                "app.decorators.caching.get_cache", new_callable=AsyncMock, return_value=None
            ) as mock_get,
            patch("app.decorators.caching.set_cache", new_callable=AsyncMock) as mock_set,
        ):
            result = await get_user(1)

        assert result == CachedUser(name="n")
        assert mock_get.await_args.args[1] is CachedUser
        mock_set.assert_awaited_once()
        assert mock_set.await_args.kwargs["model"] is CachedUser


class TestCacheableKeyGenerator:
    async def test_a_sync_key_generators_return_becomes_the_cache_key(self):
        @Cacheable(key_generator=lambda func_name, *args, **kwargs: f"gen:{args[0]}", ttl=60)
        async def fetch(item_id: str) -> str:
            return "fresh"

        with (
            patch(
                "app.decorators.caching.get_cache", new_callable=AsyncMock, return_value=None
            ) as mock_get,
            patch("app.decorators.caching.set_cache", new_callable=AsyncMock),
        ):
            assert await fetch("item-1") == "fresh"

        assert mock_get.await_args.args[0] == "gen:item-1"

    async def test_an_async_key_generator_is_awaited(self):
        async def key_gen(func_name: str, *args: Any, **kwargs: Any) -> str:
            return f"agen:{args[0]}"

        @Cacheable(key_generator=key_gen, ttl=60)
        async def fetch(item_id: str) -> str:
            return "fresh"

        with (
            patch(
                "app.decorators.caching.get_cache", new_callable=AsyncMock, return_value=None
            ) as mock_get,
            patch("app.decorators.caching.set_cache", new_callable=AsyncMock),
        ):
            await fetch("item-1")

        assert mock_get.await_args.args[0] == "agen:item-1"


class TestCacheableUnresolvedKeyGuard:
    async def test_no_resolvable_strategy_at_call_time_raises(self):
        cacheable = Cacheable(smart_hash=True)
        cacheable.smart_hash = False

        with pytest.raises(
            ValueError, match=r"^key_pattern must be provided if key_generator is not used\.$"
        ):
            await cacheable._cache_key("func_name", lambda: None, (), {})


class TestCacheInvalidatorKeyGeneratorArgs:
    """Both generator flavours receive (func.__name__, *args, **kwargs) and
    their return decides exactly which keys get busted."""

    async def test_async_generator_receives_func_name_args_and_kwargs(self):
        seen: dict[str, Any] = {}

        async def key_gen(func_name: str, *args: Any, **kwargs: Any) -> str:
            seen["call"] = (func_name, args, kwargs)
            return f"bust:{func_name}:{args[0]}:{kwargs['page']}"

        @CacheInvalidator(key_generator=key_gen)
        async def mutate(item_id: str, page: int = 0) -> str:
            return "done"

        with patch("app.decorators.caching.delete_cache", new_callable=AsyncMock) as mock_delete:
            assert await mutate("x", page=2) == "done"

        assert seen["call"] == ("mutate", ("x",), {"page": 2})
        assert [c.args[0] for c in mock_delete.await_args_list] == ["bust:mutate:x:2"]

    async def test_sync_generator_receives_func_name_args_and_kwargs(self):
        seen: dict[str, Any] = {}

        def key_gen(func_name: str, *args: Any, **kwargs: Any) -> list[str]:
            seen["call"] = (func_name, args, kwargs)
            return [f"bust:{func_name}:{kwargs['page']}", f"extra:{args[0]}"]

        @CacheInvalidator(key_generator=key_gen)
        async def mutate(item_id: str, page: int = 0) -> str:
            return "done"

        with patch("app.decorators.caching.delete_cache", new_callable=AsyncMock) as mock_delete:
            assert await mutate("y", page=4) == "done"

        assert seen["call"] == ("mutate", ("y",), {"page": 4})
        assert [c.args[0] for c in mock_delete.await_args_list] == [
            "bust:mutate:4",
            "extra:y",
        ]


class TestCacheInvalidatorAsyncKeyGenerator:
    async def test_an_async_generator_can_bust_multiple_keys(self):
        async def key_gen(func_name: str, *args: Any, **kwargs: Any) -> list[str]:
            return ["bust:a", "bust:b"]

        @CacheInvalidator(key_generator=key_gen)
        async def mutate(item_id: str) -> str:
            return "done"

        with patch("app.decorators.caching.delete_cache", new_callable=AsyncMock) as mock_delete:
            assert await mutate("x") == "done"

        assert [c.args[0] for c in mock_delete.await_args_list] == ["bust:a", "bust:b"]
