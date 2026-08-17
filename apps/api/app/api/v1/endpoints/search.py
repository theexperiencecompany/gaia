"""
Search routes for the GAIA API.

This module contains routes related to search functionality and URL metadata fetching for the GAIA API.
"""

import asyncio
import re

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.v1.dependencies.oauth_dependencies import get_user_id
from app.api.v1.middleware.rate_limiter import limiter
from app.decorators import tiered_rate_limit
from app.models.search_models import (
    EmailSearchResponse,
    MultiURLResponse,
    SearchResultsResponse,
    URLRequest,
    URLResponse,
)
from app.services.analytics_service import AnalyticsEvents, capture_context_event
from app.services.email_profile_service import fetch_email_profiles
from app.services.search_service import search_messages
from app.utils.email_utils import is_email_target
from app.utils.internet_utils import fetch_url_metadata
from app.utils.search import perform_search
from shared.py.wide_events import log

router = APIRouter()


@router.get("/search", response_model=SearchResultsResponse)
async def search_messages_endpoint(
    query: str, user_id: str = Depends(get_user_id)
) -> SearchResultsResponse:
    """
    Search for messages, conversations, and notes by their description or content.

    Args:
        query (str): The search query.
        user_id (str): The authenticated user's id.

    Returns:
        SearchResultsResponse: The search results for messages, conversations, and notes.
    """
    log.set(
        user={"id": user_id},
        search={
            "query": query,
            "mode": "keyword",
            "scope": ["messages", "conversations", "notes"],
        },
    )
    try:
        results = await search_messages(query, user_id)
        result_count = len(results.messages) + len(results.conversations) + len(results.notes)
        capture_context_event(
            AnalyticsEvents.SEARCH_PERFORMED,
            {"mode": "keyword", "query_length": len(query), "result_count": result_count},
        )
        # set_ns: log.set(search={...}) would clobber the query context set above
        log.set_ns("search", result_count=result_count)
        return results
    except Exception as e:
        log.error(
            "Error searching messages",
            user_id=user_id,
            error_type=type(e).__name__,
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Search failed",
        ) from e


def extract_emails(text: str) -> list[str]:
    """Extract every email address appearing in ``text``."""
    email_pattern = r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
    return re.findall(email_pattern, text)


@router.get("/search/email", response_model=EmailSearchResponse)
@tiered_rate_limit("web_search")
async def search_email_endpoint(query: str) -> EmailSearchResponse:
    """
    Search for official contact email addresses related to the given query.

    Args:
        query (str): The search query.

    Returns:
        EmailSearchResponse: The extracted email addresses, combined text, and search data.
    """
    log.set(
        search={
            "query": query,
            "mode": "web",
            "scope": ["emails"],
        },
    )
    search_data = await perform_search(
        query=f"Official contact e-mail address of {query}",
        count=50,
    )

    if not search_data:
        raise HTTPException(status_code=500, detail="Search failed or returned no results")

    combined_text = " ".join(f"{item.title} {item.content}" for item in search_data.web)

    emails = list(set(extract_emails(combined_text)))
    log.set(search={"result_count": len(emails)})

    return EmailSearchResponse(
        emails=emails,
        combined_text=combined_text,
        search_data=search_data,
    )


@router.post(
    "/fetch-url-metadata",
    response_model=MultiURLResponse,
    status_code=status.HTTP_200_OK,
)
@limiter.limit("100/minute")
@limiter.limit("500/hour")
async def fetch_url_metadata_endpoint(
    request: Request, data: URLRequest, user_id: str = Depends(get_user_id)
) -> MultiURLResponse:
    """
    Fetch metadata for multiple URLs in parallel.

    Email and ``mailto:`` entries resolve to person previews (Google
    Contacts, then Gravatar) instead of being scraped as web pages.

    Args:
        request (Request): The FastAPI request object (required for rate limiting).
        data (URLRequest): The URL request containing an array of URLs.
        user_id (str): The authenticated user's id (contact lookups are per-user).

    Returns:
        MultiURLResponse: The metadata for all URLs.
    """
    log.set(user={"id": user_id}, search={"mode": "url_metadata"})
    email_targets = [url for url in data.urls if is_email_target(url)]
    web_urls = [url for url in data.urls if url not in email_targets]

    email_task = fetch_email_profiles(user_id, email_targets)
    web_tasks = [fetch_url_metadata(url) for url in web_urls]
    email_results, *web_results = await asyncio.gather(
        email_task, *web_tasks, return_exceptions=True
    )

    response_data: dict[str, URLResponse] = {}
    if isinstance(email_results, dict):
        response_data.update(email_results)
    for url, result in zip(web_urls, web_results):
        if isinstance(result, Exception):
            # Skip failed URLs - they won't be in the response
            continue
        if isinstance(result, URLResponse):
            response_data[url] = result

    log.set_ns("search", result_count=len(response_data))
    return MultiURLResponse(results=response_data)
