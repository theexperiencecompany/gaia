import asyncio
import hashlib
import json
import re
import time
from typing import Annotated, Any, Dict, List, Optional

from app.agents.llm.client import get_free_llm_chain, invoke_with_fallback
from app.config.loggers import chat_logger as logger
from app.constants.cache import ONE_HOUR_TTL, SIX_HOUR_TTL
from app.db.redis import get_cache, set_cache
from app.decorators import with_doc, with_rate_limiting
from app.decorators.caching import Cacheable
from app.templates.docstrings.research_tool_docs import DEEP_RESEARCH
from app.utils.chat_utils import get_user_id_from_config
from app.utils.search_utils import (
    fetch_with_crawl4ai,
    fetch_with_httpx,
    search_with_duckduckgo,
)
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.config import get_stream_writer

_RESEARCH_INSTRUCTIONS = (
    "You have full page content from multiple research sources. "
    "Write a LONG, DETAILED, COMPREHENSIVE response — do NOT summarize or be brief. "
    "The user explicitly requested deep research, so they expect depth and completeness, not a short overview. "
    "Cover every important aspect thoroughly: explain concepts in detail, include specific data points, "
    "statistics, examples, quotes, technical details, and nuances from the sources. "
    "Structure the response with clear headings and subheadings. Each section should be substantive — "
    "multiple paragraphs, not a single sentence. "
    "Reproduce key data, numbers, and specific findings directly from the sources rather than vaguely referencing them. "
    "Highlight agreements and contradictions across sources. "
    "Always cite with [1], [2] notation inline and include a full numbered reference list at the end. "
    "A good deep research response is typically 800–2000+ words depending on the topic complexity."
)


def _build_research_cache_key(
    query: str, scope: str, focus_areas: List[str], depth: int
) -> str:
    content = f"{query}|{scope}|{'|'.join(sorted(focus_areas))}|{depth}"
    h = hashlib.sha256(content.encode()).hexdigest()[:16]
    return f"research:result:{h}"


@Cacheable(smart_hash=True, ttl=SIX_HOUR_TTL, namespace="research")
async def _decompose_research_queries(
    query: str,
    scope: str,
    focus_areas_str: str,
    depth: int,
) -> List[str]:
    """Use a cheap LLM to generate diverse, targeted sub-queries for thorough coverage."""
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
        content = response.content.strip()
        match = re.search(r"\[.*\]", content, re.DOTALL)
        if match:
            queries = json.loads(match.group())
            valid = [str(q).strip() for q in queries if q and str(q).strip()]
            if valid:
                return valid
    except Exception as e:
        logger.warning(f"Query decomposition LLM call failed: {e}")

    # Fallback: heuristic sub-queries
    base = [query]
    if depth >= 2:
        base += [f"{query} latest developments", f"{query} technical overview"]
    if depth >= 3:
        base += [
            f"{query} expert analysis",
            f"{query} case studies",
            f"{query} statistics and data",
        ]
    return base


def _rank_and_deduplicate_urls(
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
            url = item.get("url", "").strip()
            if not url or not url.startswith("http"):
                continue
            score = float(item.get("score", 0.5))
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
        key=lambda x: (x["appearances"] * 2 + x["score"]),
        reverse=True,
    )
    return ranked[:max_urls]


