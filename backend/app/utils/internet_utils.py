import asyncio
import re
import time
from typing import Any, Dict, Optional
from urllib.parse import urljoin, urlparse

from fastapi import HTTPException, status
import httpx
from bs4 import BeautifulSoup
from langgraph.config import get_stream_writer

from app.config.loggers import search_logger as logger
from app.db.mongodb.collections import (
    search_urls_collection,
)
from app.db.redis import get_cache, set_cache
from app.db.utils import serialize_document
from app.models.search_models import URLResponse
from app.services.search_service import (
    CACHE_EXPIRY,
    MAX_CONTENT_LENGTH,
    MAX_TOTAL_CONTENT,
    URL_TIMEOUT,
)
from app.utils.search_utils import (
    extract_text,
    fetch_with_playwright,
    perform_search,
)
from app.utils.storage_utils import upload_screenshot_to_cloudinary


def is_valid_url(url: str) -> bool:
    """
    Validate if a URL is well-formed and uses an acceptable protocol.

    Args:
        url (str): The URL to validate

    Returns:
        bool: True if URL is valid, False otherwise
    """
    try:
        parsed = urlparse(url)
        # Check for acceptable protocols
        if parsed.scheme not in ("http", "https"):
            return False
        # Check for presence of netloc (domain)
        if not parsed.netloc:
            return False
        # Reject IP addresses (basic check)
        if re.match(r"^\d+\.\d+\.\d+\.\d+$", parsed.netloc):
            logger.warning(f"IP address URL rejected: {url}")
            return False
        return True
    except Exception:
        return False


async def get_cached_webpage_content(url: str) -> Optional[Dict[str, Any]]:
    """
    Try to get cached webpage content.

    Args:
        url (str): The URL to fetch from cache

    Returns:
        Optional[Dict[str, Any]]: Cached content or None if not in cache
    """
    cache_key = f"webpage_content:{url}"
    try:
        cached_data = await get_cache(cache_key)
        if cached_data:
            return cached_data
    except Exception as e:
        logger.error(f"Error checking cache for {url}: {e}")
    return None


async def save_webpage_cache(url: str, content: str, markdown_content: str) -> None:
    """
    Save webpage content to cache.

    Args:
        url (str): The URL of the webpage
        content (str): The raw text content
        markdown_content (str): The markdown-formatted content
    """
    cache_key = f"webpage_content:{url}"
    cache_data = {
        "url": url,
        "content": content,
        "markdown_content": markdown_content,
        "timestamp": time.time(),
    }
    try:
        await set_cache(cache_key, cache_data, CACHE_EXPIRY)
        logger.info(f"Cached content for URL: {url}")
    except Exception as e:
        logger.error(f"Error caching content for {url}: {e}")


