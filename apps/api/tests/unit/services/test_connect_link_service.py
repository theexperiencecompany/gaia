"""Security-critical tests for the login-free connect-link code.

The code authenticates a logged-out bot user straight into an OAuth connect, so
resolution is the security boundary. These tests probe minting, atomic
single-use consumption, and rejection of unknown/malformed codes.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config.settings import settings
import app.services.connect_link_service as svc
from app.services.connect_link_service import (
    build_connect_link_url,
    resolve_and_consume_connect_code,
)


@pytest.fixture
def fake_store():
    """In-memory stand-in for the Redis single-use store: ``set_cache`` writes,
    ``get_and_delete_cache`` reads-and-deletes (the single-use guarantee)."""
    store: dict[str, object] = {}

    async def _set(key, value, ttl=None, model=None):
        store[key] = value

    async def _getdel(key):
        return store.pop(key, None)

    redis = MagicMock()
    redis.redis = MagicMock()  # truthy → Redis "available"
    with (
        patch.object(svc, "redis_cache", redis),
        patch.object(svc, "set_cache", AsyncMock(side_effect=_set)),
        patch.object(svc, "get_and_delete_cache", AsyncMock(side_effect=_getdel)),
    ):
        yield store


def _code_from_url(url: str | None) -> str:
    assert url is not None
    return url.rsplit("/", 1)[1]


@pytest.mark.unit
class TestConnectLinkCode:
    async def test_mint_then_resolve_returns_user_and_integration(self, fake_store) -> None:
        url = await build_connect_link_url("user1", "notion")
        assert url is not None
        assert url.startswith(f"{settings.FRONTEND_URL.rstrip('/')}/connect/")
        code = _code_from_url(url)
        assert await resolve_and_consume_connect_code(code) == ("user1", "notion")

    async def test_single_use_second_resolve_is_none(self, fake_store) -> None:
        """Second open of the same link must fail — the heart of single-use."""
        code = _code_from_url(await build_connect_link_url("user1", "notion"))
        first = await resolve_and_consume_connect_code(code)
        second = await resolve_and_consume_connect_code(code)
        assert first == ("user1", "notion")
        assert second is None

    async def test_unknown_code_rejected(self, fake_store) -> None:
        assert await resolve_and_consume_connect_code("does-not-exist") is None

    async def test_malformed_binding_rejected(self, fake_store) -> None:
        """A stored value missing integration_id must not resolve to a partial."""
        await svc.set_cache(svc._code_key("partial"), {"user_id": "u"})
        assert await resolve_and_consume_connect_code("partial") is None

    async def test_two_mints_have_distinct_codes(self, fake_store) -> None:
        a = _code_from_url(await build_connect_link_url("u", "notion"))
        b = _code_from_url(await build_connect_link_url("u", "notion"))
        assert a != b

    async def test_code_has_high_entropy_length(self, fake_store) -> None:
        # token_urlsafe(12) → 16 url-safe chars / 96 bits of entropy.
        code = _code_from_url(await build_connect_link_url("u", "notion"))
        assert len(code) >= 16

    async def test_redis_unavailable_returns_none(self) -> None:
        """No store → no link can be minted; callers degrade to a generic prompt."""
        redis = MagicMock()
        redis.redis = None
        with patch.object(svc, "redis_cache", redis):
            assert await build_connect_link_url("user1", "notion") is None
