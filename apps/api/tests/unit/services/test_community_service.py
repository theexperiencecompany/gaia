"""Regex-injection hardening for the community-integration search fallback."""

import re
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.integrations.community_service import _search_community_integrations
from tests.unit.services.regex_helpers import collect_regex_values

_MOD = "app.services.integrations.community_service"


@pytest.mark.unit
async def test_mongo_fallback_escapes_regex_metacharacters() -> None:
    """When ChromaDB returns nothing, the Mongo fallback must feed a *literal*
    (escaped) query into ``$regex``. A raw metacharacter query would otherwise
    run as an attacker-controlled pattern against the public collection."""
    raw_query = "a.*(b|c)+[x]$"
    escaped = re.escape(raw_query)
    assert escaped != raw_query

    cursor = MagicMock()
    cursor.to_list = AsyncMock(return_value=[])
    collection = MagicMock()
    collection.count_documents = AsyncMock(return_value=0)
    collection.aggregate = MagicMock(return_value=cursor)

    with (
        patch(f"{_MOD}.search_public_integrations", AsyncMock(return_value=[])),
        patch(f"{_MOD}.integrations_collection", collection),
        patch(f"{_MOD}.build_creator_lookup_stages", return_value=[]),
        patch(f"{_MOD}.format_community_integrations", return_value=[]),
    ):
        await _search_community_integrations(raw_query, category="all", limit=10, offset=0)

    mongo_query = collection.count_documents.call_args[0][0]
    regex_values = collect_regex_values(mongo_query)

    assert regex_values, "expected the $regex fallback to be exercised"
    for value in regex_values:
        assert value == escaped
        assert value != raw_query
