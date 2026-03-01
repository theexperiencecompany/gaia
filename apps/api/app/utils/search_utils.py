import asyncio
from typing import Optional

import html2text
import httpx
from app.config.loggers import search_logger as logger
from app.config.settings import settings
from app.constants.cache import ONE_HOUR_TTL
from app.decorators.caching import Cacheable
from app.utils.exceptions import FetchError
from bs4 import BeautifulSoup
from firecrawl import FirecrawlApp
from langgraph.config import get_stream_writer
from tavily import TavilyClient

_HTTPX_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

# Initialize clients with lazy loading
_tavily_client = None
_firecrawl_client = None


def get_tavily_client() -> TavilyClient:
    """Get or create Tavily client instance with lazy loading."""
    global _tavily_client
    if _tavily_client is None:
        if not settings.TAVILY_API_KEY:
            raise ValueError("TAVILY_API_KEY is not configured")
        _tavily_client = TavilyClient(api_key=settings.TAVILY_API_KEY)
        logger.info("Initialized Tavily client")
    return _tavily_client


def get_firecrawl_client() -> FirecrawlApp:
    """Get or create Firecrawl client instance with lazy loading."""
    global _firecrawl_client
    if _firecrawl_client is None:
        if not settings.FIRECRAWL_API_KEY:
            raise ValueError("FIRECRAWL_API_KEY is not configured")
        _firecrawl_client = FirecrawlApp(api_key=settings.FIRECRAWL_API_KEY)
        logger.info("Initialized Firecrawl client")
    return _firecrawl_client


@Cacheable(
    key_pattern="tavily:{search_topic}:{query}:{count}:{extra_params}",
    ttl=ONE_HOUR_TTL,
    namespace="search",
)
async def fetch_tavily_search(
    query: str,
    count: int,
    search_topic: str = "general",
    extra_params: Optional[dict] = None,
) -> dict:
    """
    Call Tavily API with Redis caching.

    Args:
        query: The search query.
        count: Number of results to return.
        search_topic: Type of search ("general", "news", "finance").
        extra_params: Additional search parameters.

    Returns:
        The search results as a dictionary, or an empty dict on error.
    """
    try:
        tavily = get_tavily_client()

        # Prepare search parameters with enhanced features
        search_params = {
            "query": query,
            "max_results": count,
            "topic": search_topic,
            "include_images": True,
            "include_favicon": True,
        }

        # Add extra parameters if provided
        if extra_params:
            search_params.update(extra_params)

        # Perform the search
        result = tavily.search(**search_params)
        logger.info(f"Fetched Tavily search results for query: {query}")

        return result
    except Exception as e:
        logger.error(f"Error calling Tavily API: {e}")
        return {}


@Cacheable(key_pattern="search:{query}:{count}", ttl=ONE_HOUR_TTL, namespace="search")
async def perform_search(query: str, count: int) -> dict:
    """
    Perform Tavily search and return comprehensive results.

    Args:
        query (str): The search query string.
        count (int): Number of results to fetch per category.

    Returns:
        dict: Formatted search results with web, news, images, and videos data.
    """
    try:
        # Perform general search with all features enabled
        general_data = await fetch_tavily_search(query, count, "general")

        # # Perform news search
        # news_data = await fetch_tavily_search(query, count, "news")

        return {
            "web": general_data.get("results", []),
            "news": [],
            "images": general_data.get("images", []),
            "answer": general_data.get("answer", ""),
            "query": query,
            "response_time": general_data.get("response_time", 0),
            "request_id": general_data.get("request_id", ""),
        }

    except Exception as e:
        logger.error(f"Search failed: {e}")
        return {
            "web": [],
            "news": [],
            "images": [],
            "videos": [],
            "answer": "",
            "query": query,
            "response_time": 0,
            "request_id": "",
        }


@Cacheable(
    key_pattern="firecrawl:{url}:{use_stealth}", ttl=ONE_HOUR_TTL, namespace="web"
)
async def fetch_with_firecrawl(url: str, use_stealth: bool = False) -> str:
    """
    Fetch webpage content using Firecrawl with stealth mode support.

    Args:
        url: The URL to scrape
        use_stealth: Whether to use stealth proxy mode

    Returns:
        The scraped content in markdown format
    """
    try:
        writer = get_stream_writer()
        writer({"progress": f"Fetching URL with Firecrawl: {url[:50]}..."})

        app = get_firecrawl_client()

        # First try with normal mode
        try:
            result = app.scrape(url, formats=["markdown"])

            # Handle the response - Firecrawl SDK returns a Document object
            if result and hasattr(result, "markdown") and result.markdown:
                writer({"progress": "Successfully fetched URL with Firecrawl"})
                return result.markdown
            else:
                raise FetchError("No markdown content returned from Firecrawl", url=url)

        except Exception as e:
            # If normal mode fails and we haven't tried stealth yet, retry with stealth
            if not use_stealth:
                error_msg = str(e).lower()
                if any(
                    status in error_msg
                    for status in ["401", "403", "500", "blocked", "bot", "timeout"]
                ):
                    writer(
                        {
                            "progress": "Normal mode failed, retrying with stealth mode..."
                        }
                    )

                    # Retry with stealth mode - use proxy parameter
                    result = app.scrape(url, formats=["markdown"], proxy="stealth")

                    if result and hasattr(result, "markdown") and result.markdown:
                        writer(
                            {"progress": "Successfully fetched URL with stealth mode"}
                        )
                        return result.markdown
                    else:
                        raise FetchError(
                            "No markdown content returned from Firecrawl stealth mode",
                            url=url,
                        )
            raise e

    except ValueError as ve:
        raise FetchError(f"Configuration error: {str(ve)}", url=url) from ve
    except Exception as e:
        raise FetchError(f"Firecrawl error: {str(e)}", url=url) from e


