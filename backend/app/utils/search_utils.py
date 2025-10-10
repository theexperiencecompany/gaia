import asyncio
from typing import Dict, Optional, TypedDict, Union

import httpx
from bs4 import BeautifulSoup
from langgraph.config import get_stream_writer
from playwright.async_api import async_playwright

from app.config.loggers import search_logger as logger
from app.config.settings import settings
from app.db.redis import ONE_HOUR_TTL, get_cache, set_cache
from app.utils.exceptions import FetchError

http_async_client = httpx.AsyncClient()

WEB_SEARCH_URL = "https://api.bing.microsoft.com/v7.0/search"
IMAGE_SEARCH_URL = "https://api.bing.microsoft.com/v7.0/images/search"
NEWS_SEARCH_URL = "https://api.bing.microsoft.com/v7.0/news/search"
VIDEO_SEARCH_URL = "https://api.bing.microsoft.com/v7.0/videos/search"


class PlaywrightResult(TypedDict):
    content: str
    screenshot: Optional[bytes]


async def fetch_endpoint(
    url: str, query: str, count: int, extra_params: Optional[dict] = None
) -> dict:
    """
    Generic function to call a Bing API endpoint with Redis caching.

    Args:
        url: The API endpoint.
        query: The search query.
        count: Number of results to return.
        extra_params: Additional query parameters, if needed.

    Returns:
        The JSON response as a dictionary, or an empty dict on error.
    """
    # Create a cache key using the endpoint URL, query, count, and extra parameters
    cache_key = f"bing:{url}:{query}:{count}:{str(extra_params)}"

    # Try to get cached result first
    cached_result = await get_cache(cache_key)
    if cached_result:
        return cached_result

    # If not in cache, make the API request
    headers = {"Ocp-Apim-Subscription-Key": settings.BING_API_KEY}
    params: Dict[str, Union[str, int]] = {"q": query, "count": count}
    if extra_params:
        params.update(extra_params)

    try:
        response = await http_async_client.get(url, headers=headers, params=params)
        response.raise_for_status()
        result = response.json()

        # Cache the result (expires in 1 hour)
        await set_cache(cache_key, result, ONE_HOUR_TTL)
        logger.info(f"Cached search results for query: {query}")

        return result
    except httpx.HTTPStatusError as http_err:
        logger.error(f"HTTP error from {url}: {http_err}")
    except httpx.RequestError as req_err:
        logger.error(f"Request error from {url}: {req_err}")
    except Exception as e:
        logger.error(f"Unexpected error from {url}: {e}")
    return {}


def merge_web_results(data: dict) -> list:
    """Extract and merge web search results."""
    return [
        {
            "title": item.get("name", "No Title"),
            "url": item.get("url", "#"),
            "snippet": item.get("snippet", ""),
            "source": item.get("displayUrl", "Unknown"),
            "date": item.get("dateLastCrawled"),
        }
        for item in data.get("webPages", {}).get("value", [])
    ]


def merge_image_results(data: dict) -> list:
    """Extract and merge image search results."""
    return [
        {
            "title": item.get("name", "No Title"),
            "url": item.get("contentUrl", "#"),
            "thumbnail": item.get("thumbnailUrl", ""),
            "source": item.get("hostPageUrl", "Unknown"),
        }
        for item in data.get("value", [])
    ]


def merge_news_results(data: dict) -> list:
    """Extract and merge news search results."""
    return [
        {
            "title": item.get("name", "No Title"),
            "url": item.get("url", "#"),
            "snippet": item.get("description", ""),
            "source": (item.get("provider") or [{}])[0].get("name", "Unknown"),
            "date": item.get("datePublished"),
        }
        for item in data.get("value", [])
    ]


def merge_video_results(data: dict) -> list:
    """Extract and merge video search results."""
    return [
        {
            "title": item.get("name", "No Title"),
            "url": item.get("contentUrl", "#"),
            "thumbnail": item.get("thumbnailUrl", ""),
            "source": (item.get("publisher") or [{}])[0].get("name", "Unknown"),
        }
        for item in data.get("value", [])
    ]


async def perform_search(
    query: str,
    count: int,
    web: bool = True,
    images: bool = True,
    news: bool = True,
    videos: bool = True,
) -> dict:
    """
    Perform concurrent Bing searches across multiple categories (web, images, news, videos).

    Args:
        query (str): The search query string.
        count (int): Number of results to fetch per category.
        web (bool, optional): Whether to perform a web search. Defaults to True.
        images (bool, optional): Whether to perform an image search. Defaults to True.
        news (bool, optional): Whether to perform a news search. Defaults to True.
        videos (bool, optional): Whether to perform a video search. Defaults to True.

    Returns:
        dict: A dictionary with keys as enabled search types ('web', 'images', 'news', 'videos')
              and values as merged results from corresponding search category.
    """

    # Mapping of search type to its enable flag, URL, and merging function
    search_options = {
        "web": (web, WEB_SEARCH_URL, merge_web_results),
        "images": (images, IMAGE_SEARCH_URL, merge_image_results),
        "news": (news, NEWS_SEARCH_URL, merge_news_results),
        "videos": (videos, VIDEO_SEARCH_URL, merge_video_results),
    }

    tasks, keys, merge_funcs = [], [], []

    # Prepare async tasks for all enabled search types
    for key, (enabled, url, merge_func) in search_options.items():
        if enabled:
            tasks.append(fetch_endpoint(url, query, count))  # async API request
            keys.append(key)  # search type name
            merge_funcs.append(merge_func)  # corresponding result merge function

    # Execute all API requests concurrently
    results = await asyncio.gather(*tasks)

    # Merge results using their corresponding merge functions and return them in a dictionary
    return {keys[i]: merge_funcs[i](results[i]) for i in range(len(results))}


