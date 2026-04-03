"""Unit tests for app.utils.tool_cache — Redis-backed cache decorator."""

import hashlib
import json
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.utils.tool_cache import (
    _build_cache_key,
    _get_redis_client,
    cache_gather_context,
)


# ---------------------------------------------------------------------------
# _build_cache_key
# ---------------------------------------------------------------------------


class TestBuildCacheKey:
    """Tests for _build_cache_key helper."""

    def test_with_access_token(self):
        """Returns a deterministic key based on func name and token hash."""
        creds: Dict[str, Any] = {"access_token": "my-secret-token"}
        key = _build_cache_key("module.func", creds)

        expected_hash = hashlib.sha256("my-secret-token".encode()).hexdigest()[:16]
        assert key == f"tool_cache:module.func:{expected_hash}"

    def test_without_access_token(self):
        """Returns None when access_token key is missing entirely."""
        creds: Dict[str, Any] = {"refresh_token": "something"}
        key = _build_cache_key("module.func", creds)
        assert key is None

    def test_empty_access_token(self):
        """Returns None when access_token is an empty string."""
        creds: Dict[str, Any] = {"access_token": ""}
        key = _build_cache_key("module.func", creds)
        assert key is None

    def test_empty_credentials(self):
        """Returns None when credentials dict is completely empty."""
        creds: Dict[str, Any] = {}
        key = _build_cache_key("module.func", creds)
        assert key is None

    @pytest.mark.parametrize(
        "func_name",
        [
            "simple",
            "module.Class.method",
            "deeply.nested.module.Class.method",
        ],
    )
    def test_different_func_names(self, func_name: str):
        """Key incorporates the full function qualified name."""
        creds: Dict[str, Any] = {"access_token": "tok"}
        key = _build_cache_key(func_name, creds)
        assert key is not None
        assert key.startswith(f"tool_cache:{func_name}:")

    def test_different_tokens_produce_different_keys(self):
        """Two different tokens must map to different cache keys."""
        key_a = _build_cache_key("f", {"access_token": "token-a"})
        key_b = _build_cache_key("f", {"access_token": "token-b"})
        assert key_a != key_b

    def test_same_token_same_func_produces_stable_key(self):
        """Same inputs always produce the same key (deterministic)."""
        creds: Dict[str, Any] = {"access_token": "stable"}
        key1 = _build_cache_key("fn", creds)
        key2 = _build_cache_key("fn", creds)
        assert key1 == key2


# ---------------------------------------------------------------------------
# _get_redis_client
# ---------------------------------------------------------------------------


class TestGetRedisClient:
    """Tests for _get_redis_client helper."""

    def test_success(self):
        """Returns the redis attribute from redis_cache when import succeeds."""
        mock_redis = MagicMock()
        mock_cache = MagicMock()
        mock_cache.redis = mock_redis

        with patch("app.utils.tool_cache.redis_cache", mock_cache, create=True):
            # _get_redis_client does a lazy import; we patch the target module
            with patch.dict(
                "sys.modules",
                {"app.db.redis": MagicMock(redis_cache=mock_cache)},
            ):
                result = _get_redis_client()
        assert result is mock_redis

    def test_import_failure(self):
        """Returns None when the redis module cannot be imported."""
        with patch.dict("sys.modules", {"app.db.redis": None}):
            # Setting a module to None in sys.modules causes ImportError
            result = _get_redis_client()
        assert result is None

    def test_attribute_error(self):
        """Returns None when redis_cache has no .redis attribute."""
        broken_module = MagicMock(spec=[])  # no attributes at all
        with patch.dict("sys.modules", {"app.db.redis": broken_module}):
            result = _get_redis_client()
        assert result is None


