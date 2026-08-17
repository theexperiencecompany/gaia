"""Unit tests for the Redis caching decorators.

``Cacheable`` and ``CacheInvalidator`` are applied at import time all over the
service layer, so the service suites only ever exercise the *wrapper* they
produced during collection — never the decorator classes themselves. These
tests construct and apply them per test, which is the only way the key
strategies, the serializer hooks and the invalidation fan-out are actually
run rather than inherited from module import.

Redis is mocked at the module's seam (``get_cache`` / ``set_cache`` /
``delete_cache``), never the decorators under test.
"""

from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.decorators.caching import Cacheable, CacheInvalidator, _pattern_to_key

MODULE = "app.decorators.caching"


@pytest.fixture
def redis_seam() -> Iterator[dict[str, AsyncMock]]:
    """The three Redis calls the decorators make, as mocks."""
    with (
        patch(f"{MODULE}.get_cache", new_callable=AsyncMock, return_value=None) as get_mock,
        patch(f"{MODULE}.set_cache", new_callable=AsyncMock) as set_mock,
        patch(f"{MODULE}.delete_cache", new_callable=AsyncMock) as delete_mock,
    ):
        yield {"get": get_mock, "set": set_mock, "delete": delete_mock}


class TestCacheableConstruction:
    def test_rejects_a_decorator_with_no_key_strategy(self) -> None:
        with pytest.raises(ValueError, match="key_pattern, key_generator, or smart_hash"):
            Cacheable()

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"key": "static"},
            {"key_pattern": "user:{user_id}"},
            {"key_generator": lambda _func_name, *a, **k: "generated"},
            {"smart_hash": True},
        ],
    )
    def test_each_key_strategy_is_accepted_on_its_own(self, kwargs: dict[str, Any]) -> None:
        assert Cacheable(**kwargs) is not None

    def test_namespace_defaults_to_api(self) -> None:
        assert Cacheable(smart_hash=True).namespace == "api"

    def test_optional_hooks_default_to_absent(self) -> None:
        decorator = Cacheable(key="k")

        assert decorator.serializer is None
        assert decorator.deserializer is None
        assert decorator.model is None


class TestCacheableKeyGeneration:
    async def test_a_static_key_is_used_verbatim(self, redis_seam: dict[str, AsyncMock]) -> None:
        @Cacheable(key="plans:all")
        async def load() -> str:
            return "value"

        await load()

        assert redis_seam["get"].await_args.args[0] == "plans:all"

    async def test_a_pattern_is_filled_from_the_call_arguments(
        self, redis_seam: dict[str, AsyncMock]
    ) -> None:
        @Cacheable(key_pattern="user:{user_id}:profile")
        async def load(user_id: str) -> str:
            return "value"

        await load("u42")

        assert redis_seam["get"].await_args.args[0] == "user:u42:profile"

    async def test_a_pattern_sees_defaulted_arguments_too(
        self, redis_seam: dict[str, AsyncMock]
    ) -> None:
        @Cacheable(key_pattern="user:{user_id}:{version}")
        async def load(user_id: str, version: str = "v2") -> str:
            return "value"

        await load("u42")

        assert redis_seam["get"].await_args.args[0] == "user:u42:v2"

    async def test_a_sync_key_generator_receives_the_function_name_and_args(
        self, redis_seam: dict[str, AsyncMock]
    ) -> None:
        def key_for(_func_name: str, *args: object, **kwargs: object) -> str:
            return f"{_func_name}:{args[0]}"

        @Cacheable(key_generator=key_for)
        async def load(item_id: str) -> str:
            return "value"

        await load("abc")

        assert redis_seam["get"].await_args.args[0] == "load:abc"

    async def test_an_async_key_generator_is_awaited(
        self, redis_seam: dict[str, AsyncMock]
    ) -> None:
        async def key_for(_func_name: str, *args: object, **kwargs: object) -> str:
            return f"async:{_func_name}"

        @Cacheable(key_generator=key_for)
        async def load() -> str:
            return "value"

        await load()

        assert redis_seam["get"].await_args.args[0] == "async:load"

    async def test_smart_hash_keys_are_namespaced_and_argument_sensitive(
        self, redis_seam: dict[str, AsyncMock]
    ) -> None:
        @Cacheable(smart_hash=True, namespace="metrics")
        async def load(user_id: str) -> str:
            return "value"

        await load("a")
        first = redis_seam["get"].await_args.args[0]
        await load("b")
        second = redis_seam["get"].await_args.args[0]

        assert first.startswith("metrics:load:")
        assert first != second


