"""FreeTierBudget unit tests: the real RedisCache over an in-memory client."""

import pytest

from app.db.redis import RedisCache
from app.utils.search import budget as budget_module
from app.utils.search.budget import FreeTierBudget


class _FakeRedisClient:
    def __init__(self, raises: bool = False) -> None:
        self.store: dict[str, str] = {}
        self._raises = raises

    async def get(self, name: str) -> str | None:
        if self._raises:
            raise RuntimeError("redis down")
        return self.store.get(name)

    async def incr(self, key: str) -> int:
        self.store[key] = str(int(self.store.get(key, "0")) + 1)
        return int(self.store[key])

    async def expire(self, key: str, ttl: int) -> None:
        pass


def _install_client(monkeypatch: pytest.MonkeyPatch, client: _FakeRedisClient) -> None:
    cache = RedisCache()
    monkeypatch.setattr(cache, "redis", client)
    monkeypatch.setattr(budget_module, "redis_cache", cache)


async def _record_calls(budget: FreeTierBudget, provider: str, count: int) -> None:
    for _ in range(count):
        await budget.record_call(provider)


async def test_uncapped_provider_always_has_headroom(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_client(monkeypatch, _FakeRedisClient())
    budget = FreeTierBudget({})  # provider not listed -> uncapped
    assert await budget.has_headroom("searxng") is True


async def test_has_headroom_true_when_under_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_client(monkeypatch, _FakeRedisClient())
    budget = FreeTierBudget({"exa": 10})
    await _record_calls(budget, "exa", 9)
    assert await budget.has_headroom("exa") is True


async def test_no_headroom_once_the_recorded_calls_reach_the_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_client(monkeypatch, _FakeRedisClient())
    budget = FreeTierBudget({"exa": 10})
    await _record_calls(budget, "exa", 10)
    assert await budget.has_headroom("exa") is False


async def test_one_providers_usage_does_not_spend_anothers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_client(monkeypatch, _FakeRedisClient())
    budget = FreeTierBudget({"exa": 10, "tavily": 10})
    await _record_calls(budget, "exa", 10)
    assert await budget.has_headroom("tavily") is True


@pytest.mark.parametrize("stored", ["not-an-int", "10.5"])
async def test_fails_open_on_malformed_counter(
    monkeypatch: pytest.MonkeyPatch, stored: str
) -> None:
    client = _FakeRedisClient()
    _install_client(monkeypatch, client)
    budget = FreeTierBudget({"exa": 10})
    await budget.record_call("exa")
    (key,) = client.store
    client.store[key] = stored
    assert await budget.has_headroom("exa") is True


async def test_fails_open_on_redis_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_client(monkeypatch, _FakeRedisClient(raises=True))
    budget = FreeTierBudget({"exa": 10})
    assert await budget.has_headroom("exa") is True


async def test_record_call_increments_listed_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeRedisClient()
    _install_client(monkeypatch, client)
    budget = FreeTierBudget({"exa": 10})

    await budget.record_call("exa")

    assert any(key.startswith("search_budget:exa:") for key in client.store)


async def test_record_call_noop_for_uncapped_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeRedisClient()
    _install_client(monkeypatch, client)
    budget = FreeTierBudget({"exa": 10})

    await budget.record_call("searxng")  # not budget-capped

    assert client.store == {}
