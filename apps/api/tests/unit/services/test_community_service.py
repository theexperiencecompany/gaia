"""Regex-injection hardening for the community-integration search fallback.

The escaping now lives in the repository's filter builder — a raw metacharacter
query must be fed to ``$regex`` as a *literal* (escaped) pattern, never run as an
attacker-controlled pattern against the public collection.
"""

import re

import pytest

from app.db.repositories.integrations import IntegrationsRepository
from tests.unit.services.regex_helpers import collect_regex_values


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


@pytest.mark.unit
def test_community_search_filter_applies_category() -> None:
    with_category = IntegrationsRepository._community_search_filter("q", "developer")
    assert with_category["category"] == "developer"
    # "all" means no category constraint
    assert "category" not in IntegrationsRepository._community_search_filter("q", "all")
