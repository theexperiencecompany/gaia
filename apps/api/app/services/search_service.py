"""
Service module for handling search operations and URL metadata fetching.
"""

import re
import time

from fastapi import HTTPException, status

from app.db.repositories.conversations import conversation_repository
from app.db.repositories.notes import note_repository
from app.utils.general_utils import get_context_window
from shared.py.wide_events import log


async def search_messages(query: str, user_id: str) -> dict:
    """
    Search for messages, conversations, and notes for a given user that match the query.

    Args:
        query (str): The search text.
        user_id (str): The ID of the authenticated user.

    Returns:
        dict: A dictionary containing lists of matched messages, conversations, and notes.

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
        service="search_service",
    )
    search_start = time.monotonic()
    escaped_query = re.escape(query)
    try:
        conversation_results = await conversation_repository.search(user_id, pattern=escaped_query)
        note_hits = await note_repository.search_by_plaintext(user_id, pattern=escaped_query)

        messages = []
        for hit in conversation_results.messages:
            row = hit.model_dump(mode="json")
            # Snippet for search highlighting, centered on the matched response.
            row["snippet"] = get_context_window(hit.message.response, query, chars_before=30)
            messages.append(row)

        conversations = [hit.model_dump(mode="json") for hit in conversation_results.conversations]

        notes_with_snippets = [
            {
                **hit.model_dump(mode="json"),
                "snippet": get_context_window(hit.plaintext, query, chars_before=30),
            }
            for hit in note_hits
        ]

        result_count = len(messages) + len(conversations) + len(notes_with_snippets)
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
        return {
            "messages": messages,
            "conversations": conversations,
            "notes": notes_with_snippets,
        }
    except Exception as e:
        log.error(f"Error in search_messages: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to perform search: {e!s}",
        )
