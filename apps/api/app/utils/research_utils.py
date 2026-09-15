"""Utility functions for the deep research tool."""

from collections.abc import Mapping, Sequence
import hashlib
import json
import re

from langchain_core.messages import HumanMessage
from pydantic import BaseModel

from app.agents.llm.client import ainvoke_llm, get_helper_llm
from app.constants.cache import SIX_HOUR_TTL
from app.constants.log_tags import LogTag
from app.decorators.caching import Cacheable
from app.utils.search.models import ResearchSearchResult
from shared.py.wide_events import log


class RankedUrl(BaseModel):
    """One deduplicated research source, ranked by how many searches surfaced it.

    Crosses the wire: the research tool spreads it into the ``research_data``
    frame's ``sources`` (with the fetched content layered on) and caches it.
    """

    url: str
    title: str
    snippet: str
    score: float
    appearances: int


def build_research_cache_key(query: str, scope: str, focus_areas: list[str], depth: int) -> str:
    content = f"{query}|{scope}|{'|'.join(sorted(focus_areas))}|{depth}"
    h = hashlib.sha256(content.encode()).hexdigest()[:16]
    return f"research:result:{h}"


@Cacheable(smart_hash=True, ttl=SIX_HOUR_TTL, namespace="research")
async def decompose_research_queries(
    query: str,
    scope: str,
    focus_areas_str: str,
    depth: int,
) -> list[str]:
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
        response = await ainvoke_llm(
            get_helper_llm(), [HumanMessage(content=prompt)], label="research_queries"
        )
        # ``.text`` flattens the message's content blocks to a string; ``.content``
        # may be a list (Gemini), whose repr would never parse as JSON.
        content = response.text.strip()
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
        log.warning(
            f"{LogTag.TOOL} Query decomposition LLM call failed",
            error=str(e),
            error_type=type(e).__name__,
        )

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
    search_results: Sequence[Mapping[str, object] | ResearchSearchResult | BaseException],
    max_urls: int,
) -> list[RankedUrl]:
    """Merge results from multiple searches, ranked by appearance frequency + relevance score.

    Returns a deduplicated URL list sorted by combined relevance. search_results is
    what asyncio.gather(..., return_exceptions=True) over search_for_research returns;
    a failed search rides along as its exception and is skipped.
    """
    url_map: dict[str, RankedUrl] = {}

    for result in search_results:
        if isinstance(result, BaseException):
            continue
        for item in ResearchSearchResult.model_validate(result).results:
            url = item.url.strip()
            if not url or not url.startswith("http"):
                continue
            if url in url_map:
                url_map[url].score += item.score
                url_map[url].appearances += 1
            else:
                url_map[url] = RankedUrl(
                    url=url,
                    title=item.title,
                    snippet=item.content,
                    score=item.score,
                    appearances=1,
                )

    ranked = sorted(
        url_map.values(),
        key=lambda x: x.appearances * 2 + x.score,
        reverse=True,
    )
    return ranked[:max_urls]