class TestCacheableBehaviour:
    async def test_a_miss_calls_the_function_and_stores_its_result(
        self, redis_seam: dict[str, AsyncMock]
    ) -> None:
        calls: list[int] = []

        @Cacheable(key="k", ttl=60)
        async def load() -> str:
            calls.append(1)
            return "fresh"

        assert await load() == "fresh"
        assert calls == [1]
        assert redis_seam["set"].await_args.kwargs["value"] == "fresh"
        assert redis_seam["set"].await_args.kwargs["ttl"] == 60

    async def test_a_hit_returns_the_cached_value_without_calling_the_function(
        self, redis_seam: dict[str, AsyncMock]
    ) -> None:
        redis_seam["get"].return_value = "cached"
        calls: list[int] = []

        @Cacheable(key="k")
        async def load() -> str:
            calls.append(1)
            return "fresh"

        assert await load() == "cached"
        assert calls == []
        redis_seam["set"].assert_not_awaited()

    async def test_a_sync_function_is_wrapped_into_an_awaitable(
        self, redis_seam: dict[str, AsyncMock]
    ) -> None:
        @Cacheable(key="k")
        def load() -> str:
            return "sync result"

        assert await load() == "sync result"

    async def test_the_serializer_shapes_what_is_stored_not_what_is_returned(
        self, redis_seam: dict[str, AsyncMock]
    ) -> None:
        @Cacheable(key="k", serializer=lambda value: {"wrapped": value})
        async def load() -> str:
            return "fresh"

        assert await load() == "fresh"
        assert redis_seam["set"].await_args.kwargs["value"] == {"wrapped": "fresh"}

    async def test_without_a_serializer_the_raw_result_is_stored(
        self, redis_seam: dict[str, AsyncMock]
    ) -> None:
        @Cacheable(key="k")
        async def load() -> dict[str, int]:
            return {"count": 3}

        await load()

        assert redis_seam["set"].await_args.kwargs["value"] == {"count": 3}

    async def test_the_deserializer_shapes_what_a_hit_returns(
        self, redis_seam: dict[str, AsyncMock]
    ) -> None:
        redis_seam["get"].return_value = {"wrapped": "cached"}

        @Cacheable(key="k", deserializer=lambda value: value["wrapped"])
        async def load() -> str:
            return "fresh"

        assert await load() == "cached"

    async def test_ignore_none_skips_caching_a_none_result(
        self, redis_seam: dict[str, AsyncMock]
    ) -> None:
        @Cacheable(key="k", ignore_none=True)
        async def load() -> str | None:
            return None

        assert await load() is None
        redis_seam["set"].assert_not_awaited()

    async def test_without_ignore_none_a_none_result_is_still_cached(
        self, redis_seam: dict[str, AsyncMock]
    ) -> None:
        @Cacheable(key="k")
        async def load() -> str | None:
            return None

        assert await load() is None
        assert redis_seam["set"].await_args.kwargs["value"] is None

    async def test_the_wrapped_functions_identity_survives_decoration(
        self, redis_seam: dict[str, AsyncMock]
    ) -> None:
        @Cacheable(key="k")
        async def load_plans() -> str:
            """Docstring kept."""
            return "value"

        assert load_plans.__name__ == "load_plans"
        assert load_plans.__doc__ == "Docstring kept."


class TestCacheInvalidator:
    def test_rejects_an_invalidator_with_no_key_strategy(self) -> None:
        with pytest.raises(ValueError, match="key, key_patterns, or key_generator"):
            CacheInvalidator()

    async def test_every_pattern_is_deleted_before_the_function_runs(
        self, redis_seam: dict[str, AsyncMock]
    ) -> None:
        order: list[str] = []
        redis_seam["delete"].side_effect = lambda key: order.append(f"delete:{key}")

        @CacheInvalidator(key_patterns=["user:{user_id}:profile", "user:{user_id}:stats"])
        async def update(user_id: str) -> str:
            order.append("update")
            return "done"

        assert await update("u42") == "done"
        assert order == ["delete:user:u42:profile", "delete:user:u42:stats", "update"]

    async def test_a_static_key_is_invalidated_verbatim(
        self, redis_seam: dict[str, AsyncMock]
    ) -> None:
        @CacheInvalidator(key="plans:all")
        async def update() -> None:
            return None

        await update()

        redis_seam["delete"].assert_awaited_once_with("plans:all")

    async def test_a_key_generator_drives_the_invalidated_key(
        self, redis_seam: dict[str, AsyncMock]
    ) -> None:
        @CacheInvalidator(key_generator=lambda _func_name, *a, **k: f"team:{k['team_id']}")
        async def update(*, team_id: str) -> None:
            return None

        await update(team_id="t9")

        redis_seam["delete"].assert_awaited_once_with("team:t9")

    async def test_an_async_key_generator_is_awaited(
        self, redis_seam: dict[str, AsyncMock]
    ) -> None:
        async def key_for(_func_name: str, *args: object, **kwargs: object) -> str:
            return "async:key"

        @CacheInvalidator(key_generator=key_for)
        async def update() -> None:
            return None

        await update()

        redis_seam["delete"].assert_awaited_once_with("async:key")

    async def test_a_sync_function_is_wrapped_into_an_awaitable(
        self, redis_seam: dict[str, AsyncMock]
    ) -> None:
        @CacheInvalidator(key="k")
        def update() -> str:
            return "sync result"

        assert await update() == "sync result"


class TestPatternToKey:
    def test_placeholders_are_filled_from_the_bound_arguments(self) -> None:
        key = _pattern_to_key(
            "user:{user_id}:profile:{version}",
            arguments={"user_id": 123, "version": "v2", "extra": "ignored"},
        )

        assert key == "user:123:profile:v2"

    def test_a_pattern_without_placeholders_is_returned_as_is(self) -> None:
        assert _pattern_to_key("plans:all", arguments={}) == "plans:all"

    def test_a_missing_placeholder_is_a_named_value_error(self) -> None:
        with pytest.raises(ValueError, match="Missing key in pattern"):
            _pattern_to_key("user:{user_id}", arguments={"other": 1})

    def test_a_malformed_pattern_is_a_named_value_error(self) -> None:
        with pytest.raises(ValueError, match="Error generating key from pattern"):
            _pattern_to_key("user:{user_id", arguments={"user_id": 1})
