"""Single-use codes for the local session-import CLI."""

from __future__ import annotations

from typing import Any

import pytest

from app.services.browser import import_token as mod


class _FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, object] = {}

    async def get(self, key: str, model: type[Any] | None = None) -> object:
        raw = self.store.get(key)
        if raw is None or model is None:
            return raw
        return model.model_validate(raw) if isinstance(raw, dict) else raw

    async def set(
        self, key: str, value: object, ttl: int | None = None, model: type[Any] | None = None
    ) -> bool:
        self.store[key] = value.model_dump() if hasattr(value, "model_dump") else value
        return True

    async def delete(self, key: str) -> None:
        self.store.pop(key, None)


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
        """The code authorises writing the user's whole login state — a second
        redemption must fail, or a leaked code could overwrite it repeatedly."""
        token = await mod.mint_import_token("user-1")
        assert await mod.consume_import_token(token) == "user-1"
        assert await mod.consume_import_token(token) is None

    async def test_unknown_token_returns_none(self, fake_redis: _FakeRedis) -> None:
        assert await mod.consume_import_token("never-minted") is None

    async def test_each_mint_is_unique(self, fake_redis: _FakeRedis) -> None:
        assert await mod.mint_import_token("u") != await mod.mint_import_token("u")
