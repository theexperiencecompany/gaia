"""FreeTierBudget unit tests (Redis interactions mocked)."""

import pytest

from app.utils.search import budget as budget_module
from app.utils.search.budget import FreeTierBudget


class _FakeRedisClient:
    def __init__(self) -> None:
        self.store: dict[str, int] = {}

    async def incr(self, key: str) -> int:
        self.store[key] = self.store.get(key, 0) + 1
        return self.store[key]

    async def expire(self, key: str, ttl: int) -> None:
        pass


class _FakeRedisCache:
    def __init__(self, value: str | None = None, raises: bool = False) -> None:
        self._value = value
        self._raises = raises
        self.redis = _FakeRedisClient()

    async def get(self, key: str) -> str | None:
        if self._raises:
            raise RuntimeError("redis down")
        return self._value


async def test_uncapped_provider_always_has_headroom(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(budget_module, "redis_cache", _FakeRedisCache(value="9999"))
    budget = FreeTierBudget({})  # provider not listed -> uncapped
    assert await budget.has_headroom("searxng") is True


async def test_has_headroom_true_when_under_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(budget_module, "redis_cache", _FakeRedisCache(value="5"))
    budget = FreeTierBudget({"exa": 10})
    assert await budget.has_headroom("exa") is True


async def test_no_headroom_when_at_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(budget_module, "redis_cache", _FakeRedisCache(value="10"))
    budget = FreeTierBudget({"exa": 10})
    assert await budget.has_headroom("exa") is False


async def test_fails_open_on_malformed_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(budget_module, "redis_cache", _FakeRedisCache(value="not-an-int"))
    budget = FreeTierBudget({"exa": 10})
    assert await budget.has_headroom("exa") is True


async def test_fails_open_on_redis_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(budget_module, "redis_cache", _FakeRedisCache(raises=True))
    budget = FreeTierBudget({"exa": 10})
    assert await budget.has_headroom("exa") is True


async def test_record_call_increments_listed_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    cache = _FakeRedisCache(value="0")
    monkeypatch.setattr(budget_module, "redis_cache", cache)
    budget = FreeTierBudget({"exa": 10})

    await budget.record_call("exa")

    assert any(key.startswith("search_budget:exa:") for key in cache.redis.store)


async def test_record_call_noop_for_uncapped_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    cache = _FakeRedisCache(value="0")
    monkeypatch.setattr(budget_module, "redis_cache", cache)
    budget = FreeTierBudget({"exa": 10})

    await budget.record_call("searxng")  # not budget-capped

    assert cache.redis.store == {}
