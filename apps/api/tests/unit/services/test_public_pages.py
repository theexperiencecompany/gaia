"""invalidate_public_pages against a mocked web server (the only seam faked)."""

from collections.abc import Iterator
import json
from unittest.mock import AsyncMock, call, patch

import httpx
import pytest
import respx

from app.config.settings import settings
from app.constants.http import INTERNAL_CALLER_HEADER
from app.constants.public_pages import (
    PUBLIC_PAGES_REVALIDATE_ATTEMPTS,
    PUBLIC_PAGES_REVALIDATE_RETRY_WAIT_SECONDS,
    PUBLIC_PAGES_REVALIDATE_TIMEOUT_SECONDS,
    PublicPageDomain,
)
from app.services.public_pages import invalidate_public_pages

_MOD = "app.services.public_pages"
WEB_URL = "http://gaia-web:3000"
REVALIDATE_URL = f"{WEB_URL}/api/public-pages/revalidate"
TOKEN = "internal-token"


@pytest.fixture(autouse=True)
def web_server(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "WEB_INTERNAL_URL", WEB_URL)
    monkeypatch.setattr(settings, "INTERNAL_API_TOKEN", TOKEN)


@pytest.fixture(autouse=True)
def cleared_lists() -> Iterator[AsyncMock]:
    """Record the API's own cached public lists being dropped."""
    with patch("app.decorators.caching.delete_cache", new_callable=AsyncMock) as clear:
        yield clear


@pytest.fixture(autouse=True)
def retry_waits() -> Iterator[AsyncMock]:
    """Record the waits between attempts instead of sleeping through them."""
    with patch("asyncio.sleep", new_callable=AsyncMock) as sleep:
        yield sleep


@respx.mock
async def test_posts_the_domain_to_the_web_server_with_the_internal_token() -> None:
    route = respx.post(REVALIDATE_URL).mock(return_value=httpx.Response(200, json={}))

    with (
        patch(f"{_MOD}.httpx.AsyncClient", wraps=httpx.AsyncClient) as client_cls,
        patch(f"{_MOD}.log") as mock_log,
    ):
        await invalidate_public_pages(PublicPageDomain.WORKFLOWS)

    request = route.calls.last.request
    assert route.call_count == 1
    assert json.loads(request.content) == {"domain": "workflows"}
    assert request.headers[INTERNAL_CALLER_HEADER] == TOKEN
    assert client_cls.call_args.kwargs == {"timeout": PUBLIC_PAGES_REVALIDATE_TIMEOUT_SECONDS}
    mock_log.error.assert_not_called()
    mock_log.set_ns.assert_called_once_with("public_pages", invalidated="workflows")


@respx.mock
async def test_a_refused_call_is_logged_as_an_error_and_not_retried_or_raised() -> None:
    route = respx.post(REVALIDATE_URL).mock(return_value=httpx.Response(401))

    with patch(f"{_MOD}.log") as mock_log:
        await invalidate_public_pages(PublicPageDomain.INTEGRATIONS)

    assert route.call_count == 1
    args, kwargs = mock_log.error.call_args
    assert args == ("Public page invalidation failed",)
    assert kwargs["public_pages_domain"] == "integrations"
    assert kwargs["error_type"] == "HTTPStatusError"
    assert "401" in kwargs["error"]
    mock_log.set_ns.assert_not_called()


@respx.mock
async def test_an_unreachable_web_server_is_retried_then_logged_as_an_error(
    retry_waits: AsyncMock,
) -> None:
    route = respx.post(REVALIDATE_URL).mock(side_effect=httpx.ConnectError("refused"))

    with patch(f"{_MOD}.log") as mock_log:
        await invalidate_public_pages(PublicPageDomain.INTEGRATIONS)

    assert route.call_count == PUBLIC_PAGES_REVALIDATE_ATTEMPTS
    assert retry_waits.await_args_list == [call(PUBLIC_PAGES_REVALIDATE_RETRY_WAIT_SECONDS)] * (
        PUBLIC_PAGES_REVALIDATE_ATTEMPTS - 1
    )
    mock_log.error.assert_called_once_with(
        "Public page invalidation failed",
        public_pages_domain="integrations",
        error="refused",
        error_type="ConnectError",
    )


@respx.mock
async def test_a_server_error_is_retried_until_the_web_server_answers() -> None:
    route = respx.post(REVALIDATE_URL).mock(
        side_effect=[httpx.Response(500), httpx.Response(200, json={})]
    )

    with patch(f"{_MOD}.log") as mock_log:
        await invalidate_public_pages(PublicPageDomain.INTEGRATIONS)

    assert route.call_count == 2
    mock_log.error.assert_not_called()


@respx.mock
async def test_without_the_internal_token_nothing_is_sent_and_a_warning_says_so(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "INTERNAL_API_TOKEN", None)
    route = respx.post(REVALIDATE_URL)

    with patch(f"{_MOD}.log") as mock_log:
        await invalidate_public_pages(PublicPageDomain.INTEGRATIONS)

    assert not route.called
    mock_log.warning.assert_called_once_with(
        "Public pages not invalidated: INTERNAL_API_TOKEN is not set",
        public_pages_domain="integrations",
    )


@pytest.mark.parametrize(
    ("domain", "pattern"),
    [
        (PublicPageDomain.INTEGRATIONS, "marketplace:community:*"),
        (PublicPageDomain.WORKFLOWS, "workflows:community:*"),
    ],
)
@respx.mock
async def test_the_apis_own_cached_list_is_dropped_before_the_web_server_is_told(
    cleared_lists: AsyncMock, domain: PublicPageDomain, pattern: str
) -> None:
    cleared_before_the_call: list[int] = []

    def answer(_request: httpx.Request) -> httpx.Response:
        cleared_before_the_call.append(cleared_lists.await_count)
        return httpx.Response(200)

    respx.post(REVALIDATE_URL).mock(side_effect=answer)

    await invalidate_public_pages(domain)

    cleared_lists.assert_awaited_once_with(pattern)
    assert cleared_before_the_call == [1]


@respx.mock
async def test_the_cached_list_is_dropped_even_when_no_token_lets_the_call_be_sent(
    cleared_lists: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "INTERNAL_API_TOKEN", None)

    with patch(f"{_MOD}.log"):
        await invalidate_public_pages(PublicPageDomain.WORKFLOWS)

    cleared_lists.assert_awaited_once_with("workflows:community:*")
