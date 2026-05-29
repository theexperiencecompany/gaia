"""Unit tests for the search API endpoints.

The named overhaul target ``app/models/search_models.py`` is a pure Pydantic
data-model module with zero behavioral logic (no branches, comparisons,
arithmetic or non-trivial constants) — there is nothing in it a mutation can
break. Its models are exercised, and the real behavioral logic is mutation-
verified, through their only consumer: ``app/api/v1/endpoints/search.py``.

These tests pin that endpoint module's contract:
  * search_messages_endpoint  — passthrough, result-count emission, 500 path
  * extract_emails            — regex email extraction (no dedup)
  * search_email_endpoint     — perform_search call shape, failure branch, dedup
  * fetch_url_metadata_endpoint — concurrent fetch, exception-skip, type filter

Only I/O boundaries are mocked: the search/metadata service functions, the
external web-search util, and the wide-events logger (whose ``set`` payload is
asserted because the emitted ``result_count`` is part of the endpoint contract).
"""

from unittest.mock import AsyncMock, MagicMock, patch

from httpx import AsyncClient
import pytest

from app.api.v1.endpoints.search import extract_emails

SEARCH_BASE = "/api/v1"

SEARCH_MESSAGES = "app.api.v1.endpoints.search.search_messages"
PERFORM_SEARCH = "app.api.v1.endpoints.search.perform_search"
FETCH_URL_METADATA = "app.api.v1.endpoints.search.fetch_url_metadata"
ENDPOINT_LOG = "app.api.v1.endpoints.search.log"

# The authenticated user id injected by the root `client` fixture (FAKE_USER).
FAKE_USER_ID = "507f1f77bcf86cd799439011"  # pragma: allowlist secret


def _result_counts(mock_log: MagicMock) -> list[int]:
    """Return every ``result_count`` value the endpoint emitted via log.set."""
    counts = []
    for call in mock_log.set.call_args_list:
        search = call.kwargs.get("search")
        if isinstance(search, dict) and "result_count" in search:
            counts.append(search["result_count"])
    return counts


@pytest.mark.unit
class TestExtractEmails:
    """app.api.v1.endpoints.search.extract_emails — the regex helper."""

    def test_extracts_all_email_addresses(self):
        text = "Reach sales@acme.io or, separately, support.team@sub.acme.co.uk now."
        assert extract_emails(text) == ["sales@acme.io", "support.team@sub.acme.co.uk"]

    def test_keeps_duplicates_no_dedup(self):
        # The helper itself does NOT dedup; dedup is the endpoint's job.
        assert extract_emails("a@x.com and a@x.com") == ["a@x.com", "a@x.com"]

    def test_returns_empty_when_no_email(self):
        assert extract_emails("no addresses here, just words.") == []


@pytest.mark.unit
class TestSearchMessages:
    """GET /api/v1/search — search_messages_endpoint."""

    @patch(SEARCH_MESSAGES, new_callable=AsyncMock)
    async def test_returns_service_payload_verbatim(
        self, mock_search: AsyncMock, client: AsyncClient
    ):
        payload = {
            "messages": [{"id": "msg-1", "content": "hello"}],
            "conversations": [{"id": "c-1"}],
            "notes": [],
        }
        mock_search.return_value = payload
        response = await client.get(f"{SEARCH_BASE}/search", params={"query": "hello"})
        assert response.status_code == 200
        assert response.json() == payload

    @patch(SEARCH_MESSAGES, new_callable=AsyncMock)
    async def test_passes_query_and_authenticated_user_id(
        self, mock_search: AsyncMock, client: AsyncClient
    ):
        mock_search.return_value = {"messages": [], "conversations": [], "notes": []}
        await client.get(f"{SEARCH_BASE}/search", params={"query": "find me"})
        mock_search.assert_awaited_once_with("find me", FAKE_USER_ID)

    @patch(ENDPOINT_LOG, new=MagicMock())
    @patch(SEARCH_MESSAGES, new_callable=AsyncMock)
    async def test_result_count_is_sum_of_all_three_categories(
        self, mock_search: AsyncMock, client: AsyncClient
    ):
        # 2 messages + 3 conversations + 1 note == 6.
        from app.api.v1.endpoints import search as search_module

        mock_search.return_value = {
            "messages": [{"id": "m1"}, {"id": "m2"}],
            "conversations": [{"id": "c1"}, {"id": "c2"}, {"id": "c3"}],
            "notes": [{"id": "n1"}],
        }
        response = await client.get(f"{SEARCH_BASE}/search", params={"query": "x"})
        assert response.status_code == 200
        assert _result_counts(search_module.log) == [6]

    @patch(SEARCH_MESSAGES, new_callable=AsyncMock)
    async def test_service_failure_returns_500_with_detail(
        self, mock_search: AsyncMock, client: AsyncClient
    ):
        mock_search.side_effect = RuntimeError("search engine down")
        response = await client.get(f"{SEARCH_BASE}/search", params={"query": "boom"})
        assert response.status_code == 500
        assert response.json() == {"detail": "Search failed"}

    async def test_missing_query_returns_422(self, client: AsyncClient):
        response = await client.get(f"{SEARCH_BASE}/search")
        assert response.status_code == 422


