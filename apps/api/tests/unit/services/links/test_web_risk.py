"""Google Web Risk lookups: one search per URL, a threat in any answer flags the file, and an outage fails loud."""

import asyncio
from collections.abc import Awaitable, Callable

import httpx
import pytest

from app.config.settings import settings
from app.constants.short_links import WEB_RISK_CONCURRENCY, WEB_RISK_MAX_URLS
from app.services.links import web_risk
from app.services.links.web_risk import flagged_urls
from app.utils.errors import AppError

KEY = "test-web-risk-key"
SAFE = "https://example.com/report"
PHISHING = "http://testsafebrowsing.appspot.com/s/phishing.html"
_THREAT = {"threat": {"threatTypes": ["SOCIAL_ENGINEERING"], "expireTime": "2026-11-13T00:00:00Z"}}

Handler = Callable[[httpx.Request], Awaitable[httpx.Response]]


class FakeWebRisk:
    """Answer Web Risk searches through a mock transport, recording each request and client."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.requests: list[httpx.Request] = []
        self.clients: list[httpx.AsyncClient] = []
        self.handler: Handler = self._threat_for_phishing
        real_client = httpx.AsyncClient

        def client(*, timeout: float) -> httpx.AsyncClient:
            built = real_client(transport=httpx.MockTransport(self._record), timeout=timeout)
            self.clients.append(built)
            return built

        monkeypatch.setattr(web_risk.httpx, "AsyncClient", client)

    async def _record(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return await self.handler(request)

    @staticmethod
    async def _threat_for_phishing(request: httpx.Request) -> httpx.Response:
        flagged = request.url.params["uri"] == PHISHING
        return httpx.Response(200, json=_THREAT if flagged else {})


@pytest.fixture
def google(monkeypatch: pytest.MonkeyPatch) -> FakeWebRisk:
    monkeypatch.setattr(settings, "GOOGLE_WEB_RISK_API_KEY", KEY)
    return FakeWebRisk(monkeypatch)


async def test_each_url_is_searched_for_every_threat_type(google: FakeWebRisk) -> None:
    assert not await flagged_urls([SAFE])
    [request] = google.requests
    assert request.method == "GET"
    assert str(request.url) == (
        "https://webrisk.googleapis.com/v1/uris:search?uri=https%3A%2F%2Fexample.com%2Freport"
        f"&key={KEY}&threatTypes=MALWARE&threatTypes=SOCIAL_ENGINEERING"
        "&threatTypes=UNWANTED_SOFTWARE"
    )
    [client] = google.clients
    assert client.timeout == httpx.Timeout(10.0)


async def test_one_flagged_url_flags_the_file(google: FakeWebRisk) -> None:
    assert await flagged_urls([SAFE, PHISHING, "https://example.org/"])
    assert sorted(request.url.params["uri"] for request in google.requests) == sorted(
        [SAFE, PHISHING, "https://example.org/"]
    )


async def test_only_safe_urls_flag_nothing(google: FakeWebRisk) -> None:
    assert not await flagged_urls([SAFE, "https://example.org/"])
    assert len(google.requests) == 2


async def test_without_a_key_nothing_is_looked_up(
    google: FakeWebRisk, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "GOOGLE_WEB_RISK_API_KEY", None)
    assert not await flagged_urls([PHISHING])
    assert google.requests == []


async def test_a_file_naming_too_many_urls_is_flagged_unchecked(google: FakeWebRisk) -> None:
    urls = [f"https://example.com/{n}" for n in range(WEB_RISK_MAX_URLS + 1)]
    assert await flagged_urls(urls)
    assert google.requests == []


async def test_a_file_at_the_url_limit_is_checked(google: FakeWebRisk) -> None:
    urls = [f"https://example.com/{n}" for n in range(WEB_RISK_MAX_URLS)]
    assert not await flagged_urls(urls)
    assert len(google.requests) == WEB_RISK_MAX_URLS


async def test_lookups_run_at_most_the_concurrency_limit_at_once(google: FakeWebRisk) -> None:
    in_flight = 0
    peak = 0

    async def slow(request: httpx.Request) -> httpx.Response:
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(0.01)
        in_flight -= 1
        return httpx.Response(200, json={})

    google.handler = slow
    assert not await flagged_urls([f"https://example.com/{n}" for n in range(20)])
    assert peak == WEB_RISK_CONCURRENCY


async def _server_error(request: httpx.Request) -> httpx.Response:
    return httpx.Response(500, json={"error": {"code": 500}})


async def _not_json(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, content=b"<html>")


async def _wrong_shape(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"threat": {"types": ["MALWARE"]}})


async def _unreachable(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("connection refused", request=request)


@pytest.mark.parametrize(
    ("handler", "cause"),
    [
        (_server_error, "HTTPStatusError"),
        (_not_json, "JSONDecodeError"),
        (_wrong_shape, "ValidationError"),
        (_unreachable, "ConnectError"),
    ],
)
async def test_an_unanswered_lookup_fails_the_publish(
    google: FakeWebRisk, handler: Handler, cause: str
) -> None:
    google.handler = handler
    with pytest.raises(AppError) as raised:
        await flagged_urls([SAFE])
    assert raised.value == AppError(
        message="This file couldn't be checked for unsafe links right now",
        why="Google Web Risk is unavailable",
        fix="Try sharing it again in a minute",
        status_code=503,
        code="web_risk_unavailable",
        meta={"cause": cause},
    )
