"""POST /api/v1/fetch-url-metadata admits a signed-in user or GAIA's own web server, nothing else."""

from collections.abc import Iterator
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from httpx import AsyncClient
import pytest

from app.api.v1.dependencies.oauth_dependencies import get_optional_user
from app.config.settings import settings
from app.constants.http import INTERNAL_CALLER_HEADER
from app.models.search_models import URLResponse
from tests.conftest import FAKE_USER

URL = "/api/v1/fetch-url-metadata"
INTERNAL_TOKEN = "internal-token-for-tests"  # pragma: allowlist secret
WEB_URL = "https://example.com"
EMAIL_TARGET = "mailto:ada@example.org"
BODY = {"urls": [WEB_URL, EMAIL_TARGET]}
PROFILES = "app.api.v1.endpoints.search.fetch_email_profiles"
FETCH = "app.api.v1.endpoints.search.fetch_url_metadata"


def _preview(url: str, title: str) -> URLResponse:
    return URLResponse(
        title=title,
        description=None,
        favicon=None,
        website_name=None,
        website_image=None,
        url=url,
    )


@pytest.fixture(autouse=True)
def _internal_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "INTERNAL_API_TOKEN", INTERNAL_TOKEN)
    monkeypatch.setattr(settings, "INTERNAL_API_TOKEN_PREVIOUS", None)


@pytest.fixture
def web_page() -> Iterator[AsyncMock]:
    """Stub the outbound network fetch only."""
    with patch(FETCH, new_callable=AsyncMock) as fetch:
        fetch.return_value = _preview(WEB_URL, "Example")
        yield fetch


@pytest.fixture
def contact_lookup() -> Iterator[AsyncMock]:
    with patch(PROFILES, new_callable=AsyncMock) as profiles:
        profiles.return_value = {}
        yield profiles


@pytest.mark.regression
async def test_internal_web_server_gets_web_urls_and_no_contact_lookup(
    client: AsyncClient, web_page: AsyncMock, contact_lookup: AsyncMock
):
    response = await client.post(URL, json=BODY, headers={INTERNAL_CALLER_HEADER: INTERNAL_TOKEN})

    assert response.status_code == 200
    assert list(response.json()["results"]) == [WEB_URL]
    contact_lookup.assert_not_called()


async def test_no_credentials_is_unauthorized(
    client: AsyncClient, web_page: AsyncMock, contact_lookup: AsyncMock
):
    response = await client.post(URL, json=BODY)

    assert response.status_code == 401
    web_page.assert_not_called()


async def test_wrong_internal_token_is_unauthorized(
    client: AsyncClient, web_page: AsyncMock, contact_lookup: AsyncMock
):
    response = await client.post(URL, json=BODY, headers={INTERNAL_CALLER_HEADER: "not-the-token"})

    assert response.status_code == 401
    web_page.assert_not_called()


async def test_signed_in_user_still_resolves_email_targets(
    client: AsyncClient, test_app: FastAPI, web_page: AsyncMock, contact_lookup: AsyncMock
):
    contact_lookup.return_value = {EMAIL_TARGET: _preview(EMAIL_TARGET, "Ada")}
    test_app.dependency_overrides[get_optional_user] = lambda: FAKE_USER
    try:
        response = await client.post(URL, json=BODY)
    finally:
        test_app.dependency_overrides.pop(get_optional_user)

    assert response.status_code == 200
    assert set(response.json()["results"]) == {WEB_URL, EMAIL_TARGET}
    contact_lookup.assert_awaited_once_with(FAKE_USER.user_id, [EMAIL_TARGET])
