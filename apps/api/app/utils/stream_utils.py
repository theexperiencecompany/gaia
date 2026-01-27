"""
Shared utilities for SSE stream processing.

Used by both web chat and bot chat flows to parse streaming chunks.
"""

import json
from typing import Any, Dict, Optional


def extract_response_text(chunk: str) -> str:
    """
    Extract response text from an SSE data chunk.

    Args:
        chunk: Raw SSE chunk string (e.g., "data: {...}")

    Returns:
        Extracted response text, or empty string if not found
    """
    try:
        if chunk.startswith("data: "):
            chunk = chunk[6:]
        data = json.loads(chunk)
        return data.get("response", "")
    except (json.JSONDecodeError, KeyError):
        pass
    return ""


def extract_complete_message(chunk: str) -> Optional[str]:
    """
    Extract complete message from a nostream marker.

    Args:
        chunk: Raw chunk string (e.g., "nostream: {...}")

    Returns:
        Complete message text, or None if not a nostream marker
    """
    if not chunk.startswith("nostream: "):
        return None

    try:
        chunk_json = json.loads(chunk.replace("nostream: ", ""))
        return chunk_json.get("complete_message", "")
    except json.JSONDecodeError:
        return None


def is_done_marker(chunk: str) -> bool:
    """Check if chunk is the SSE done marker."""
    return chunk == "data: [DONE]\n\n"


def parse_sse_chunk(chunk: str) -> Optional[Dict[str, Any]]:
    """
    Parse an SSE data chunk into a dictionary.

    Args:
        chunk: Raw SSE chunk string

    Returns:
        Parsed dictionary, or None if parsing fails
    """
    try:
        if chunk.startswith("data: "):
            chunk = chunk[6:]
        return json.loads(chunk)
    except json.JSONDecodeError:
        return None
