import base64
from datetime import datetime
from pathlib import Path
from typing import Dict

import tomllib


def get_context_window(
    text: str, query: str, chars_before: int = 15, chars_after: int = 30
) -> str:
    """
    Get text window around the search query with specified characters before and after.

    Args:
        text (str): Full text to search in
        query (str): Search term to find
        chars_around (int): Number of characters to include before and after match

    Returns:
        str: Context window containing the match with surrounding text
    """
    # Find the query in text (case-insensitive)
    query_lower = query.lower()
    text_lower = text.lower()

    # Find the start position of the query
    start_pos = text_lower.find(query_lower)
    if start_pos == -1:
        return ""

    # Calculate window boundaries
    window_start = max(0, start_pos - chars_before)
    window_end = min(len(text), start_pos + len(query) + chars_after)

    # Get the context window
    context = text[window_start:window_end]

    # Add ellipsis if we're not at the start/end of the text
    if window_start > 0:
        context = "..." + context
    if window_end < len(text):
        context = context + "..."

    return context


def transform_gmail_message(msg) -> Dict:
    """Transform Gmail API message to frontend-friendly format while keeping all raw data for debugging."""
    """
    Transform a Gmail/Composio message to a frontend-friendly format.
    Handles both Gmail API and Composio message formats.
    """
    from dateutil.parser import parse as parse_date  # type: ignore[import-untyped]

    def get_sender(m):
        return m.get("from") or m.get("sender") or ""

    def get_time(m):
        # Prefer 'date', then 'messageTimestamp', then fallback
        if m.get("date"):
            return m["date"]
        ts = m.get("messageTimestamp")
        if ts:
            try:
                return parse_date(ts).strftime("%Y-%m-%d %H:%M")
            except Exception:
                return ts
        # Gmail API fallback
        if m.get("internalDate"):
            try:
                timestamp = int(m["internalDate"]) / 1000
                return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M")
            except Exception:
                return str(m["internalDate"])
        return ""

    def transform_composio(m):
        return {
            **m,
            "id": m.get("messageId", ""),
            "threadId": m.get("threadId", ""),
            "from": get_sender(m),
            "to": m.get("to", ""),
            "cc": m.get("cc", ""),
            "replyTo": m.get("replyTo", ""),
            "subject": m.get("subject", ""),
            "time": get_time(m),
            "snippet": m.get("snippet", m.get("messageText", "")),
            "body": m.get("body", m.get("messageText", "")),
            "isThread": bool(m.get("threadId") and len(m.get("labelIds", [])) > 0),
        }

    def transform_gmail_api(m):
        headers = {
            h["name"]: h["value"] for h in m.get("payload", {}).get("headers", [])
        }
        return {
            **m,
            "id": m.get("id", ""),
            "threadId": m.get("threadId", ""),
            "from": headers.get("From", ""),
            "to": headers.get("To", ""),
            "cc": headers.get("Cc", ""),
            "replyTo": headers.get("Reply-To", ""),
            "subject": headers.get("Subject", ""),
            "time": get_time(m),
            "snippet": m.get("snippet", ""),
            "body": decode_message_body(m),
            "isThread": bool(m.get("threadId") and len(m.get("labelIds", [])) > 0),
        }

    # Detect and transform
    if "messageId" in msg and "messageText" in msg:
        return transform_composio(msg)
    return transform_gmail_api(msg)


def decode_message_body(msg):
    """Decode the message body from a Gmail API message."""
    payload = msg.get("payload", {})
    parts = payload.get("parts", [])

    # Handle single-part messages
    if not parts:
        body_data = payload.get("body", {}).get("data", "")
        if body_data:
            return base64.urlsafe_b64decode(
                body_data.replace("-", "+").replace("_", "/")
            ).decode("utf-8", errors="ignore")
        return None

    # For multipart messages, prioritize HTML over plain text
    html_body = None
    plain_body = None

    for part in parts:
        part_mime_type = part.get("mimeType", "")
        body_data = part.get("body", {}).get("data", "")

        if body_data:
            decoded_content = base64.urlsafe_b64decode(
                body_data.replace("-", "+").replace("_", "/")
            ).decode("utf-8", errors="ignore")

            if part_mime_type == "text/html":
                html_body = decoded_content
            elif part_mime_type == "text/plain":
                plain_body = decoded_content

    # Return HTML if available (frontend expects HTML), otherwise plain text
    return html_body or plain_body


def get_project_info() -> dict:
    """Get project info from pyproject.toml file."""
    try:
        # Path to pyproject.toml from this file location
        pyproject_path = Path(__file__).parent.parent.parent / "pyproject.toml"
        with open(pyproject_path, "rb") as f:
            pyproject_data = tomllib.load(f)
            project = pyproject_data.get("project", {})
            return {
                "name": project.get("name", "GAIA API"),
                "version": project.get("version", "dev"),
                "description": project.get("description", "Backend for GAIA"),
            }
    except Exception:
        return {"name": "GAIA API", "version": "dev", "description": "Backend for GAIA"}
