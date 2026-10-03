"""Search, MCP health, and the catalog as the user experiences them: answers, tools, browse.

Unit tests prove each provider and each endpoint branch with the engine
patched out, and integration tests prove the MCP endpoint's wiring with a
canned client. Nothing proved the joins: the waterfall actually failing over
when a provider errors or comes back empty, the keyword search joining both
repositories into one response, the MCP endpoint's three probe outcomes
against the real resolver, the marketplace listing real static entries with
custom ones merged in.

Real: the search waterfall, the keyword join, the MCP endpoint branches, the
marketplace assembly. Doubled: provider HTTP (fake providers), Mongo rows
(structured doubles), the MCP server (fake client), the tools store.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
import pytest

from app.api.v1.endpoints import mcp as mcp_endpoint
from app.models.chat_models import MessageModel
from app.models.conversation_models import ConversationDescriptionHit
from app.services.integrations import marketplace
from app.services.search_service import search_messages
from app.utils.search.engine import SearchEngine
from app.utils.search.models import SearchResponse, SearchResultItem
from app.utils.search.providers.base import SearchProvider
from tests.conftest import FAKE_USER

pytestmark = pytest.mark.e2e

MCP_ENDPOINT = "app.api.v1.endpoints.mcp"
MARKETPLACE = "app.services.integrations.marketplace"


class _FakeProvider(SearchProvider):
    name = "fake"
    monthly_free_limit = None

    def __init__(
        self,
        *,
        name: str = "fake",
        configured: bool = True,
        response: SearchResponse | None = None,
        error: Exception | None = None,
    ) -> None:
        self.name = name
        self._configured = configured
        self._response = response or SearchResponse()
        self._error = error
        self.calls = 0

    def is_configured(self) -> bool:
        return self._configured

    async def search(self, query: str, count: int) -> SearchResponse:
        self.calls += 1
        if self._error is not None:
            raise self._error
        return self._response


def _hit(url: str = "https://example.com/a") -> SearchResponse:
    return SearchResponse(
        results=[SearchResultItem(url=url, title="A", content="alpha")],
        provider="fake",
    )


class TestSearchWaterfall:
    async def test_first_non_empty_provider_wins(self) -> None:
        first = _FakeProvider(name="p1", response=_hit("https://p1.example/"))
        second = _FakeProvider(name="p2", response=_hit("https://p2.example/"))
        response = await SearchEngine(providers=[first, second]).search("q", 5)

        assert [r.url for r in response.results] == ["https://p1.example/"]
        assert second.calls == 0

    async def test_error_fails_over_to_the_next_provider(self) -> None:
        broken = _FakeProvider(name="p1", error=RuntimeError("down"))
        backup = _FakeProvider(name="p2", response=_hit("https://p2.example/"))
        response = await SearchEngine(providers=[broken, backup]).search("q", 5)

        assert [r.url for r in response.results] == ["https://p2.example/"]
        assert broken.calls == 1 and backup.calls == 1

    async def test_empty_response_fails_over(self) -> None:
        empty = _FakeProvider(name="p1", response=SearchResponse())
        backup = _FakeProvider(name="p2", response=_hit())
        response = await SearchEngine(providers=[empty, backup]).search("q", 5)

        assert [r.url for r in response.results] == ["https://example.com/a"]

    async def test_unconfigured_provider_is_skipped_without_a_call(self) -> None:
        missing = _FakeProvider(name="p1", configured=False)
        backup = _FakeProvider(name="p2", response=_hit())
        response = await SearchEngine(providers=[missing, backup]).search("q", 5)

        assert missing.calls == 0
        assert [r.url for r in response.results] == ["https://example.com/a"]

    async def test_all_empty_is_an_empty_response_not_an_error(self) -> None:
        providers = [_FakeProvider(name="p1"), _FakeProvider(name="p2")]
        response = await SearchEngine(providers=providers).search("q", 5)

        assert response.results == []


class TestKeywordSearchJoinsBothRepositories:
    async def test_messages_and_notes_merge_into_one_response(self) -> None:
        convo_results = SimpleNamespace(
            messages=[
                SimpleNamespace(
                    conversation_id="conv-1",
                    message=MessageModel(type="user", response="standup moved to nine"),
                )
            ],
            conversations=[ConversationDescriptionHit(conversation_id="conv-1")],
        )
        note_hits = [SimpleNamespace(id="n1", note_id="note-1", plaintext="standup notes here")]
        with (
            patch(
                "app.services.search_service.conversation_repository.search",
                AsyncMock(return_value=convo_results),
            ),
            patch(
                "app.services.search_service.note_repository.search_by_plaintext",
                AsyncMock(return_value=note_hits),
            ),
        ):
            response = await search_messages("standup", FAKE_USER.user_id)

        assert [m.conversation_id for m in response.messages] == ["conv-1"]
        assert "standup" in response.messages[0].snippet
        assert [n.note_id for n in response.notes] == ["note-1"]
        assert [c.conversation_id for c in response.conversations] == ["conv-1"]

    async def test_special_chars_are_escaped_before_the_pattern(self) -> None:
        seen: dict[str, str] = {}

        async def _record(user_id: str, pattern: str):
            seen["pattern"] = pattern
            return SimpleNamespace(messages=[], conversations=[])

        with (
            patch(
                "app.services.search_service.conversation_repository.search",
                AsyncMock(side_effect=_record),
            ),
            patch(
                "app.services.search_service.note_repository.search_by_plaintext",
                AsyncMock(return_value=[]),
            ),
        ):
            await search_messages("standup (9:30)?", FAKE_USER.user_id)

        # An unescaped paren would reach Mongo as a regex group.
        assert seen["pattern"] == "standup\\ \\(9:30\\)\\?"


def _mcp_client(probe: dict, connect: object = None, oauth_url: str | None = None):
    client = SimpleNamespace(
        probe_connection=AsyncMock(return_value=probe),
        connect=AsyncMock(return_value=connect if connect is not None else []),
        update_integration_auth_status=AsyncMock(),
        build_oauth_auth_url=AsyncMock(return_value=oauth_url or "https://oauth.example/"),
    )
    return client


def _resolved():
    return SimpleNamespace(mcp_config=SimpleNamespace(server_url="https://mcp.example.com"))


class TestMcpConnectionMatrix:
    async def test_healthy_server_connects_and_counts_tools(self) -> None:
        client = _mcp_client({"requires_auth": False}, connect=["t1", "t2"])
        with (
            patch(f"{MCP_ENDPOINT}.get_mcp_client", AsyncMock(return_value=client)),
            patch(
                f"{MCP_ENDPOINT}.IntegrationResolver.resolve", AsyncMock(return_value=_resolved())
            ),
            patch(f"{MCP_ENDPOINT}.invalidate_user_integration_caches", AsyncMock()),
        ):
            response = await mcp_endpoint.test_mcp_connection("github", FAKE_USER)

        assert response.status == "connected"
        assert response.tools_count == 2
        client.connect.assert_awaited_once_with("github")

    async def test_probe_error_is_failed_without_connecting(self) -> None:
        client = _mcp_client({"error": "connection refused"})
        with (
            patch(f"{MCP_ENDPOINT}.get_mcp_client", AsyncMock(return_value=client)),
            patch(
                f"{MCP_ENDPOINT}.IntegrationResolver.resolve", AsyncMock(return_value=_resolved())
            ),
        ):
            response = await mcp_endpoint.test_mcp_connection("github", FAKE_USER)

        assert response.status == "failed"
        assert "refused" in (response.error or "")
        client.connect.assert_not_awaited()

    async def test_auth_required_returns_oauth_url_and_records_status(self) -> None:
        client = _mcp_client({"requires_auth": True, "auth_type": "oauth"})
        with (
            patch(f"{MCP_ENDPOINT}.get_mcp_client", AsyncMock(return_value=client)),
            patch(
                f"{MCP_ENDPOINT}.IntegrationResolver.resolve", AsyncMock(return_value=_resolved())
            ),
        ):
            response = await mcp_endpoint.test_mcp_connection("github", FAKE_USER)

        assert response.status == "requires_oauth"
        assert response.oauth_url == "https://oauth.example/"
        client.update_integration_auth_status.assert_awaited_once_with(
            "github", requires_auth=True, auth_type="oauth"
        )
        client.connect.assert_not_awaited()

    async def test_unknown_integration_is_404(self) -> None:
        with (
            patch(
                f"{MCP_ENDPOINT}.get_mcp_client",
                AsyncMock(return_value=_mcp_client({})),
            ),
            patch(f"{MCP_ENDPOINT}.IntegrationResolver.resolve", AsyncMock(return_value=None)),
        ):
            with pytest.raises(HTTPException) as err:
                await mcp_endpoint.test_mcp_connection("nope", FAKE_USER)
        assert err.value.status_code == 404


class TestMarketplaceCatalog:
    async def test_static_catalog_lists_with_custom_merged(self) -> None:
        with (
            patch(f"{MARKETPLACE}.get_all_mcp_tools", AsyncMock(return_value={})),
            patch(
                f"{MARKETPLACE}.integration_repository.list_public_custom",
                AsyncMock(return_value=[]),
            ),
        ):
            listing = await marketplace.get_all_integrations()

        assert listing.total > 0
        assert listing.total == len(listing.integrations)
        assert all(i.integration_id and i.name for i in listing.integrations)

    async def test_details_roundtrip_for_a_listed_id(self) -> None:
        with (
            patch(f"{MARKETPLACE}.get_all_mcp_tools", AsyncMock(return_value={})),
            patch(
                f"{MARKETPLACE}.integration_repository.list_public_custom",
                AsyncMock(return_value=[]),
            ),
            patch(f"{MARKETPLACE}.get_integration_tools", AsyncMock(return_value=[])),
        ):
            listing = await marketplace.get_all_integrations()
            listed_id = listing.integrations[0].integration_id
            details = await marketplace.get_integration_details(listed_id)

        assert details is not None
        assert details.integration_id == listed_id

    async def test_unknown_details_id_is_none(self) -> None:
        with (
            patch(f"{MARKETPLACE}.get_integration_tools", AsyncMock(return_value=[])),
            patch(f"{MARKETPLACE}.IntegrationResolver.resolve", AsyncMock(return_value=None)),
        ):
            assert await marketplace.get_integration_details("no-such-integration") is None

    async def test_category_filter_only_returns_that_category(self) -> None:
        with (
            patch(f"{MARKETPLACE}.get_all_mcp_tools", AsyncMock(return_value={})),
            patch(
                f"{MARKETPLACE}.integration_repository.list_public_custom",
                AsyncMock(return_value=[]),
            ),
        ):
            listing = await marketplace.get_all_integrations(category="productivity")

        assert all(i.category == "productivity" for i in listing.integrations)
