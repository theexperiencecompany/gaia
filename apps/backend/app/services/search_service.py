"""
Service module for handling search operations and URL metadata fetching.
"""

from fastapi import HTTPException, status

from app.config.loggers import search_logger as logger
from app.db.mongodb.collections import (
    conversations_collection,
    notes_collection,
)
from app.db.utils import serialize_document
from app.utils.general_utils import get_context_window
from app.utils.tool_data_utils import convert_legacy_tool_data

# Constants
MAX_CONTENT_LENGTH = 8000  # Max characters per webpage
MAX_TOTAL_CONTENT = 20000  # Max total characters for all webpages combined
URL_TIMEOUT = 20.0  # Seconds
CACHE_EXPIRY = 86400  # 24 hours


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
    try:
        results = await conversations_collection.aggregate(
            [
                {"$match": {"user_id": user_id}},
                {
                    "$facet": {
                        "messages": [
                            {"$unwind": "$messages"},
                            {
                                "$match": {
                                    "$or": [
                                        {
                                            "messages.response": {
                                                "$regex": query,
                                                "$options": "i",
                                            }
                                        },
                                    ]
                                }
                            },
                            {
                                "$project": {
                                    "_id": 0,
                                    "conversation_id": 1,
                                    "message": "$messages",
                                }
                            },
                        ],
                        "conversations": [
                            {
                                "$match": {
                                    "description": {"$regex": query, "$options": "i"},
                                }
                            },
                            {
                                "$project": {
                                    "_id": 0,
                                    "conversation_id": 1,
                                    "description": 1,
                                    "conversation": "$conversations",
                                }
                            },
                        ],
                    }
                },
            ]
        ).to_list(None)

        notes_results = await notes_collection.aggregate(
            [
                {
                    "$match": {
                        "user_id": user_id,
                        "plaintext": {"$regex": query, "$options": "i"},
                    }
                },
                {
                    "$project": {
                        "id": {"$toString": "$_id"},
                        "note_id": 1,
                        "plaintext": 1,
                    }
                },
            ]
        ).to_list(None)

        messages = results[0]["messages"] if results else []
        conversations = results[0]["conversations"] if results else []

        for message in messages:
            # Convert legacy tool data in the message
            if "message" in message:
                message["message"] = convert_legacy_tool_data(message["message"])
            # Add snippet for search highlighting
            message["snippet"] = get_context_window(
                message["message"]["response"], query, chars_before=30
            )

        notes_with_snippets = [
            {
                **serialize_document(note),
                "snippet": get_context_window(
                    note["plaintext"], query, chars_before=30
                ),
            }
            for note in notes_results
        ]

        return {
            "messages": messages,
            "conversations": conversations,
            "notes": notes_with_snippets,
        }
    except Exception as e:
        logger.error(f"Error in search_messages: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to perform search: {str(e)}",
        )
