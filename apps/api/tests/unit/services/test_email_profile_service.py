"""Unit tests for email_profile_service (email -> person preview resolution).

Sources (Google contacts, Gravatar, domain favicon) degrade silently and
merge field-wise in priority order; results are cached per (user, email).
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.constants.email import (
    DOMAIN_FAVICON_URL_TEMPLATE,
    EMAIL_PROFILE_CACHE_KEY_TEMPLATE,
    GOOGLE_CONTACTS_SOURCE_NAME,
    GRAVATAR_SOURCE_NAME,
)
from app.models.search_models import URLResponse
from app.services.email_profile_service import (
    _domain_favicon_profile,
    _merge_profiles,
    _person_to_profile,
    _pick_photo,
    fetch_email_profile,
    fetch_email_profiles,
)

_MOD = "app.services.email_profile_service"
USER_ID = "507f1f77bcf86cd799439011"
EMAIL = "alice@example.com"


def _person(**overrides: object) -> dict:
    data: dict[str, object] = {
        "resourceName": "people/c123",
        "emailAddresses": [{"value": EMAIL}],
        "names": [{"displayName": "Alice Example"}],
        "photos": [{"url": "https://photos.example/avatar.jpg"}],
    }
    data.update(overrides)
    return data


def _search_result(person: dict) -> dict:
    return {"results": [{"person": person}]}


def _proxy_side_effect(search_payload: dict, get_payload: dict):
    async def fake_proxy_request(**kwargs: object) -> dict:
        endpoint = kwargs["endpoint"]
        if "search" in str(endpoint):
            return search_payload
        return get_payload

    return fake_proxy_request


@pytest.fixture
def mock_http():
    """All network seams: People API proxy, Gravatar fetcher, Redis cache."""
    with (
        patch(f"{_MOD}.proxy_request", new_callable=AsyncMock) as m_proxy,
        patch(f"{_MOD}._fetch_gravatar_profile", new_callable=AsyncMock) as m_gravatar,
        patch(f"{_MOD}.get_cache", new_callable=AsyncMock) as m_get,
        patch(f"{_MOD}.set_cache", new_callable=AsyncMock) as m_set,
    ):
        m_proxy.return_value = {}
        m_gravatar.return_value = None
        m_get.return_value = None
        yield SimpleNamespace(proxy=m_proxy, gravatar=m_gravatar, get=m_get, set=m_set)


class TestFetchEmailProfile:
    async def test_invalid_email_returns_bare_url_response(self, mock_http):
        response = await fetch_email_profile(USER_ID, "not-an-email")

        assert response.url == "not-an-email"
        assert response.title is None
        assert response.favicon is None
        assert response.website_name is None
        mock_http.set.assert_not_awaited()

    async def test_serves_from_cache(self, mock_http):
        mock_http.get.return_value = {"title": "Cached Alice", "favicon": "https://x/f.png"}

        response = await fetch_email_profile(USER_ID, "mailto:alice@example.com")

        assert response.url == "mailto:alice@example.com"
        assert response.title == "Cached Alice"
        assert response.favicon == "https://x/f.png"
        mock_http.proxy.assert_not_awaited()
        mock_http.set.assert_not_awaited()

    async def test_resolves_google_contact_and_caches(self, mock_http):
        person = _person()
        mock_http.proxy.side_effect = _proxy_side_effect(
            _search_result(person),
            {
                "photos": [
                    {
                        "url": "https://photos.example/real.jpg",
                        "metadata": {"source": {"type": "PROFILE"}},
                    }
                ]
            },
        )

        response = await fetch_email_profile(USER_ID, EMAIL)

        assert response.url == EMAIL
        assert response.title == "Alice Example"
        assert response.favicon == "https://photos.example/real.jpg"
        assert response.website_name == GOOGLE_CONTACTS_SOURCE_NAME
        mock_http.set.assert_awaited_once()
        key, value, ttl = mock_http.set.await_args.args
        assert key == EMAIL_PROFILE_CACHE_KEY_TEMPLATE.format(user_id=USER_ID, email=EMAIL)
        assert "url" not in value
        assert value["title"] == "Alice Example"
        assert ttl == 24 * 60 * 60

    async def test_freemail_domain_never_gets_domain_favicon(self, mock_http):
        mock_http.proxy.return_value = {}
        mock_http.gravatar.return_value = None

        response = await fetch_email_profile(USER_ID, "alice@gmail.com")

        assert response.favicon is None
        assert response.website_name is None

    async def test_company_domain_falls_back_to_favicon(self, mock_http):
        mock_http.proxy.return_value = {}
        mock_http.gravatar.return_value = None

        response = await fetch_email_profile(USER_ID, "alice@acme-corp.com")

        assert response.favicon == DOMAIN_FAVICON_URL_TEMPLATE.format(domain="acme-corp.com")
        assert response.website_name is None
        assert response.title is None

    async def test_gravatar_contributes_when_contacts_miss(self, mock_http):
        mock_http.proxy.return_value = {}
        mock_http.gravatar.return_value = URLResponse(
            title="Gravatar Alice",
            description="Public bio",
            favicon="https://gravatar.example/a.jpg",
            website_name=GRAVATAR_SOURCE_NAME,
            url="",
        )

        response = await fetch_email_profile(USER_ID, EMAIL)

        assert response.title == "Gravatar Alice"
        assert response.description == "Public bio"
        assert response.website_name == GRAVATAR_SOURCE_NAME

    async def test_empty_search_triggers_warmup_retry(self, mock_http):
        """Google's search endpoints go cold after inactivity — the service must
        warm up (empty query) and retry before giving up."""
        calls = {"n": 0}

        async def fake_proxy_request(**kwargs: object) -> dict:
            calls["n"] += 1
            if calls["n"] <= 2:
                return {"results": []}
            return _search_result(_person())

        mock_http.proxy.side_effect = fake_proxy_request
        with patch(f"{_MOD}.PEOPLE_SEARCH_WARMUP_DELAY_SECONDS", 0):
            response = await fetch_email_profile(USER_ID, EMAIL)

        assert response.title == "Alice Example"
        assert calls["n"] >= 4

    async def test_proxy_failure_degrades_to_fallback(self, mock_http):
        mock_http.proxy.side_effect = RuntimeError("composio down")
        mock_http.gravatar.return_value = None

        response = await fetch_email_profile(USER_ID, EMAIL)

        assert response.url == EMAIL
        assert response.title is None


class TestFetchEmailProfiles:
    async def test_gather_keyed_by_original_input(self, mock_http):
        mock_http.proxy.return_value = {}
        mock_http.gravatar.return_value = None

        results = await fetch_email_profiles(USER_ID, ["alice@example.com", "bob@example.com"])

        assert set(results) == {"alice@example.com", "bob@example.com"}
        assert results["alice@example.com"].url == "alice@example.com"
        assert results["bob@example.com"].url == "bob@example.com"

    async def test_cache_hits_are_keyed_per_email(self, mock_http):
        mock_http.get.side_effect = lambda key, **kwargs: (
            {"title": "Alice"} if key.endswith("alice@example.com") else None
        )

        results = await fetch_email_profiles(USER_ID, ["alice@example.com", "bob@example.com"])

        assert results["alice@example.com"].title == "Alice"
        assert results["bob@example.com"].title is None


class TestPersonToProfile:
    def test_matches_email_and_extracts_fields(self):
        profile = _person_to_profile(
            {
                "names": [{"displayName": "Alice Example"}],
                "emailAddresses": [{"value": "ALICE@example.com "}],
                "biographies": [{"value": "Works at X"}],
                "photos": [{"url": "https://x/a.jpg"}],
            },
            EMAIL,
        )

        assert profile is not None
        assert profile.title == "Alice Example"
        assert profile.description == "Works at X"
        assert profile.favicon == "https://x/a.jpg"
        assert profile.website_name == GOOGLE_CONTACTS_SOURCE_NAME

    def test_returns_none_when_email_does_not_match(self):
        assert (
            _person_to_profile(_person(emailAddresses=[{"value": "other@example.com"}]), EMAIL)
            is None
        )

    def test_returns_none_without_name_or_photo(self):
        assert _person_to_profile({"emailAddresses": [{"value": EMAIL}]}, EMAIL) is None

    def test_prefers_real_photo_over_monogram(self):
        photos = [
            {"url": "https://x/monogram.jpg", "default": True},
            {"url": "https://x/real.jpg"},
        ]

        assert _pick_photo(photos) == "https://x/real.jpg"

    def test_pick_photo_prefers_profile_source(self):
        photos = [
            {"url": "https://x/real.jpg"},
            {"url": "https://x/profile.jpg", "metadata": {"source": {"type": "PROFILE"}}},
        ]

        assert _pick_photo(photos) == "https://x/profile.jpg"

    def test_pick_photo_empty(self):
        assert _pick_photo([]) is None
        assert _pick_photo([{"default": True, "url": "https://x/m.jpg"}]) is None


class TestMergeProfiles:
    def test_first_non_empty_field_wins_in_priority_order(self):
        merged = _merge_profiles(
            [
                None,
                URLResponse(title="Second", favicon="https://second/f.png", url=""),
                URLResponse(title="First", description="d", url=""),
            ]
        )

        assert merged.title == "Second"
        assert merged.description == "d"
        assert merged.favicon == "https://second/f.png"

    def test_empty_string_never_wins_a_field(self):
        merged = _merge_profiles([URLResponse(title="", favicon="", url="")])

        assert merged.title is None
        assert merged.favicon is None


class TestDomainFaviconProfile:
    def test_none_for_freemail(self):
        assert _domain_favicon_profile("alice@gmail.com") is None

    def test_favicon_for_company_domain(self):
        profile = _domain_favicon_profile("alice@acme-corp.com")

        assert profile is not None
        assert profile.favicon == DOMAIN_FAVICON_URL_TEMPLATE.format(domain="acme-corp.com")
