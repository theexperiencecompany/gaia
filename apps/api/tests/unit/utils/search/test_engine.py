"""Search engine waterfall behaviour: failover, budget gating, and selection."""

from app.utils.search.engine import SearchEngine
from app.utils.search.models import SearchResponse, SearchResultItem
from app.utils.search.providers.base import SearchProvider


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


async def test_returns_first_non_empty_provider():
    first = FakeProvider("first")
    second = FakeProvider("second")
    engine = SearchEngine(providers=[first, second], budget=FakeBudget())

    response = await engine.search("q", 5)

    assert response.provider == "first"
    assert second.called is False


async def test_skips_unconfigured_provider():
    unconfigured = FakeProvider("unconfigured", configured=False)
    fallback = FakeProvider("fallback")
    engine = SearchEngine(providers=[unconfigured, fallback], budget=FakeBudget())

    response = await engine.search("q", 5)

    assert response.provider == "fallback"
    assert unconfigured.called is False


async def test_fails_over_on_exception():
    broken = FakeProvider("broken", raises=True)
    healthy = FakeProvider("healthy")
    engine = SearchEngine(providers=[broken, healthy], budget=FakeBudget())

    response = await engine.search("q", 5)

    assert response.provider == "healthy"


async def test_fails_over_on_empty_results():
    empty = FakeProvider("empty", response=SearchResponse(provider="empty"))
    healthy = FakeProvider("healthy")
    engine = SearchEngine(providers=[empty, healthy], budget=FakeBudget())

    response = await engine.search("q", 5)

    assert empty.called is True
    assert response.provider == "healthy"


async def test_skips_provider_without_budget_headroom():
    budgeted = FakeProvider("budgeted", monthly_free_limit=1000)
    floor = FakeProvider("floor")
    engine = SearchEngine(providers=[budgeted, floor], budget=FakeBudget(denied={"budgeted"}))

    response = await engine.search("q", 5)

    assert budgeted.called is False
    assert response.provider == "floor"


async def test_records_budget_on_successful_call():
    budget = FakeBudget()
    engine = SearchEngine(providers=[FakeProvider("first")], budget=budget)

    await engine.search("q", 5)

    assert budget.recorded == ["first"]


async def test_returns_empty_response_when_all_exhausted():
    a = FakeProvider("a", raises=True)
    b = FakeProvider("b", response=SearchResponse(provider="b"))
    engine = SearchEngine(providers=[a, b], budget=FakeBudget())

    response = await engine.search("q", 5)

    assert response.is_empty
    assert response.provider is None
