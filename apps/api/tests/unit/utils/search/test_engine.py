"""Search engine waterfall behaviour: failover, budget gating, and selection."""

import httpx
import pytest
import respx

from app.config.settings import settings
from app.services.providers.provider_credentials_service import resolve
from app.utils.search.engine import SearchEngine
from app.utils.search.models import SearchResponse, SearchResultItem
from app.utils.search.providers import default_providers
from app.utils.search.providers.base import SearchProvider
from tests.helpers import InMemoryCredentialStore


def _response(provider: str) -> SearchResponse:
    return SearchResponse(
        results=[SearchResultItem(url=f"https://{provider}.example/1")],
        provider=provider,
    )


class FakeProvider(SearchProvider):
    def __init__(
        self,
        name: str,
        *,
        configured: bool = True,
        response: SearchResponse | None = None,
        raises: bool = False,
        monthly_free_limit: int | None = None,
    ) -> None:
        self.name = name
        self.monthly_free_limit = monthly_free_limit
        self._configured = configured
        self._response = response if response is not None else _response(name)
        self._raises = raises
        self.called = False

    def is_configured(self) -> bool:
        return self._configured

    async def search(self, query: str, count: int) -> SearchResponse:
        self.called = True
        if self._raises:
            raise RuntimeError("provider boom")
        return self._response


class FakeBudget:
    def __init__(self, denied: set[str] | None = None) -> None:
        self._denied = denied or set()
        self.recorded: list[str] = []

    async def has_headroom(self, provider: str) -> bool:
        return provider not in self._denied

    async def record_call(self, provider: str) -> None:
        self.recorded.append(provider)


async def test_returns_first_non_empty_provider() -> None:
    first = FakeProvider("first")
    second = FakeProvider("second")
    engine = SearchEngine(providers=[first, second], budget=FakeBudget())

    response = await engine.search("q", 5)

    assert response.provider == "first"
    assert second.called is False


async def test_skips_unconfigured_provider() -> None:
    unconfigured = FakeProvider("unconfigured", configured=False)
    fallback = FakeProvider("fallback")
    engine = SearchEngine(providers=[unconfigured, fallback], budget=FakeBudget())

    response = await engine.search("q", 5)

    assert response.provider == "fallback"
    assert unconfigured.called is False


async def test_fails_over_on_exception() -> None:
    broken = FakeProvider("broken", raises=True)
    healthy = FakeProvider("healthy")
    engine = SearchEngine(providers=[broken, healthy], budget=FakeBudget())

    response = await engine.search("q", 5)

    assert response.provider == "healthy"


async def test_fails_over_on_empty_results() -> None:
    empty = FakeProvider("empty", response=SearchResponse(provider="empty"))
    healthy = FakeProvider("healthy")
    engine = SearchEngine(providers=[empty, healthy], budget=FakeBudget())

    response = await engine.search("q", 5)

    assert empty.called is True
    assert response.provider == "healthy"


async def test_skips_provider_without_budget_headroom() -> None:
    budgeted = FakeProvider("budgeted", monthly_free_limit=1000)
    floor = FakeProvider("floor")
    engine = SearchEngine(providers=[budgeted, floor], budget=FakeBudget(denied={"budgeted"}))

    response = await engine.search("q", 5)

    assert budgeted.called is False
    assert response.provider == "floor"


async def test_records_budget_on_successful_call() -> None:
    budget = FakeBudget()
    engine = SearchEngine(providers=[FakeProvider("first")], budget=budget)

    await engine.search("q", 5)

    assert budget.recorded == ["first"]


async def test_returns_empty_response_when_all_exhausted() -> None:
    a = FakeProvider("a", raises=True)
    b = FakeProvider("b", response=SearchResponse(provider="b"))
    engine = SearchEngine(providers=[a, b], budget=FakeBudget())

    response = await engine.search("q", 5)

    assert response.is_empty
    assert response.provider is None


@pytest.mark.parametrize(
    ("env", "auth_mode", "order"),
    [
        ("production", "workos", ["exa", "tavily", "brave", "duckduckgo", "searxng"]),
        ("development", "workos", ["exa", "tavily", "brave", "duckduckgo", "searxng"]),
        ("selfhost", "local", ["exa", "tavily", "brave", "searxng", "duckduckgo"]),
    ],
)
def test_waterfall_order_per_deployment(
    monkeypatch: pytest.MonkeyPatch, env: str, auth_mode: str, order: list[str]
) -> None:
    monkeypatch.setattr(settings, "ENV", env)
    monkeypatch.setattr(settings, "AUTH_MODE", auth_mode)

    assert [p.name for p in default_providers()] == order


@respx.mock
async def test_selfhost_with_searxng_never_sends_the_query_to_duckduckgo(
    selfhost_credential_store: InMemoryCredentialStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    for field in ("EXA_API_KEY", "TAVILY_API_KEY", "BRAVE_API_KEY", "SEARXNG_BASE_URL"):
        monkeypatch.setattr(settings, field, None)
    selfhost_credential_store.save("searxng", base_url="http://searxng.lan:8080")
    await resolve("searxng")
    searxng = respx.get("http://searxng.lan:8080/search").mock(
        return_value=httpx.Response(200, json={"results": [{"url": "https://example.com/s"}]})
    )
    duckduckgo = respx.post("https://lite.duckduckgo.com/lite/").mock(
        return_value=httpx.Response(200, text="<html></html>")
    )

    response = await SearchEngine(budget=FakeBudget()).search("private query", 5)

    assert response.provider == "searxng"
    assert searxng.called
    assert not duckduckgo.called