@pytest.mark.unit
class TestSearchEmail:
    """GET /api/v1/search/email — search_email_endpoint."""

    @patch(PERFORM_SEARCH, new_callable=AsyncMock)
    async def test_calls_perform_search_with_exact_query_and_flags(
        self, mock_perform: AsyncMock, client: AsyncClient
    ):
        mock_perform.return_value = {"web": []}
        await client.get(f"{SEARCH_BASE}/search/email", params={"query": "Acme Corp"})
        mock_perform.assert_awaited_once_with(
            query="Official contact e-mail address of Acme Corp",
            count=50,
            images=False,
            videos=False,
            news=False,
        )

    @patch(PERFORM_SEARCH, new_callable=AsyncMock)
    async def test_combines_title_and_snippet_and_extracts_emails(
        self, mock_perform: AsyncMock, client: AsyncClient
    ):
        mock_perform.return_value = {
            "web": [
                {"title": "Contact head@acme.io", "snippet": "or write to sales@acme.io"},
            ]
        }
        response = await client.get(f"{SEARCH_BASE}/search/email", params={"query": "Acme"})
        assert response.status_code == 200
        data = response.json()
        # Both the title email and the snippet email must be present -> proves
        # combined_text is built from title AND snippet, not just one.
        assert set(data["emails"]) == {"head@acme.io", "sales@acme.io"}
        assert "Contact head@acme.io or write to sales@acme.io" in data["combined_text"]
        assert data["search_data"] == mock_perform.return_value

    @patch(PERFORM_SEARCH, new_callable=AsyncMock)
    async def test_deduplicates_repeated_emails(self, mock_perform: AsyncMock, client: AsyncClient):
        mock_perform.return_value = {
            "web": [
                {"title": "Page1", "snippet": "info@test.com hello info@test.com"},
                {"title": "Page2", "snippet": "info@test.com again"},
            ]
        }
        response = await client.get(f"{SEARCH_BASE}/search/email", params={"query": "t"})
        assert response.status_code == 200
        assert response.json()["emails"] == ["info@test.com"]

    @patch(ENDPOINT_LOG, new=MagicMock())
    @patch(PERFORM_SEARCH, new_callable=AsyncMock)
    async def test_emits_deduped_email_count(self, mock_perform: AsyncMock, client: AsyncClient):
        from app.api.v1.endpoints import search as search_module

        mock_perform.return_value = {"web": [{"title": "", "snippet": "a@x.com b@x.com a@x.com"}]}
        response = await client.get(f"{SEARCH_BASE}/search/email", params={"query": "t"})
        assert response.status_code == 200
        # 2 distinct emails after dedup.
        assert _result_counts(search_module.log) == [2]

    @patch(PERFORM_SEARCH, new_callable=AsyncMock)
    async def test_falsy_search_data_returns_500_detail(
        self, mock_perform: AsyncMock, client: AsyncClient
    ):
        mock_perform.return_value = None
        response = await client.get(f"{SEARCH_BASE}/search/email", params={"query": "unknown"})
        assert response.status_code == 500
        assert response.json() == {"detail": "Search failed or returned no results"}

    @patch(PERFORM_SEARCH, new_callable=AsyncMock)
    async def test_missing_web_key_returns_500_detail(
        self, mock_perform: AsyncMock, client: AsyncClient
    ):
        # Truthy dict without a "web" key. With the correct `or` guard this is a
        # clean HTTPException(500, detail=...). If the guard were `and`, the
        # endpoint would proceed and crash on search_data["web"] -> a generic
        # {"error": ...} 500. Asserting the exact detail body kills `or`->`and`.
        mock_perform.return_value = {"images": []}
        response = await client.get(f"{SEARCH_BASE}/search/email", params={"query": "t"})
        assert response.status_code == 500
        assert response.json() == {"detail": "Search failed or returned no results"}

    async def test_missing_query_returns_422(self, client: AsyncClient):
        response = await client.get(f"{SEARCH_BASE}/search/email")
        assert response.status_code == 422


