"""Unit tests for the shared integration search both agent tiers run."""

from unittest.mock import AsyncMock, patch

from app.schemas.integrations.responses import (
    CommunityIntegrationItem,
    CommunityListResponse,
    MyIntegrationItem,
    MyIntegrationsResponse,
)
from app.services.integrations.integration_search import (
    match_my_integrations,
    match_public_integrations,
)

MODULE = "app.services.integrations.integration_search"
USER = "user-1"


def _mine(
    integration_id: str,
    *,
    name: str | None = None,
    description: str = "",
    category: str = "productivity",
    connected: bool = False,
    available: bool = True,
) -> MyIntegrationItem:
    return MyIntegrationItem(
        id=integration_id,
        name=name or integration_id.title(),
        description=description,
        category=category,
        source="platform",
        managed_by="composio",
        status="connected" if connected else "not_connected",
        available=available,
    )


def _public(integration_id: str) -> CommunityIntegrationItem:
    return CommunityIntegrationItem(
        integration_id=integration_id,
        slug=integration_id,
        name=integration_id,
        description="",
        category="productivity",
    )


def _catalogue(*items: MyIntegrationItem) -> AsyncMock:
    return AsyncMock(return_value=MyIntegrationsResponse(integrations=list(items)))


class TestMatchMyIntegrations:
    async def test_matches_on_id_name_category_or_description(self) -> None:
        mine = _catalogue(
            _mine("gmail", description="Read and send email", category="communication"),
            _mine("notion", description="Pages and notes"),
            _mine("linear", description="Issue tracking"),
        )
        with patch(f"{MODULE}.get_my_integrations", mine):
            by_description = await match_my_integrations(USER, "email")
            by_category = await match_my_integrations(USER, "communication")
            by_name = await match_my_integrations(USER, "Notion")

        mine.assert_awaited_with(USER)
        assert [i.id for i in by_description] == ["gmail"]
        assert [i.id for i in by_category] == ["gmail"]
        assert [i.id for i in by_name] == ["notion"]

    async def test_connected_integrations_come_first(self) -> None:
        mine = _catalogue(
            _mine("crm-a", category="crm"), _mine("crm-b", category="crm", connected=True)
        )
        with patch(f"{MODULE}.get_my_integrations", mine):
            matched = await match_my_integrations(USER, "crm")

        assert [i.id for i in matched] == ["crm-b", "crm-a"]

    async def test_unavailable_integrations_never_match(self) -> None:
        mine = _catalogue(_mine("gmail", available=False))
        with patch(f"{MODULE}.get_my_integrations", mine):
            assert await match_my_integrations(USER, "gmail") == []

    async def test_no_query_lists_everything_but_a_stopword_query_matches_nothing(self) -> None:
        mine = _catalogue(_mine("gmail"), _mine("notion"))
        with patch(f"{MODULE}.get_my_integrations", mine):
            everything = await match_my_integrations(USER, None)
            nothing = await match_my_integrations(USER, "the")

        assert [i.id for i in everything] == ["gmail", "notion"]
        assert nothing == []


class TestMatchPublicIntegrations:
    async def test_excludes_what_the_user_owns_case_insensitively_and_caps(self) -> None:
        marketplace = AsyncMock(
            return_value=CommunityListResponse(
                integrations=[_public("NOTION"), _public("stripe"), _public("hubspot")]
            )
        )
        with patch(f"{MODULE}.list_community_integrations", marketplace):
            matched = await match_public_integrations("crm", exclude_ids={"notion"}, limit=1)

        assert [i.integration_id for i in matched] == ["stripe"]

    async def test_over_fetches_by_the_excluded_count_so_exclusions_cannot_crowd_out_hits(
        self,
    ) -> None:
        marketplace = AsyncMock(return_value=CommunityListResponse(integrations=[]))
        with patch(f"{MODULE}.list_community_integrations", marketplace):
            await match_public_integrations("crm", exclude_ids={"a", "b", "c"}, limit=5)

        marketplace.assert_awaited_once_with(search="crm", limit=8)
