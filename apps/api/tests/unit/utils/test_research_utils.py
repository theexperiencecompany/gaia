"""Unit tests for research query decomposition and URL ranking.

decompose_research_queries hits a real LLM — the tests mock the LLM seam
(ainvoke_llm) and pin both the JSON-parse path and the deterministic
heuristic fallback, plus the cache key and the URL ranker.
"""

from unittest.mock import AsyncMock, patch
from uuid import uuid4

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
        patch("app.utils.research_utils.get_helper_llm", return_value=object()),
    ):
        llm.return_value = response
        queries = await decompose_research_queries(query, "web", "", 1)

    assert queries == ["query one", "query two", "query three"]
    assert len(queries) == 3
    # The label becomes ``agent_name`` on the llm_call wide event, which is how
    # this lane's auxiliary COGS is told apart from every other one-shot helper.
    assert llm.await_args.kwargs["label"] == "research_queries"


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
