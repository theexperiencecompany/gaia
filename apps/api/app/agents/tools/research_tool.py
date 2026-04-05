import asyncio
import time
from typing import Annotated, Any, Dict, List, Optional

from app.constants.cache import ONE_HOUR_TTL
from app.constants.search import (
    CRAWL4AI_PAGE_TIMEOUT_MS,
    DEEP_RESEARCH_CRAWL4AI_BATCH_TIMEOUT_SECONDS,
    DEEP_RESEARCH_CRAWL4AI_SEMAPHORE_COUNT,
    DEEP_RESEARCH_FALLBACK_SEMAPHORE_COUNT,
)
from app.db.redis import get_cache, set_cache
from app.decorators import with_doc, with_rate_limiting
from app.templates.docstrings.research_tool_docs import (
    DEEP_RESEARCH,
    RESEARCH_INSTRUCTIONS,
)
from app.utils.chat_utils import get_user_id_from_config
from app.utils.crawl4ai_utils import batch_fetch_with_crawl4ai
from app.utils.research_utils import (
    build_research_cache_key,
    decompose_research_queries,
    rank_and_deduplicate_urls,
)
from app.utils.search_utils import fetch_with_httpx, search_with_duckduckgo
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.config import get_stream_writer
from shared.py.wide_events import log


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
        Optional[List[str]],
        "Specific subtopics or aspects to prioritize (e.g. ['performance', 'cost', 'adoption'])",
    ] = None,
) -> Dict[str, Any]:
    log.set(tool={"name": "deep_research", "action": "research"})
    focus_areas = focus_areas or []
    user_id = get_user_id_from_config(config)
    if not user_id:
        return {"error": "User authentication required", "data": None}

    writer = get_stream_writer()
    start_time = time.time()
    if depth not in (1, 2, 3):
        return {
            "error": "Invalid depth. Use 1 (quick), 2 (standard), or 3 (deep).",
            "query": query,
            "data": None,
        }
    max_sources_by_depth = {1: 5, 2: 10, 3: 20}
    max_sources = max_sources_by_depth[depth]

    # ── Phase 0: Full-result cache check ────────────────────────────────────
    cache_key = build_research_cache_key(query, scope, focus_areas, depth)
    cached_result: Optional[Dict[str, Any]] = await get_cache(cache_key)
    if cached_result:
        writer({"progress": "Loaded research from cache!"})
        writer({"research_data": cached_result})
        return {
            **cached_result,
            "cached": True,
            "instructions": RESEARCH_INSTRUCTIONS,
        }

    try:
        # ── Phase 1: Query decomposition ────────────────────────────────────
        writer({"progress": "Planning research strategy..."})
        focus_areas_str = " | ".join(focus_areas) if focus_areas else ""
        sub_queries = await decompose_research_queries(
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
            1 for r in search_results if isinstance(r, dict) and r.get("results")
        )
        writer(
            {
                "progress": f"{successful_searches}/{len(sub_queries)} searches returned results"
            }
        )

        # ── Phase 3: Deduplicate + rank URLs ────────────────────────────────
        ranked_urls = rank_and_deduplicate_urls(search_results, max_urls=max_sources)
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

        # ── Phase 4: Batch crawl4ai fetch + bounded fallback fetches ─────────
        writer({"progress": "Fetching sources..."})
        urls_to_fetch = [u["url"] for u in ranked_urls]
        crawl4ai_contents, crawl4ai_errors = await batch_fetch_with_crawl4ai(
            urls_to_fetch,
            page_timeout_ms=CRAWL4AI_PAGE_TIMEOUT_MS,
            total_timeout_seconds=DEEP_RESEARCH_CRAWL4AI_BATCH_TIMEOUT_SECONDS,
            semaphore_count=DEEP_RESEARCH_CRAWL4AI_SEMAPHORE_COUNT,
            context_name="crawl4ai",
        )

        semaphore = asyncio.Semaphore(DEEP_RESEARCH_FALLBACK_SEMAPHORE_COUNT)
        fetch_counter = 0
        total_urls = len(ranked_urls)

        async def _bounded_fetch(url_info: Dict[str, Any]) -> Dict[str, Any]:
            nonlocal fetch_counter
            async with semaphore:
                url = url_info["url"]
                errors: list[str] = []

                batch_content = crawl4ai_contents.get(url)
                if batch_content and batch_content.strip():
                    fetch_counter += 1
                    writer(
                        {"progress": f"Fetched source {fetch_counter}/{total_urls}..."}
                    )
                    return {**url_info, "content": batch_content, "fetch_error": None}

                crawl_error = crawl4ai_errors.get(url)
                if crawl_error:
                    errors.append(f"crawl4ai: {crawl_error}")
                else:
                    errors.append("crawl4ai: returned no content")

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
                    log.warning(
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

        # Only cache when we have content — avoid masking transient fetch failures
        if valid_sources:
            await set_cache(cache_key, result, ttl=ONE_HOUR_TTL)

        writer({"research_data": result})

        return {
            **result,
            "cached": False,
            "instructions": RESEARCH_INSTRUCTIONS,
        }

    except Exception as e:
        log.error(f"Deep research error: {e}", exc_info=True)
        return {"error": str(e), "query": query, "data": None}
