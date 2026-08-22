"""
Service module for handling search operations and URL metadata fetching.
"""

import re
import time

from fastapi import HTTPException, status

from app.db.repositories.conversations import conversation_repository
from app.db.repositories.notes import note_repository
from app.models.search_models import MessageSearchResult, NoteSearchResult, SearchResultsResponse
from app.utils.general_utils import get_context_window
from shared.py.wide_events import log


async def search_messages(query: str, user_id: str) -> SearchResultsResponse:
    """
    Search for messages, conversations, and notes for a given user that match the query.

    Raises:
        HTTPException: If an error occurs during the search process.
    """
    log.set(
        search={
            "query": query,
            "query_length": len(query),
            "search_type": "keyword",
            "sources": ["messages", "conversations", "notes"],
        },
        user_id=user_id,
        component="search_service",
    )
    search_start = time.monotonic()
    escaped_query = re.escape(query)
    try:
        conversation_results = await conversation_repository.search(user_id, pattern=escaped_query)
        note_hits = await note_repository.search_by_plaintext(user_id, pattern=escaped_query)

        messages = [
            MessageSearchResult(
                conversation_id=hit.conversation_id,
                message=hit.message,
                # Snippet for search highlighting, centered on the matched response.
                snippet=get_context_window(hit.message.response, query, chars_before=30),
            )
            for hit in conversation_results.messages
        ]

        notes_with_snippets = [
            NoteSearchResult(
                id=hit.id,
                note_id=hit.note_id,
                plaintext=hit.plaintext,
                snippet=get_context_window(hit.plaintext, query, chars_before=30),
            )
            for hit in note_hits
        ]

        result_count = (
            len(messages) + len(conversation_results.conversations) + len(notes_with_snippets)
        )
        duration_ms = int((time.monotonic() - search_start) * 1000)
        log.set(
            search={
                "query": query,
                "query_length": len(query),
                "search_type": "keyword",
                "sources": ["messages", "conversations", "notes"],
                "result_count": result_count,
                "duration_ms": duration_ms,
            }
        )
        return SearchResultsResponse(
            messages=messages,
            conversations=conversation_results.conversations,
            notes=notes_with_snippets,
        )
    except Exception as e:
        log.error(
            "Error in search_messages", error=str(e), error_type=type(e).__name__, user_id=user_id
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to perform search: {e!s}",
        ) from e
