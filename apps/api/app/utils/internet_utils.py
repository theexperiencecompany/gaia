import re
from urllib.parse import urljoin, urlparse

import httpx
from app.config.loggers import search_logger as logger
from app.db.mongodb.collections import search_urls_collection
from app.db.redis import get_cache, set_cache
from app.db.utils import serialize_document
from app.models.search_models import URLResponse
from bs4 import BeautifulSoup
from fastapi import HTTPException, status


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
        logger.debug(f"Error fetching URL metadata: {exc}")
    except Exception as exc:
        logger.debug(f"Unexpected error: {exc}")

    return {
        "title": None,
        "description": None,
        "favicon": None,
        "website_name": None,
        "website_image": None,
        "url": url,
    }
