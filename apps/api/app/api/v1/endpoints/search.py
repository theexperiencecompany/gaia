"""
Search routes for the GAIA API.

This module contains routes related to search functionality and URL metadata fetching for the GAIA API.
"""

import asyncio
import re

from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.decorators import tiered_rate_limit
from app.models.search_models import URLRequest, MultiURLResponse, URLResponse
from app.services.search_service import search_messages
from app.utils.internet_utils import fetch_url_metadata
from app.utils.search_utils import perform_search
from fastapi import APIRouter, Depends, HTTPException, status

router = APIRouter()


@router.get("/search")
async def search_messages_endpoint(query: str, user: dict = Depends(get_current_user)):
    """
    Search for messages, conversations, and notes by their description or content.

    Args:
        query (str): The search query.
        user (dict): The authenticated user information.

    Returns:
        dict: A dictionary containing the search results for messages, conversations, and notes.
    """
    user_id = user["user_id"]
    return await search_messages(query, user_id)


def extract_emails(text: str) -> list:
    """
    Extract email addresses from the given text.

    Args:
        text (str): The text to extract email addresses from.

    Returns:
        list: A list of extracted email addresses.
    """
    email_pattern = r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
    return re.findall(email_pattern, text)


@router.get("/search/email")
@tiered_rate_limit("web_search")
async def search_email_endpoint(query: str):
    """
    Search for official contact email addresses related to the given query.

    Args:
        query (str): The search query.

    Returns:
        dict: A dictionary containing the extracted email addresses, combined text, and search data.
    """
    search_data = await perform_search(
        query=f"Official contact e-mail address of {query}",
        count=50,
        images=False,
        videos=False,
        news=False,
    )

    if not search_data or "web" not in search_data:
        raise HTTPException(
            status_code=500, detail="Search failed or returned no results"
        )

    combined_text = " ".join(
        f"{item.get('title', '')} {item.get('snippet', '')}"
        for item in search_data["web"]
    )

    emails = list(set(extract_emails(combined_text)))

    return {
        "emails": emails,
        "combined_text": combined_text,
        "search_data": search_data,
    }


@router.post(
    "/fetch-url-metadata",
    response_model=MultiURLResponse,
    status_code=status.HTTP_200_OK,
)
@tiered_rate_limit("web_search")
async def fetch_url_metadata_endpoint(data: URLRequest):
    """
    Fetch metadata for multiple URLs in parallel.

    Args:
        data (URLRequest): The URL request containing an array of URLs.

    Returns:
        MultiURLResponse: The metadata for all URLs.
    """
    # Process all URLs in parallel
    tasks = [fetch_url_metadata(url) for url in data.urls]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Build response mapping
    response_data: dict[str, URLResponse] = {}
    for url, result in zip(data.urls, results):
        if isinstance(result, Exception):
            # Skip failed URLs - they won't be in the response
            continue
        else:
            if isinstance(result, URLResponse):
                response_data[url] = result

    return MultiURLResponse(results=response_data)