async def fetch_and_process_url(
    url: str, max_length: int = MAX_CONTENT_LENGTH, take_screenshot: bool = False
) -> Dict[str, Any]:
    """
    Fetch and process a single URL with error handling, validation and caching.

    Args:
        url (str): The URL to fetch
        max_length (int): Maximum content length to return
        take_screenshot (bool): Whether to take a screenshot of the page

    Returns:
        Dict[str, Any]: Dictionary with processed content and metadata
    """
    # Check URL validity
    if not is_valid_url(url):
        logger.warning(f"Invalid URL format: {url}")
        return {
            "url": url,
            "error": "Invalid URL format",
            "content": "",
            "markdown_content": "",
        }

    writer = get_stream_writer()

    writer({"progress": f"Deep Research: Fetching url {url:20}..."})

    # Try to get cached content
    cached_content = await get_cached_webpage_content(url)
    if cached_content:
        return {
            "url": url,
            "content": cached_content.get("content", ""),
            "markdown_content": cached_content.get("markdown_content", ""),
            "screenshot_url": cached_content.get("screenshot_url"),
            "from_cache": True,
        }

    # Fetch new content with proper error handling
    try:
        if take_screenshot:
            logger.info(f"Fetching {url} with screenshot")
            result = await fetch_with_playwright(url=url, take_screenshot=True)

            writer({"progress": f"Deep Research: Processing page {url:20}..."})

            html_content = result.get("content", "")
            screenshot_bytes = result.get("screenshot")

            # Process the HTML content
            soup = BeautifulSoup(html_content, "html.parser")

            for element in soup(
                [
                    "script",
                    "style",
                    "nav",
                    "footer",
                    "iframe",
                    "noscript",
                    "header",
                    "aside",
                    "object",
                    "embed",
                    "video",
                    "audio",
                    "picture",
                    "source",
                    "link",
                    "meta",
                    "svg",
                    "canvas",
                    "ins",
                    "del",
                ]
            ):
                element.extract()

            # Get text content
            text = soup.get_text(separator="\n", strip=True)

            # Process text
            lines = (line.strip() for line in text.splitlines())
            chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
            content = "\n".join(chunk for chunk in chunks if chunk)

            # Truncate if needed
            if len(content) > max_length:
                content = content[:max_length] + "...[content truncated]"

            # Convert to markdown
            markdown_content = await convert_to_markdown(content)

            # Upload screenshot to Cloudinary if available and is bytes
            screenshot_url = None
            if screenshot_bytes and isinstance(screenshot_bytes, bytes):
                writer({"progress": "Deep Research: Uploading Screenshot..."})

                screenshot_url = await upload_screenshot_to_cloudinary(
                    screenshot_bytes, url
                )
            else:
                logger.info("No screenshot bytes available for upload")

            writer({"progress": "Deep Research Completed!"})

            # Cache the result with screenshot URL
            cache_data = {
                "url": url,
                "content": content,
                "markdown_content": markdown_content,
                "screenshot_url": screenshot_url,
                "timestamp": time.time(),
            }

            cache_key = f"webpage_content:{url}"
            await set_cache(cache_key, cache_data, CACHE_EXPIRY)

            return {
                "url": url,
                "content": content,
                "markdown_content": markdown_content,
                "screenshot_url": screenshot_url,
                "from_cache": False,
            }
        else:
            # Use standard httpx fetch when screenshots aren't needed
            async with httpx.AsyncClient(
                follow_redirects=True,
                timeout=URL_TIMEOUT,
                headers={"User-Agent": "Mozilla/5.0 GAIA Web Research Bot"},
            ) as client:
                response = await client.get(url)
                response.raise_for_status()

                # Check content type - reject non-text content
                content_type = response.headers.get("content-type", "")
                if not content_type.startswith(
                    (
                        "text/",
                        "application/json",
                        "application/xml",
                        "application/xhtml+xml",
                    )
                ):
                    return {
                        "url": url,
                        "error": f"Unsupported content type: {content_type}",
                        "content": "",
                        "markdown_content": "",
                    }

                content = await extract_text(response.text)

                if len(content) > max_length:
                    content = content[:max_length] + "...[content truncated]"

                markdown_content = await convert_to_markdown(content)

                await save_webpage_cache(url, content, markdown_content)

                return {
                    "url": url,
                    "content": content,
                    "markdown_content": markdown_content,
                    "from_cache": False,
                }
    except httpx.TimeoutException:
        logger.error(f"Timeout fetching {url}")
        return {
            "url": url,
            "error": "Request timed out",
            "content": "",
            "markdown_content": "",
        }
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error {e.response.status_code} fetching {url}: {e}")
        return {
            "url": url,
            "error": f"HTTP error: {e.response.status_code}",
            "content": "",
            "markdown_content": "",
        }
    except httpx.RequestError as e:
        logger.error(f"Request error fetching {url}: {e}")
        return {
            "url": url,
            "error": f"Request error: {str(e)}",
            "content": "",
            "markdown_content": "",
        }
    except Exception as e:
        logger.error(f"Unexpected error fetching {url}: {e}")
        return {
            "url": url,
            "error": f"Error: {str(e)}",
            "content": "",
            "markdown_content": "",
        }


