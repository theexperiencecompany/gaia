"""Unit tests for research query decomposition and URL ranking.

decompose_research_queries hits a real LLM — the tests mock the LLM seam
(ainvoke_llm) and pin both the JSON-parse path and the deterministic
heuristic fallback, plus the cache key and the URL ranker.
"""

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.utils.research_utils import (
    build_research_cache_key,
    decompose_research_queries,
    rank_and_deduplicate_urls,
)


def test_cache_key_is_stable_and_scope_aware() -> None:
    assert build_research_cache_key("q", "web", ["b", "a"], 2) == (
        build_research_cache_key("q", "web", ["a", "b"], 2)
    )
    assert build_research_cache_key("q", "web", ["a"], 2) != (
        build_research_cache_key("q", "web", ["a"], 3)
    )


async def test_decompose_parses_llm_json_response() -> None:
    response = AsyncMock()
    response.text = '["query one", "query two", "query three"]'
    query = f"unique-llm-path-{uuid4()}"
    with (
        patch("app.utils.research_utils.ainvoke_llm", new_callable=AsyncMock) as llm,
        patch("app.utils.research_utils.get_default_llm", return_value=object()),
    ):
        llm.return_value = response
        queries = await decompose_research_queries(query, "web", "", 1)

    assert queries == ["query one", "query two", "query three"]
    assert len(queries) == 3


async def test_decompose_falls_back_to_heuristics_when_llm_fails() -> None:
    query = f"unique-fallback-path-{uuid4()}"
    with patch("app.utils.research_utils.ainvoke_llm", new_callable=AsyncMock) as llm:
        llm.side_effect = RuntimeError("llm down")
        queries = await decompose_research_queries(query, "", "", 2)

    assert queries == [
        query,
        f"{query} overview",
        f"{query} key concepts",
        f"{query} latest developments",
        f"{query} technical overview",
        f"{query} best practices",
    ]


def test_rank_and_deduplicate_urls() -> None:
    results = [
        {"results": [{"url": "https://a.com", "title": "A", "score": "0.8"}]},
        {"results": [{"url": "https://a.com", "title": "A", "score": 0.9}]},
        {"results": [{"url": "not-a-url", "title": "skip"}]},
        Exception("search failed"),
    ]
    ranked = rank_and_deduplicate_urls(results, max_urls=1)

    assert len(ranked) == 1
    assert ranked[0]["url"] == "https://a.com"
    assert ranked[0]["appearances"] == 2
    # Repeat appearances accumulate the provider scores rather than replacing
    # them — string and float scores both count.
    assert ranked[0]["score"] == pytest.approx(1.7)


def test_rank_orders_by_appearances_then_score() -> None:
    """The sort key is appearances*2 + score, so a twice-seen URL outranks a higher-scored one."""
    results = [
        {"results": [{"url": "https://twice.com", "score": 0.1}]},
        {"results": [{"url": "https://twice.com", "score": 0.1}]},
        {"results": [{"url": "https://once.com", "score": 0.9}]},
    ]
    ranked = rank_and_deduplicate_urls(results, max_urls=10)

    assert [r["url"] for r in ranked] == ["https://twice.com", "https://once.com"]


def test_rank_lets_strong_relevance_outweigh_one_extra_appearance() -> None:
    """Appearances are worth two points each, so accumulated relevance still wins
    when the rival is only one appearance ahead but barely relevant."""
    strong = [{"url": "https://strong.com", "score": 0.9}]
    weak = [{"url": "https://weak.com", "score": 0.05}]
    results = [
        *({"results": strong} for _ in range(3)),  # 3*2 + 2.7 = 8.7
        *({"results": weak} for _ in range(4)),  # 4*2 + 0.2 = 8.2
    ]
    ranked = rank_and_deduplicate_urls(results, max_urls=10)

    assert [r["url"] for r in ranked] == ["https://strong.com", "https://weak.com"]
    assert [r["appearances"] for r in ranked] == [3, 4]


def test_rank_skips_malformed_results_and_keeps_the_rest() -> None:
    """An empty or malformed payload is skipped, not crashed on, and does not stop the scan."""
    results = [
        None,
        {},
        {"results": "not-a-list"},
        {"results": [{"url": "https://good.com", "title": "T", "content": "C", "score": 0.4}]},
    ]
    ranked = rank_and_deduplicate_urls(results, max_urls=10)

    assert ranked == [
        {
            "url": "https://good.com",
            "title": "T",
            "snippet": "C",
            "score": 0.4,
            "appearances": 1,
        }
    ]


def test_rank_defaults_an_unusable_score_to_one_half() -> None:
    """A score float() cannot read falls back to 0.5, the same as an absent one."""
    results = [
        {"results": [{"url": "https://a.com", "score": {"nested": 1}}]},
        {"results": [{"url": "https://b.com", "score": "not-a-number"}]},
        {"results": [{"url": "https://c.com"}]},
    ]
    ranked = rank_and_deduplicate_urls(results, max_urls=10)

    assert {r["url"]: r["score"] for r in ranked} == {
        "https://a.com": 0.5,
        "https://b.com": 0.5,
        "https://c.com": 0.5,
    }