def format_results_for_llm(results, result_type="Search Results"):
    """
    Formats a list of result dictionaries into a clean, structured format for an LLM.

    Args:
        results (list): List of result dictionaries containing 'title', 'url', 'snippet', 'source', and 'date'.
        result_type (str): Label for the results (e.g., "Web Results", "News Results").

    Returns:
        str: Formatted string suitable for an LLM response.
    """
    if not results:
        return "No relevant results found."

    formatted_output = f"{result_type}:\n\n"

    for index, result in enumerate(results, start=1):
        formatted_output += (
            f"{index}. **{result.get('title', 'No Title')}**\n"
            f"   - Source: {result.get('source', 'Unknown')}\n"
            f"   - Date: {result.get('date', 'N/A')}\n"
            f"   - Snippet: {result.get('snippet', 'No snippet available')}\n"
            f"   - [URL]({result.get('url', '#')})\n\n"
        )

    return formatted_output


async def fetch_with_httpx(url: str) -> str:
    """Fetches webpage content using httpx (fast for static pages)."""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=10)
            response.raise_for_status()
            return response.text
    except httpx.HTTPStatusError as http_err:
        raise FetchError(
            f"HTTP error: {http_err}",
            status_code=http_err.response.status_code,
            url=url,
        ) from http_err
    except httpx.RequestError as req_err:
        raise FetchError(f"Request error: {req_err}", url=url) from req_err
    except Exception as e:
        raise FetchError(f"Unexpected error: {type(e).__name__}: {e}", url=url) from e


async def fetch_with_playwright(
    url: str,
    wait_time: int = 3,
    wait_for_element: str = "body",
    take_screenshot: bool = False,
) -> PlaywrightResult:
    """Fetches webpage content using Playwright with optimizations.

    Args:
        url: URL to fetch
        wait_time: Time to wait after page load
        wait_for_element: Selector to wait for
        take_screenshot: Whether to take a screenshot of the page

    Returns:
        Dictionary containing HTML content and optionally screenshot data
    """
    browser = None
    page = None
    context = None

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)

            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            )
            page = await context.new_page()

            async def intercept_requests(route):
                if route.request.resource_type in [
                    "image",
                    "stylesheet",
                    "font",
                    "media",
                    "xhr",
                ]:
                    await route.abort()
                else:
                    await route.continue_()

            # Only intercept requests if not taking screenshot to ensure visuals load properly
            if not take_screenshot:
                await page.route("**/*", intercept_requests)

            await page.goto(url, wait_until="domcontentloaded", timeout=15000)
            await page.wait_for_selector(wait_for_element, timeout=15000)
            await page.wait_for_timeout(wait_time * 1000)
            content = await page.content()

            result: PlaywrightResult = {"content": content, "screenshot": None}

            # Take screenshot if requested
            if take_screenshot:
                try:
                    writer = get_stream_writer()

                    writer(
                        {
                            "progress": f"Deep Research: Taking screenshot of page {url:20}..."
                        }
                    )

                    # Set viewport to a reasonable size
                    await page.set_viewport_size({"width": 1280, "height": 1024})
                    # Wait extra time for visuals to load when taking screenshots
                    await page.wait_for_timeout(2000)

                    # Make sure we get bytes data from the screenshot
                    screenshot_bytes = await page.screenshot(
                        type="jpeg", quality=90, full_page=True
                    )

                    # Verify it's actually bytes before setting in result
                    if screenshot_bytes and isinstance(screenshot_bytes, bytes):
                        result["screenshot"] = screenshot_bytes

                except Exception as screenshot_error:
                    logger.error(f"Error taking screenshot: {screenshot_error}")
                    # Don't add screenshot to result if there was an error

            await page.close()
            await context.close()
            await browser.close()
            return result

    except Exception as e:
        logger.error(f"Unexpected error: {type(e).__name__}: {e}")
        if page and not page.is_closed():
            await page.close()
        if context:
            await context.close()
        # if browser and not browser.is_closed():
        # await browser.close()
        raise FetchError(f"Unexpected error: {type(e).__name__}") from e


async def extract_text(html: str) -> str:
    """Extracts and cleans text from HTML content."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in ["script", "style", "nav", "footer", "iframe", "noscript"]:
        for element in soup.find_all(tag):
            element.extract()

    text = soup.get_text(separator="\n", strip=True)
    lines = (line.strip() for line in text.splitlines())
    chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
    content = "\n".join(chunk for chunk in chunks if chunk)
    return content


async def perform_fetch(url: str, use_playwright: bool = True) -> str:
    """Fetches webpage content using either httpx or Playwright based on `use_playwright`."""
    try:
        writer = get_stream_writer()
        writer({"progress": f"Fetching URL: '{url:20}'..."})

        result = await (
            fetch_with_playwright(url) if use_playwright else fetch_with_httpx(url)
        )

        writer({"progress": f"Successfully fetched URL '{url:20}'!"})

        # Handle different return types from the fetch functions
        content: str = str(
            result.get("content") if isinstance(result, dict) else result
        )
        return await extract_text(content or "Error: Could not fetch content.")
    except FetchError as e:
        return f"[ERROR] {e}"
