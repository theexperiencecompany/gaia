"""Unit tests for search API endpoints.

Tests the search endpoints with mocked service layer
to verify routing, status codes, response bodies, and validation.
"""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

SEARCH_BASE = "/api/v1"


@pytest.mark.unit
class TestSearchMessages:
    """GET /api/v1/search"""

    @patch(
        "app.api.v1.endpoints.search.search_messages",
        new_callable=AsyncMock,
    )
    async def test_search_returns_200(
        self, mock_search: AsyncMock, client: AsyncClient
    ):
        mock_search.return_value = {
            "messages": [{"id": "msg-1", "content": "hello"}],
            "conversations": [],
            "notes": [],
        }
        response = await client.get(f"{SEARCH_BASE}/search", params={"query": "hello"})
        assert response.status_code == 200
        data = response.json()
        assert "messages" in data
        assert "conversations" in data
        assert "notes" in data
        assert len(data["messages"]) == 1

    @patch(
        "app.api.v1.endpoints.search.search_messages",
        new_callable=AsyncMock,
    )
    async def test_search_passes_user_id(
        self, mock_search: AsyncMock, client: AsyncClient
    ):
        mock_search.return_value = {"messages": [], "conversations": [], "notes": []}
        await client.get(f"{SEARCH_BASE}/search", params={"query": "test"})
        mock_search.assert_awaited_once_with(
            "test",
            "507f1f77bcf86cd799439011",  # pragma: allowlist secret
        )

    async def test_search_missing_query_returns_422(self, client: AsyncClient):
        response = await client.get(f"{SEARCH_BASE}/search")
        assert response.status_code == 422

    @patch(
        "app.api.v1.endpoints.search.search_messages",
        new_callable=AsyncMock,
    )
    async def test_search_empty_results(
        self, mock_search: AsyncMock, client: AsyncClient
    ):
        mock_search.return_value = {"messages": [], "conversations": [], "notes": []}
        response = await client.get(
            f"{SEARCH_BASE}/search", params={"query": "nothing"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["messages"] == []
        assert data["conversations"] == []
        assert data["notes"] == []

    @patch(
        "app.api.v1.endpoints.search.search_messages",
        new_callable=AsyncMock,
    )
    async def test_search_service_error_returns_500(
        self, mock_search: AsyncMock, client: AsyncClient
    ):
        mock_search.side_effect = Exception("Search engine down")
        response = await client.get(f"{SEARCH_BASE}/search", params={"query": "test"})
        assert response.status_code == 500


@pytest.mark.unit
class TestSearchEmail:
    """GET /api/v1/search/email"""

    @patch(
        "app.api.v1.endpoints.search.perform_search",
        new_callable=AsyncMock,
    )
    async def test_search_email_returns_200(
        self, mock_perform: AsyncMock, client: AsyncClient
    ):
        mock_perform.return_value = {
            "web": [
                {
                    "title": "Contact Us",
                    "snippet": "Email us at support@example.com",
                }
            ]
        }
        response = await client.get(
            f"{SEARCH_BASE}/search/email", params={"query": "Example Corp"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "emails" in data
        assert "combined_text" in data
        assert "search_data" in data
        assert "support@example.com" in data["emails"]

    @patch(
        "app.api.v1.endpoints.search.perform_search",
        new_callable=AsyncMock,
    )
    async def test_search_email_no_results_returns_500(
        self, mock_perform: AsyncMock, client: AsyncClient
    ):
        mock_perform.return_value = None
        response = await client.get(
            f"{SEARCH_BASE}/search/email", params={"query": "unknown"}
        )
        assert response.status_code == 500

    @patch(
        "app.api.v1.endpoints.search.perform_search",
        new_callable=AsyncMock,
    )
    async def test_search_email_no_web_key_returns_500(
        self, mock_perform: AsyncMock, client: AsyncClient
    ):
        mock_perform.return_value = {"images": []}
        response = await client.get(
            f"{SEARCH_BASE}/search/email", params={"query": "test"}
        )
        assert response.status_code == 500

    @patch(
        "app.api.v1.endpoints.search.perform_search",
        new_callable=AsyncMock,
    )
    async def test_search_email_deduplicates_emails(
        self, mock_perform: AsyncMock, client: AsyncClient
    ):
        mock_perform.return_value = {
            "web": [
                {"title": "Page1", "snippet": "info@test.com hello info@test.com"},
                {"title": "Page2", "snippet": "info@test.com again"},
            ]
        }
        response = await client.get(
            f"{SEARCH_BASE}/search/email", params={"query": "test"}
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["emails"]) == 1
        assert "info@test.com" in data["emails"]

    async def test_search_email_missing_query_returns_422(self, client: AsyncClient):
        response = await client.get(f"{SEARCH_BASE}/search/email")
        assert response.status_code == 422


@pytest.mark.unit
class TestFetchUrlMetadata:
    """POST /api/v1/fetch-url-metadata"""

    @patch(
        "app.api.v1.endpoints.search.fetch_url_metadata",
        new_callable=AsyncMock,
    )
    async def test_fetch_url_metadata_returns_200(
        self, mock_fetch: AsyncMock, client: AsyncClient
    ):
        from app.models.search_models import URLResponse

        mock_fetch.return_value = URLResponse(
            title="Example",
            description="An example page",
            favicon="https://example.com/favicon.ico",
            website_name="Example",
            website_image=None,
            url="https://example.com",  # type: ignore[arg-type]
        )
        response = await client.post(
            f"{SEARCH_BASE}/fetch-url-metadata",
            json={"urls": ["https://example.com"]},
        )
        assert response.status_code == 200
        data = response.json()
        assert "results" in data
        assert "https://example.com" in data["results"]
        assert data["results"]["https://example.com"]["title"] == "Example"

    @patch(
        "app.api.v1.endpoints.search.fetch_url_metadata",
        new_callable=AsyncMock,
    )
    async def test_fetch_url_metadata_multiple_urls(
        self, mock_fetch: AsyncMock, client: AsyncClient
    ):
        from app.models.search_models import URLResponse

        url1_resp = URLResponse(
            title="Site A",
            description=None,
            favicon=None,
            website_name=None,
            website_image=None,
            url="https://a.com",  # type: ignore[arg-type]
        )
        url2_resp = URLResponse(
            title="Site B",
            description=None,
            favicon=None,
            website_name=None,
            website_image=None,
            url="https://b.com",  # type: ignore[arg-type]
        )
        mock_fetch.side_effect = [url1_resp, url2_resp]
        response = await client.post(
            f"{SEARCH_BASE}/fetch-url-metadata",
            json={"urls": ["https://a.com", "https://b.com"]},
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["results"]) == 2

    @patch(
        "app.api.v1.endpoints.search.fetch_url_metadata",
        new_callable=AsyncMock,
    )
    async def test_fetch_url_metadata_skips_failed_urls(
        self, mock_fetch: AsyncMock, client: AsyncClient
    ):
        from app.models.search_models import URLResponse

        good_resp = URLResponse(
            title="Good",
            description=None,
            favicon=None,
            website_name=None,
            website_image=None,
            url="https://good.com",  # type: ignore[arg-type]
        )
        mock_fetch.side_effect = [good_resp, Exception("Timeout")]
        response = await client.post(
            f"{SEARCH_BASE}/fetch-url-metadata",
            json={"urls": ["https://good.com", "https://bad.com"]},
        )
        assert response.status_code == 200
        data = response.json()
        assert "https://good.com" in data["results"]
        assert "https://bad.com" not in data["results"]

    async def test_fetch_url_metadata_missing_urls_returns_422(
        self, client: AsyncClient
    ):
        response = await client.post(f"{SEARCH_BASE}/fetch-url-metadata", json={})
        assert response.status_code == 422

    @patch(
        "app.api.v1.endpoints.search.fetch_url_metadata",
        new_callable=AsyncMock,
    )
    async def test_fetch_url_metadata_empty_urls_returns_200(
        self, mock_fetch: AsyncMock, client: AsyncClient
    ):
        response = await client.post(
            f"{SEARCH_BASE}/fetch-url-metadata", json={"urls": []}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["results"] == {}
        mock_fetch.assert_not_awaited()