async def fetch_url_metadata(url: str) -> URLResponse:
    """Fetch metadata for a URL, with caching and database fallback."""
    if not is_valid_url(url):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid URL provided.",
        )

    cache_key = f"url_metadata:{url}"
    metadata = await get_cache(cache_key) or await search_urls_collection.find_one(
        {"url": url}
    )

    if metadata:
        return URLResponse(**metadata)

    metadata = await scrape_url_metadata(url)
    await search_urls_collection.insert_one(metadata)
    await set_cache(cache_key, serialize_document(metadata), 864000)

    return URLResponse(**metadata)


async def scrape_url_metadata(url: str) -> dict:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(url, follow_redirects=True)
            response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")

        def to_absolute(relative_url: str) -> str | None:
            if not relative_url:
                return None
            parsed = urlparse(relative_url)
            if parsed.scheme in ["http", "https"]:
                return relative_url
            return urljoin(url, relative_url)

        def get_attr_value(tag, attr_name: str) -> str | None:
            """Safely get attribute value from a BeautifulSoup tag."""
            if not tag or not hasattr(tag, "attrs"):
                return None
            if attr_name not in tag.attrs:
                return None
            attr_value = tag.attrs[attr_name]
            if isinstance(attr_value, str):
                return attr_value.strip()
            elif isinstance(attr_value, list) and attr_value:
                return str(attr_value[0]).strip()
            return None

        title = soup.title.string.strip() if soup.title and soup.title.string else None

        description_tag = soup.find("meta", attrs={"name": "description"}) or soup.find(
            "meta", attrs={"property": "og:description"}
        )
        description = get_attr_value(description_tag, "content")

        website_name_tag = soup.find("meta", property="og:site_name") or soup.find(
            "meta", attrs={"name": "application-name"}
        )
        website_name = get_attr_value(website_name_tag, "content")

        # Find favicon with a more specific search
        favicon_tag = (
            soup.find("link", rel="icon")
            or soup.find("link", rel="shortcut icon")
            or soup.find("link", rel="apple-touch-icon")
        )
        favicon_href = get_attr_value(favicon_tag, "href")
        favicon = to_absolute(favicon_href) if favicon_href else None

        og_image_tag = soup.find("meta", property="og:image")
        og_image_content = get_attr_value(og_image_tag, "content")
        og_image = to_absolute(og_image_content) if og_image_content else None

        logo_tag = soup.find("meta", property="og:logo") or soup.find(
            "link", rel="logo"
        )
        website_image = None
        if logo_tag:
            logo_content = get_attr_value(logo_tag, "content")
            logo_href = get_attr_value(logo_tag, "href")
            logo_url = logo_content or logo_href
            if logo_url:
                website_image = to_absolute(logo_url)

        if not website_image:
            website_image = og_image

        return {
            "title": title,
            "description": description,
            "favicon": favicon or og_image,
            "website_name": website_name,
            "website_image": website_image,
            "url": url,
        }

    except (httpx.RequestError, httpx.HTTPStatusError) as exc:
        logger.error(f"Error fetching URL metadata: {exc}")
    except Exception as exc:
        logger.error(f"Unexpected error: {exc}")

    return {
        "title": None,
        "description": None,
        "favicon": None,
        "website_name": None,
        "website_image": None,
        "url": url,
    }


async def convert_to_markdown(text: str) -> str:
    """
    Convert plaintext to markdown format.

    Args:
        text (str): The plaintext to convert

    Returns:
        str: The markdown formatted text
    """
    # Basic markdown transformation
    # This is a simple implementation that could be expanded
    paragraphs = text.split("\n\n")
    markdown_text = ""

    for i, p in enumerate(paragraphs):
        p = p.strip()
        if not p:
            continue

        # Check if paragraph might be a header
        if len(p) < 100 and not p.endswith("."):
            markdown_text += f"## {p}\n\n"
        else:
            markdown_text += f"{p}\n\n"

    return markdown_text


