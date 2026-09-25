"""Single-use codes for the local session-import CLI."""

from __future__ import annotations

from typing import Any

import pytest

from app.constants.browser import BROWSER_IMPORT_TOKEN_TTL_SECONDS
from app.services.browser import import_token as mod

DEFAULT_REDIS_TTL_SECONDS = 3600


class _FakeRedis:
    """Mirrors RedisCache's contract, including its 1-hour default TTL."""

    def __init__(self) -> None:
        self.store: dict[str, object] = {}
        self.ttls: dict[str, int] = {}

    async def get(self, key: str, model: type[Any] | None = None) -> object:
        raw = self.store.get(key)
        if raw is None or model is None:
            return raw
        return model.model_validate(raw) if isinstance(raw, dict) else raw

    async def set(
        self,
        key: str,
        value: object,
        ttl: int = DEFAULT_REDIS_TTL_SECONDS,
        model: type[Any] | None = None,
    ) -> bool:
        self.store[key] = value.model_dump() if hasattr(value, "model_dump") else value
        self.ttls[key] = ttl or DEFAULT_REDIS_TTL_SECONDS
        return True

    async def delete(self, key: str) -> None:
        self.store.pop(key, None)
        self.ttls.pop(key, None)

    async def get_and_delete(self, key: str, model: type[Any] | None = None) -> object:
        record = await self.get(key, model)
        await self.delete(key)
        return record


@pytest.fixture
def fake_redis(monkeypatch: pytest.MonkeyPatch) -> _FakeRedis:
    fake = _FakeRedis()
    monkeypatch.setattr(mod, "redis_cache", fake)
    return fake


@pytest.mark.unit
class TestImportToken:
    async def test_mint_then_consume_returns_the_user(self, fake_redis: _FakeRedis) -> None:
        token = await mod.mint_import_token("user-1")
        assert await mod.consume_import_token(token) == "user-1"

    async def test_token_is_single_use(self, fake_redis: _FakeRedis) -> None:
        """The code authorises writing the user's whole login state — a second redemption must fail, or a leaked code could overwrite it repeatedly."""
        token = await mod.mint_import_token("user-1")
        assert await mod.consume_import_token(token) == "user-1"
        assert await mod.consume_import_token(token) is None

    async def test_unknown_token_returns_none(self, fake_redis: _FakeRedis) -> None:
        assert await mod.consume_import_token("never-minted") is None

    async def test_code_expires_after_the_import_ttl_not_the_cache_default(
        self, fake_redis: _FakeRedis
    ) -> None:
        """The code authorises a login overwrite — it must live 10 minutes, not the cache's 1-hour default."""
        token = await mod.mint_import_token("user-1")

        assert fake_redis.ttls[mod._key(token)] == BROWSER_IMPORT_TOKEN_TTL_SECONDS
        assert BROWSER_IMPORT_TOKEN_TTL_SECONDS < DEFAULT_REDIS_TTL_SECONDS
