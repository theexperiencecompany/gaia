import asyncio
import re
import time
from typing import Any, Dict, Optional
from urllib.parse import urljoin, urlparse

import httpx
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
)
from app.utils.search_utils import perform_search
from bs4 import BeautifulSoup
from fastapi import HTTPException, status
from langgraph.config import get_stream_writer


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


async def perform_deep_research(query: str, max_results: int = 3) -> Dict[str, Any]:
    """
    Perform a deep research by first searching the web, then concurrently fetching
    the content of the top results and converting them to markdown.

    Args:
        query (str): The search query
        max_results (int): Maximum number of results to process in depth

    Returns:
        Dict[str, Any]: A dictionary containing search results with fetched content
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
        result = await fetch_and_process_url(url)

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

            # Add the content
            enhanced_result = {
                **result,
                "full_content": markdown_content,
            }

        enhanced_results.append(enhanced_result)

    elapsed_time = time.time() - start_time
    final_status = f"Deep Research completed in {elapsed_time:.2f} seconds. Processed {len(enhanced_results)} results"

    writer({"progress": final_status})
    logger.info(final_status)

    return {
        "original_search": search_results,
        "enhanced_results": enhanced_results,
        "metadata": {
            "total_content_size": total_content_size,
            "elapsed_time": elapsed_time,
            "query": query,
        },
    }