@pytest.mark.unit
class TestFetchUrlMetadata:
    """POST /api/v1/fetch-url-metadata — fetch_url_metadata_endpoint."""

    @staticmethod
    def _url_response(url: str, title: str):
        from app.models.search_models import URLResponse

        return URLResponse(
            title=title,
            description=None,
            favicon=None,
            website_name=None,
            website_image=None,
            url=url,  # type: ignore[arg-type]
        )

    @patch(FETCH_URL_METADATA, new_callable=AsyncMock)
    async def test_returns_metadata_keyed_by_url(self, mock_fetch: AsyncMock, client: AsyncClient):
        mock_fetch.return_value = self._url_response("https://example.com", "Example")
        response = await client.post(
            f"{SEARCH_BASE}/fetch-url-metadata",
            json={"urls": ["https://example.com"]},
        )
        assert response.status_code == 200
        data = response.json()
        assert list(data["results"].keys()) == ["https://example.com"]
        assert data["results"]["https://example.com"]["title"] == "Example"
        mock_fetch.assert_awaited_once_with("https://example.com")

    @patch(FETCH_URL_METADATA, new_callable=AsyncMock)
    async def test_fetches_every_url_and_maps_each(
        self, mock_fetch: AsyncMock, client: AsyncClient
    ):
        mock_fetch.side_effect = [
            self._url_response("https://a.com", "Site A"),
            self._url_response("https://b.com", "Site B"),
        ]
        response = await client.post(
            f"{SEARCH_BASE}/fetch-url-metadata",
            json={"urls": ["https://a.com", "https://b.com"]},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["results"]["https://a.com"]["title"] == "Site A"
        assert data["results"]["https://b.com"]["title"] == "Site B"

    @patch(FETCH_URL_METADATA, new_callable=AsyncMock)
    async def test_skips_urls_that_raise(self, mock_fetch: AsyncMock, client: AsyncClient):
        mock_fetch.side_effect = [
            self._url_response("https://good.com", "Good"),
            TimeoutError("boom"),
        ]
        response = await client.post(
            f"{SEARCH_BASE}/fetch-url-metadata",
            json={"urls": ["https://good.com", "https://bad.com"]},
        )
        assert response.status_code == 200
        results = response.json()["results"]
        assert results["https://good.com"]["title"] == "Good"
        assert "https://bad.com" not in results

    @patch(FETCH_URL_METADATA, new_callable=AsyncMock)
    async def test_empty_urls_returns_empty_and_never_fetches(
        self, mock_fetch: AsyncMock, client: AsyncClient
    ):
        response = await client.post(f"{SEARCH_BASE}/fetch-url-metadata", json={"urls": []})
        assert response.status_code == 200
        assert response.json()["results"] == {}
        mock_fetch.assert_not_awaited()

    async def test_missing_urls_field_returns_422(self, client: AsyncClient):
        response = await client.post(f"{SEARCH_BASE}/fetch-url-metadata", json={})
        assert response.status_code == 422
