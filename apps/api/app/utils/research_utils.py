"""Utility functions for the deep research tool."""

import hashlib
import json
import re
from typing import Any, Dict, List

from app.agents.llm.client import get_free_llm_chain, invoke_with_fallback
from shared.py.wide_events import log
from app.constants.cache import SIX_HOUR_TTL
from app.decorators.caching import Cacheable
from langchain_core.messages import HumanMessage


def build_research_cache_key(
    query: str, scope: str, focus_areas: List[str], depth: int
) -> str:
    content = f"{query}|{scope}|{'|'.join(sorted(focus_areas))}|{depth}"
    h = hashlib.sha256(content.encode()).hexdigest()[:16]
    return f"research:result:{h}"


@Cacheable(smart_hash=True, ttl=SIX_HOUR_TTL, namespace="research")
async def decompose_research_queries(
    query: str,
    scope: str,
    focus_areas_str: str,
    depth: int,
) -> List[str]:
    """Use a cheap LLM to generate diverse, targeted sub-queries for thorough coverage."""
    log.set(
        operation="decompose_research_queries",
        research_query=query,
        research_scope=scope,
        research_depth=depth,
    )
    n_queries = 3 + (depth - 1) * 3  # depth 1→3, 2→6, 3→9

    scope_text = f"\nScope/angle: {scope}" if scope else ""
    focus_text = f"\nFocus areas: {focus_areas_str}" if focus_areas_str else ""

    prompt = (
        f"You are a research strategist. Generate exactly {n_queries} highly specific, "
        f"diverse search queries for comprehensive research on the following topic.\n\n"
        f"Topic: {query}{scope_text}{focus_text}\n\n"
        f"Rules:\n"
        f"- Cover different angles: overview, technical details, recent developments, "
        f"expert opinions, statistics/data, comparisons, real-world examples\n"
        f"- Each query must be concise and optimized for a search engine\n"
        f"- No duplicate angles\n"
        f"- Return ONLY a valid JSON array of strings, nothing else\n\n"
        f'Example: ["query one", "query two", "query three"]'
    )

    try:
        llm_chain = get_free_llm_chain()
        response = await invoke_with_fallback(llm_chain, [HumanMessage(content=prompt)])
        content = str(response.content).strip()
        match = re.search(r"\[.*\]", content, re.DOTALL)
        if match:
            queries = json.loads(match.group())
            if not isinstance(queries, list):
                raise ValueError(f"Expected JSON array, got {type(queries).__name__}")
            normalized = [str(q).strip() for q in queries if q and str(q).strip()]
            valid = list(dict.fromkeys(normalized))[:n_queries]
            if valid:
                return valid
    except Exception as e:
        log.warning(f"Query decomposition LLM call failed: {e}")

    # Fallback: heuristic sub-queries matching n_queries contract (depth 1→3, 2→6, 3→9)
    base = [
        query,
        f"{query} overview",
        f"{query} key concepts",
    ]
    if depth >= 2:
        base += [
            f"{query} latest developments",
            f"{query} technical overview",
            f"{query} best practices",
        ]
    if depth >= 3:
        base += [
            f"{query} expert analysis",
            f"{query} case studies",
            f"{query} statistics and data",
        ]
    return base[:n_queries]


def rank_and_deduplicate_urls(
    search_results: List[Any], max_urls: int
) -> List[Dict[str, Any]]:
    """
    Merge results from multiple searches, rank by appearance frequency + relevance score.
    Returns deduplicated URL list sorted by combined relevance.
    """
    url_map: Dict[str, Dict[str, Any]] = {}

    for result in search_results:
        if isinstance(result, Exception) or not result:
            continue
        for item in result.get("results", []):
            if not isinstance(item, dict):
                continue
            url = item.get("url", "").strip()
            if not url or not url.startswith("http"):
                continue
            raw_score = item.get("score", 0.5)
            try:
                score = float(raw_score)
            except (TypeError, ValueError):
                score = 0.5
            if url in url_map:
                url_map[url]["score"] += score
                url_map[url]["appearances"] += 1
            else:
                url_map[url] = {
                    "url": url,
                    "title": item.get("title", ""),
                    "snippet": item.get("content", ""),
                    "score": score,
                    "appearances": 1,
                }

    ranked = sorted(
        url_map.values(),
        key=lambda x: x["appearances"] * 2 + x["score"],
        reverse=True,
    )
    return ranked[:max_urls]
