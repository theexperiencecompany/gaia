from typing import Optional

from app.config.loggers import search_logger as logger
from app.config.settings import settings
from app.constants.cache import ONE_HOUR_TTL
from app.decorators.caching import Cacheable
from app.utils.exceptions import FetchError
from firecrawl import FirecrawlApp
from langgraph.config import get_stream_writer
from tavily import TavilyClient

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