@Cacheable(key_pattern="crawl4ai:{url}", ttl=ONE_HOUR_TTL, namespace="web")
async def fetch_with_crawl4ai(url: str) -> str:
    """
    Fetch webpage content using crawl4ai (free, no API key required).
    Falls back from Firecrawl when that service is unavailable or blocked.
    """
    try:
        from crawl4ai import AsyncWebCrawler

        async with AsyncWebCrawler(verbose=False) as crawler:
            result = await asyncio.wait_for(crawler.arun(url=url), timeout=30.0)

        if result and result.markdown and result.markdown.strip():
            logger.info(f"crawl4ai successfully fetched: {url[:60]}")
            return result.markdown
        raise FetchError("crawl4ai returned empty content", url=url)
    except FetchError:
        raise
    except Exception as e:
        raise FetchError(f"crawl4ai error: {str(e)}", url=url) from e


@Cacheable(key_pattern="httpx:{url}", ttl=ONE_HOUR_TTL, namespace="web")
async def fetch_with_httpx(url: str) -> str:
    """
    Fetch webpage content using plain httpx + BeautifulSoup + html2text.
    Last-resort fallback — always available, no external service dependency.
    Works best for static pages; may miss JS-rendered content.
    """
    try:
        async with httpx.AsyncClient(
            timeout=15, follow_redirects=True, headers=_HTTPX_HEADERS
        ) as client:
            response = await client.get(url)
            response.raise_for_status()

        soup = BeautifulSoup(response.text, "lxml")

        # Strip non-content elements
        for tag in soup(
            ["script", "style", "nav", "footer", "aside", "iframe", "noscript", "head"]
        ):
            tag.decompose()

        # Prefer semantic main content containers
        content_node = (
            soup.find("main")
            or soup.find("article")
            or soup.find(id="content")
            or soup.find(id="main-content")
            or soup.find(class_="content")
            or soup.body
        )
        html_content = str(content_node) if content_node else str(soup)

        converter = html2text.HTML2Text()
        converter.ignore_links = False
        converter.ignore_images = True
        converter.body_width = 0
        markdown = converter.handle(html_content).strip()

        if not markdown:
            raise FetchError("httpx+BS4 returned empty content", url=url)

        logger.info(f"httpx fallback successfully fetched: {url[:60]}")
        return markdown[:60_000]  # Cap at 60KB
    except FetchError:
        raise
    except httpx.HTTPStatusError as e:
        raise FetchError(f"HTTP {e.response.status_code}", url=url) from e
    except Exception as e:
        raise FetchError(f"httpx error: {str(e)}", url=url) from e


async def fetch_page_resilient(url: str) -> str:
    """
    Resilient page fetcher with automatic 3-tier fallback chain:
      1. Firecrawl  — best quality, handles JS, markdown-native
      2. crawl4ai   — good JS support, free, no API key required
      3. httpx+BS4  — always available, static pages only

    Each tier is independently cached in Redis (1h TTL).
    Raises FetchError only if all three tiers fail.
    """
    errors: list[str] = []

    # Tier 1: Firecrawl
    try:
        return await fetch_with_firecrawl(url)
    except Exception as e:
        errors.append(f"firecrawl: {e}")
        logger.warning(f"Firecrawl failed for {url[:60]}, trying crawl4ai: {e}")

    # Tier 2: crawl4ai
    try:
        return await fetch_with_crawl4ai(url)
    except Exception as e:
        errors.append(f"crawl4ai: {e}")
        logger.warning(f"crawl4ai failed for {url[:60]}, trying httpx: {e}")

    # Tier 3: httpx + BeautifulSoup
    try:
        return await fetch_with_httpx(url)
    except Exception as e:
        errors.append(f"httpx: {e}")

    raise FetchError(
        f"All fetchers failed [{'; '.join(errors)}]",
        url=url,
    )


@Cacheable(key_pattern="ddg:{query}:{count}", ttl=ONE_HOUR_TTL, namespace="search")
async def search_with_duckduckgo(query: str, count: int = 5) -> dict:
    """
    Search using DuckDuckGo Lite (no API key required).
    Fallback when Tavily is unavailable or rate-limited.
    Returns results in the same shape as fetch_tavily_search.
    """
    try:
        async with httpx.AsyncClient(
            timeout=10, follow_redirects=True, headers=_HTTPX_HEADERS
        ) as client:
            response = await client.post(
                "https://lite.duckduckgo.com/lite/",
                data={"q": query},
            )
            response.raise_for_status()

        soup = BeautifulSoup(response.text, "lxml")
        results = []

        # DDG Lite returns results in <tr> rows with alternating classes
        for row in soup.select("tr.result-sponsored, tr:has(a.result-link)")[:count]:
            link = row.select_one("a.result-link") or row.select_one("a[href]")
            snippet_cell = row.find_next_sibling("tr")
            if not link:
                continue
            href = str(link.get("href", ""))
            if not href.startswith("http"):
                continue
            snippet = snippet_cell.get_text(strip=True) if snippet_cell else ""
            results.append(
                {
                    "url": href,
                    "title": link.get_text(strip=True),
                    "content": snippet,
                    "score": 0.5,
                }
            )

        logger.info(f"DuckDuckGo returned {len(results)} results for: {query[:60]}")
        return {"results": results}
    except Exception as e:
        logger.error(f"DuckDuckGo search failed: {e}")
        return {"results": []}