# ---------------------------------------------------------------------------
# cache_gather_context decorator
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestCacheGatherContext:
    """Tests for the cache_gather_context decorator."""

    # -- helpers --

    @staticmethod
    def _make_decorated_func(
        return_value: Dict[str, Any],
    ) -> tuple[Any, AsyncMock]:
        """Create a decorated async function and return (decorated, inner_mock)."""
        inner = AsyncMock(return_value=return_value)

        @cache_gather_context(ttl=60)
        async def gather(
            request: Any,
            execute_request: Any,
            auth_credentials: Dict[str, Any],
        ) -> Dict[str, Any]:
            return await inner(request, execute_request, auth_credentials)

        return gather, inner

    @staticmethod
    def _creds(token: str = "test-token") -> Dict[str, Any]:
        return {"access_token": token}

    # -- cache hit --

    async def test_cache_hit_returns_cached_value(self):
        """When Redis holds a cached value, it is returned without calling the function."""
        cached_data = {"tools": ["a", "b"]}
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=json.dumps(cached_data))

        func, inner = self._make_decorated_func({"tools": ["should-not-reach"]})

        with patch("app.utils.tool_cache._get_redis_client", return_value=mock_redis):
            result = await func(MagicMock(), MagicMock(), self._creds())

        assert result == cached_data
        inner.assert_not_awaited()

    async def test_cache_hit_does_not_write_back(self):
        """On a hit, we should not call setex again."""
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=json.dumps({"cached": True}))

        func, _ = self._make_decorated_func({"fresh": True})

        with patch("app.utils.tool_cache._get_redis_client", return_value=mock_redis):
            await func(MagicMock(), MagicMock(), self._creds())

        mock_redis.setex.assert_not_awaited()

    # -- cache miss --

    async def test_cache_miss_calls_function_and_caches_result(self):
        """On miss, call original func, write result to Redis."""
        expected = {"tools": ["x"]}
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)

        func, inner = self._make_decorated_func(expected)

        with patch("app.utils.tool_cache._get_redis_client", return_value=mock_redis):
            result = await func(MagicMock(), MagicMock(), self._creds())

        assert result == expected
        inner.assert_awaited_once()
        mock_redis.setex.assert_awaited_once()
        # Verify correct TTL and serialized payload
        call_args = mock_redis.setex.call_args
        assert call_args[0][1] == 60  # ttl
        assert json.loads(call_args[0][2]) == expected

    # -- Redis unavailable --

    async def test_redis_unavailable_calls_function_directly(self):
        """When _get_redis_client returns None, call the function without caching."""
        expected = {"tools": ["fallback"]}
        func, inner = self._make_decorated_func(expected)

        with patch("app.utils.tool_cache._get_redis_client", return_value=None):
            result = await func(MagicMock(), MagicMock(), self._creds())

        assert result == expected
        inner.assert_awaited_once()

    async def test_redis_get_raises_calls_function(self):
        """If redis.get raises, we fall through and call the function."""
        expected = {"tools": ["recovered"]}
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(side_effect=ConnectionError("gone"))

        func, inner = self._make_decorated_func(expected)

        with patch("app.utils.tool_cache._get_redis_client", return_value=mock_redis):
            result = await func(MagicMock(), MagicMock(), self._creds())

        assert result == expected
        inner.assert_awaited_once()

    async def test_redis_setex_raises_still_returns_result(self):
        """If redis.setex raises, the function result is still returned."""
        expected = {"tools": ["ok"]}
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.setex = AsyncMock(side_effect=ConnectionError("write fail"))

        func, inner = self._make_decorated_func(expected)

        with patch("app.utils.tool_cache._get_redis_client", return_value=mock_redis):
            result = await func(MagicMock(), MagicMock(), self._creds())

        assert result == expected

    # -- no cache key (empty token) --

    async def test_no_cache_key_skips_caching(self):
        """When auth_credentials has no access_token, caching is bypassed entirely."""
        expected = {"tools": ["uncached"]}
        mock_redis = AsyncMock()

        func, inner = self._make_decorated_func(expected)

        with patch("app.utils.tool_cache._get_redis_client", return_value=mock_redis):
            result = await func(MagicMock(), MagicMock(), {"access_token": ""})

        assert result == expected
        inner.assert_awaited_once()
        mock_redis.get.assert_not_awaited()
        mock_redis.setex.assert_not_awaited()

    # -- custom TTL --

    async def test_custom_ttl_passed_to_setex(self):
        """The TTL argument is forwarded to redis.setex."""
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)

        inner = AsyncMock(return_value={"data": 1})

        @cache_gather_context(ttl=900)
        async def gather(
            request: Any,
            execute_request: Any,
            auth_credentials: Dict[str, Any],
        ) -> Dict[str, Any]:
            return await inner(request, execute_request, auth_credentials)

        with patch("app.utils.tool_cache._get_redis_client", return_value=mock_redis):
            await gather(MagicMock(), MagicMock(), self._creds())

        call_args = mock_redis.setex.call_args
        assert call_args[0][1] == 900

    async def test_default_ttl_is_300(self):
        """When no TTL is specified, the default (300s) is used."""
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)

        inner = AsyncMock(return_value={"data": 1})

        @cache_gather_context()
        async def gather(
            request: Any,
            execute_request: Any,
            auth_credentials: Dict[str, Any],
        ) -> Dict[str, Any]:
            return await inner(request, execute_request, auth_credentials)

        with patch("app.utils.tool_cache._get_redis_client", return_value=mock_redis):
            await gather(MagicMock(), MagicMock(), self._creds())

        call_args = mock_redis.setex.call_args
        assert call_args[0][1] == 300

    # -- JSON serialization error on write --

    async def test_json_serialization_error_on_write(self):
        """Non-serializable results should not crash; result is still returned."""
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        # setex will receive the json.dumps output; we force json.dumps to fail
        # by patching it at the module level for the setex path.
        # Alternatively, make setex raise (simulates the failure path).
        mock_redis.setex = AsyncMock(side_effect=TypeError("not serializable"))

        func, inner = self._make_decorated_func({"key": "value"})

        with patch("app.utils.tool_cache._get_redis_client", return_value=mock_redis):
            result = await func(MagicMock(), MagicMock(), self._creds())

        # Function result is returned despite the write error
        assert result == {"key": "value"}

    async def test_json_dumps_failure_on_write(self):
        """If json.dumps itself raises, the decorator catches and returns the result."""
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)

        # Return a non-serializable value from the inner function
        non_serializable = {"obj": object()}
        inner = AsyncMock(return_value=non_serializable)

        @cache_gather_context(ttl=60)
        async def gather(
            request: Any,
            execute_request: Any,
            auth_credentials: Dict[str, Any],
        ) -> Dict[str, Any]:
            return await inner(request, execute_request, auth_credentials)

        with patch("app.utils.tool_cache._get_redis_client", return_value=mock_redis):
            result = await gather(MagicMock(), MagicMock(), self._creds())

        assert result is non_serializable

    # -- json.loads error on read --

    async def test_json_loads_error_on_cache_read(self):
        """If cached value is not valid JSON, fall through to the real function."""
        expected = {"tools": ["fresh"]}
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value="<<<invalid json>>>")

        func, inner = self._make_decorated_func(expected)

        with patch("app.utils.tool_cache._get_redis_client", return_value=mock_redis):
            result = await func(MagicMock(), MagicMock(), self._creds())

        assert result == expected
        inner.assert_awaited_once()

    # -- decorator preserves function metadata --

    async def test_decorator_preserves_function_name(self):
        """functools.wraps should preserve the original function name."""

        @cache_gather_context()
        async def my_custom_gather(
            request: Any,
            execute_request: Any,
            auth_credentials: Dict[str, Any],
        ) -> Dict[str, Any]:
            return {}

        assert my_custom_gather.__name__ == "my_custom_gather"

    # -- arguments forwarded correctly --

    async def test_arguments_forwarded_to_wrapped_function(self):
        """Ensure request, execute_request, and auth_credentials are forwarded."""
        inner = AsyncMock(return_value={"ok": True})

        @cache_gather_context(ttl=60)
        async def gather(
            request: Any,
            execute_request: Any,
            auth_credentials: Dict[str, Any],
        ) -> Dict[str, Any]:
            return await inner(request, execute_request, auth_credentials)

        sentinel_req = object()
        sentinel_exec = object()
        creds = self._creds()

        with patch("app.utils.tool_cache._get_redis_client", return_value=None):
            await gather(sentinel_req, sentinel_exec, creds)

        inner.assert_awaited_once_with(sentinel_req, sentinel_exec, creds)