@tool
@with_rate_limiting("deep_research")
@with_doc(DEEP_RESEARCH)
async def deep_research(
    config: RunnableConfig,
    query: Annotated[str, "The main research question or topic to investigate"],
    scope: Annotated[
        str,
        "Specific angle or focus (e.g. 'technical implementation', 'market trends', 'historical context')",
    ] = "",
    depth: Annotated[
        int,
        "Research depth: 1=quick (3 searches, 5 sources), 2=standard (6 searches, 10 sources), 3=deep (9 searches, 20 sources)",
    ] = 2,
    focus_areas: Annotated[
        List[str],
        "Specific subtopics or aspects to prioritize (e.g. ['performance', 'cost', 'adoption'])",
    ] = [],
) -> Dict[str, Any]:
    user_id = get_user_id_from_config(config)
    if not user_id:
        return {"error": "User authentication required", "data": None}

    writer = get_stream_writer()
    start_time = time.time()
    max_sources = 5 * depth  # 1→5, 2→10, 3→20

    # ── Phase 0: Full-result cache check ────────────────────────────────────
    cache_key = _build_research_cache_key(query, scope, focus_areas, depth)
    cached_result: Optional[Dict[str, Any]] = await get_cache(cache_key)
    if cached_result:
        writer({"progress": "Loaded research from cache!"})
        writer({"research_data": cached_result})
        return {
            **cached_result,
            "cached": True,
            "instructions": _RESEARCH_INSTRUCTIONS,
        }

    try:
        # ── Phase 1: Query decomposition ────────────────────────────────────
        writer({"progress": "Planning research strategy..."})
        focus_areas_str = " | ".join(focus_areas) if focus_areas else ""
        sub_queries = await _decompose_research_queries(
            query, scope, focus_areas_str, depth
        )
        writer(
            {
                "progress": f"Generated {len(sub_queries)} targeted search queries",
                "research_queries": sub_queries,
            }
        )

        # ── Phase 2: Parallel searches ────────────────────────────────────────
        writer({"progress": f"Running {len(sub_queries)} parallel searches..."})

        async def _resilient_search(q: str) -> dict:
            return await search_with_duckduckgo(q, count=5)

        search_results = await asyncio.gather(
            *[_resilient_search(q) for q in sub_queries],
            return_exceptions=True,
        )

        successful_searches = sum(
            True
            for r in search_results
            if not isinstance(r, BaseException) and r and r.get("results")
        )
        writer(
            {
                "progress": f"{successful_searches}/{len(sub_queries)} searches returned results"
            }
        )

        # ── Phase 3: Deduplicate + rank URLs ────────────────────────────────
        ranked_urls = _rank_and_deduplicate_urls(search_results, max_urls=max_sources)
        writer(
            {
                "progress": f"Found {len(ranked_urls)} unique sources — fetching full content..."
            }
        )

        if not ranked_urls:
            return {
                "error": "No sources found for the given query. Try broadening your search.",
                "query": query,
                "data": None,
            }

        # ── Phase 4: Parallel page fetches (bounded concurrency) ────────────
        # Fallback chain per URL: crawl4ai → httpx+BS4 → snippet
        semaphore = asyncio.Semaphore(5)
        fetch_counter = 0
        total_urls = len(ranked_urls)

        async def _bounded_fetch(url_info: Dict[str, Any]) -> Dict[str, Any]:
            nonlocal fetch_counter
            async with semaphore:
                url = url_info["url"]
                errors: list[str] = []

                # Tier 1: crawl4ai (free, no API key, handles JS)
                try:
                    content = await fetch_with_crawl4ai(url)
                    fetch_counter += 1
                    writer(
                        {"progress": f"Fetched source {fetch_counter}/{total_urls}..."}
                    )
                    return {**url_info, "content": content, "fetch_error": None}
                except Exception as e:
                    errors.append(f"crawl4ai: {e}")

                # Tier 2: httpx + BeautifulSoup (always available)
                try:
                    content = await fetch_with_httpx(url)
                    fetch_counter += 1
                    writer(
                        {"progress": f"Fetched source {fetch_counter}/{total_urls}..."}
                    )
                    return {**url_info, "content": content, "fetch_error": None}
                except Exception as e:
                    errors.append(f"httpx: {e}")

                # Tier 3: fall back to search snippet
                fetch_counter += 1
                snippet = url_info.get("snippet", "").strip()
                if snippet:
                    logger.warning(
                        f"All fetchers failed for {url[:60]}, using search snippet"
                    )
                    return {
                        **url_info,
                        "content": f"[Snippet only — full page unavailable]\n\n{snippet}",
                        "fetch_error": "; ".join(errors),
                    }
                return {**url_info, "content": None, "fetch_error": "; ".join(errors)}

        fetch_tasks = [_bounded_fetch(u) for u in ranked_urls]
        sources: List[Dict[str, Any]] = await asyncio.gather(
            *fetch_tasks, return_exceptions=False
        )

        valid_sources = [s for s in sources if s.get("content")]
        failed_count = len(sources) - len(valid_sources)

        elapsed = round(time.time() - start_time, 2)
        writer(
            {
                "progress": (
                    f"Research complete! {len(valid_sources)} sources fetched "
                    f"({failed_count} failed) in {elapsed}s"
                )
            }
        )

        # ── Build result ─────────────────────────────────────────────────────
        result: Dict[str, Any] = {
            "query": query,
            "scope": scope,
            "focus_areas": focus_areas,
            "sub_queries": sub_queries,
            "sources": valid_sources,
            "source_count": len(valid_sources),
            "depth": depth,
            "elapsed_seconds": elapsed,
            "error": None,
        }

        # Cache for 1 hour — searches and pages are individually cached longer
        await set_cache(cache_key, result, ttl=ONE_HOUR_TTL)

        writer({"research_data": result})

        return {
            **result,
            "cached": False,
            "instructions": _RESEARCH_INSTRUCTIONS,
        }

    except Exception as e:
        logger.error(f"Deep research error: {e}", exc_info=True)
        return {"error": str(e), "query": query, "data": None}
