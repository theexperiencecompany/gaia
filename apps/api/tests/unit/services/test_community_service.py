"""Regex-injection hardening for the community-integration search fallback.

The escaping now lives in the repository's filter builder — a raw metacharacter
query must be fed to ``$regex`` as a *literal* (escaped) pattern, never run as an
attacker-controlled pattern against the public collection.
"""

import re
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.db.repositories.integrations import IntegrationsRepository
from app.schemas.integrations.responses import CommunityIntegrationItem
from app.services.integrations import community_service
from tests.unit.services.regex_helpers import collect_regex_values

_SVC = "app.services.integrations.community_service"


@pytest.mark.unit
def test_community_search_filter_escapes_regex_metacharacters() -> None:
    raw_query = "a.*(b|c)+[x]$"
    escaped = re.escape(raw_query)
    assert escaped != raw_query

    mongo_query = IntegrationsRepository._community_search_filter(raw_query, "all")
    regex_values = collect_regex_values(mongo_query)

    assert regex_values, "expected the $regex fallback to build regex conditions"
    for value in regex_values:
        assert value == escaped
        assert value != raw_query


def _hit(integration_id: str, category: str) -> SimpleNamespace:
    return SimpleNamespace(integration_id=integration_id, category=category)


def _as_items(rows: list[SimpleNamespace]) -> list[CommunityIntegrationItem]:
    """Stand-in for format_community_integrations, keeping id and category."""
    return [
        CommunityIntegrationItem(
            integration_id=r.integration_id,
            slug=r.integration_id,
            name=r.integration_id,
            description="",
            category=r.category,
        )
        for r in rows
    ]


@pytest.mark.unit
async def test_semantic_search_results_respect_the_category_filter() -> None:
    """A category filter must constrain semantic-search hits, not just the fallback.

    ChromaDB indexes only {"integration_id": ...} for public integrations, so the
    vector search cannot filter by category itself and returns hits from every
    category. Filtering therefore has to happen once the hits are hydrated from
    Mongo, or picking a category on the marketplace silently does nothing on the
    search path while working on the browse path right beside it.
    """
    hits = [{"integration_id": "int-a"}, {"integration_id": "int-b"}]
    hydrated = [_hit("int-a", "productivity"), _hit("int-b", "developer")]

    with (
        patch(f"{_SVC}.search_public_integrations", new=AsyncMock(return_value=hits)),
        patch(
            f"{_SVC}.integration_repository.community_by_ids",
            new=AsyncMock(return_value=hydrated),
        ),
        patch(f"{_SVC}.format_community_integrations", new=_as_items),
    ):
        result = await community_service._search_community_integrations(
            "notes", "productivity", limit=20, offset=0
        )

    assert [r.integration_id for r in result.integrations] == ["int-a"]
    assert result.total == 1


@pytest.mark.unit
async def test_semantic_search_category_all_keeps_every_hit() -> None:
    """ "all" is the no-filter sentinel, matching _community_search_filter."""
    hits = [{"integration_id": "int-a"}, {"integration_id": "int-b"}]
    hydrated = [_hit("int-a", "productivity"), _hit("int-b", "developer")]

    with (
        patch(f"{_SVC}.search_public_integrations", new=AsyncMock(return_value=hits)),
        patch(
            f"{_SVC}.integration_repository.community_by_ids",
            new=AsyncMock(return_value=hydrated),
        ),
        patch(f"{_SVC}.format_community_integrations", new=_as_items),
    ):
        result = await community_service._search_community_integrations(
            "notes", "all", limit=20, offset=0
        )

    assert [r.integration_id for r in result.integrations] == ["int-a", "int-b"]


@pytest.mark.unit
async def test_semantic_hits_all_filtered_out_falls_back_to_mongo() -> None:
    """Every hit in another category is the same situation as no hits at all.

    The Mongo path filters by category itself, so it can surface rows the vector
    search ranked below the cut. Returning an empty page instead would hide them.
    """
    hits = [{"integration_id": "int-b"}]
    hydrated = [_hit("int-b", "developer")]
    fallback = [_hit("int-c", "productivity")]

    with (
        patch(f"{_SVC}.search_public_integrations", new=AsyncMock(return_value=hits)),
        patch(
            f"{_SVC}.integration_repository.community_by_ids",
            new=AsyncMock(return_value=hydrated),
        ),
        patch(
            f"{_SVC}.integration_repository.count_community_search",
            new=AsyncMock(return_value=1),
        ),
        patch(
            f"{_SVC}.integration_repository.community_search",
            new=AsyncMock(return_value=fallback),
        ),
        patch(f"{_SVC}.format_community_integrations", new=_as_items),
    ):
        result = await community_service._search_community_integrations(
            "notes", "productivity", limit=20, offset=0
        )

    assert [r.integration_id for r in result.integrations] == ["int-c"]


@pytest.mark.unit
def test_community_search_filter_applies_category() -> None:
    with_category = IntegrationsRepository._community_search_filter("q", "developer")
    assert with_category["category"] == "developer"
    # "all" means no category constraint
    assert "category" not in IntegrationsRepository._community_search_filter("q", "all")