async def perform_deep_research(
    query: str, max_results: int = 3, take_screenshots: bool = False
) -> Dict[str, Any]:
    """
    Perform a deep research by first searching the web, then concurrently fetching
    the content of the top results and converting them to markdown.

    Args:
        query (str): The search query
        max_results (int): Maximum number of results to process in depth
        take_screenshots (bool): Whether to take screenshots of the webpages
        writer: Optional writer for output of the tool

    Returns:
        Dict[str, Any]: A dictionary containing search results with fetched content and optional screenshots
    """
    start_time = time.time()
    writer = get_stream_writer()

    writer({"progress": "Deep Research: Searching the web..."})

    search_results = await perform_search(query=query, count=5)
    web_results = search_results.get("web", [])

    if not web_results:
        logger.info("No web results found for deep research")
        writer({"progress": "Deep Research: No web results found."})
        return {"original_search": search_results, "enhanced_results": []}

    # Create a list of URLs to process with domain information for better reporting
    urls_to_process = []
    for result in web_results[:max_results]:
        url = result.get("url")
        if url and is_valid_url(url):
            # Extract domain for more readable progress updates
            domain = urlparse(url).netloc
            urls_to_process.append((url, domain))

    writer(
        {
            "progress": f"Deep Research: Starting concurrent processing of {len(urls_to_process)} URLs..."
        }
    )

    # Create a shared counter for tracking progress across async tasks
    completed_urls = 0

    # Custom wrapper for fetch_and_process_url that updates progress
    async def fetch_with_progress(url_info):
        nonlocal completed_urls
        url, domain = url_info

        writer({"progress": f"Deep Research: Fetching content from {domain}..."})
        result = await fetch_and_process_url(url, take_screenshot=take_screenshots)

        # Update progress after each URL is processed
        completed_urls += 1
        progress_pct = int((completed_urls / len(urls_to_process)) * 100)
        writer(
            {
                "progress": f"Deep Research: {progress_pct}% complete. Processed {completed_urls}/{len(urls_to_process)} URLs. Completed: {domain}"
            }
        )

        return result

    # Use gather to process URLs concurrently with progress updates
    if urls_to_process:
        writer(
            {
                "progress": f"Deep Research: Processing {len(urls_to_process)} URLs concurrently..."
            }
        )
        fetched_contents = await asyncio.gather(
            *[fetch_with_progress(url_info) for url_info in urls_to_process]
        )
    else:
        fetched_contents = []

    enhanced_results = []
    total_content_size = 0

    for i, content_data in enumerate(fetched_contents):
        # Skip if we've reached content limit or no more results
        if i >= len(web_results) or total_content_size >= MAX_TOTAL_CONTENT:
            break

        # Get the corresponding search result
        result = web_results[i]
        domain = urlparse(result.get("url", "#")).netloc

        # Check if there was an error during fetching
        if "error" in content_data:
            enhanced_result = {
                **result,
                "full_content": f"Error fetching content: {content_data['error']}",
                "fetch_error": content_data["error"],
            }
        else:
            # Get markdown content
            markdown_content = content_data.get("markdown_content", "")

            # Check if we need to truncate for size limits
            if total_content_size + len(markdown_content) > MAX_TOTAL_CONTENT:
                available_space = MAX_TOTAL_CONTENT - total_content_size
                if available_space > 0:
                    markdown_content = (
                        markdown_content[:available_space]
                        + "...[content truncated for size limits]"
                    )

            total_content_size += len(markdown_content)

            # Add the content and screenshot URL if available
            enhanced_result = {
                **result,
                "full_content": markdown_content,
            }

            # Include screenshot URL if available
            if (
                take_screenshots
                and "screenshot_url" in content_data
                and content_data["screenshot_url"]
            ):
                enhanced_result["screenshot_url"] = content_data["screenshot_url"]
                writer(
                    {"progress": f"Deep Research: Screenshot available for {domain}"}
                )

        enhanced_results.append(enhanced_result)

    elapsed_time = time.time() - start_time
    final_status = (
        f"Deep Research completed in {elapsed_time:.2f} seconds. Processed {len(enhanced_results)} results"
        + (" with screenshots" if take_screenshots else "")
    )

    writer({"progress": final_status})
    logger.info(final_status)

    return {
        "original_search": search_results,
        "enhanced_results": enhanced_results,
        "screenshots_taken": take_screenshots,
        "metadata": {
            "total_content_size": total_content_size,
            "elapsed_time": elapsed_time,
            "query": query,
        },
    }
