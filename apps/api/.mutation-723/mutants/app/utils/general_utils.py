import base64
from datetime import datetime
import json
from pathlib import Path
import tomllib
from typing import Any, TypedDict

ELLIPSIS = "…"


def is_json_safe(value: object) -> bool:
    """Whether ``value`` survives a JSON round trip — the honest test for
    "can this be persisted", rather than a proxy like isinstance-on-scalars."""
    try:
        json.dumps(value)
    except (TypeError, ValueError):
        return False
    return True


def clip_text(text: str, limit: int) -> str:
    """Cap ``text`` at ``limit`` characters, marking the cut so a reader (or a model)
    can tell truncation apart from the real end of the value."""
    return text if len(text) <= limit else f"{text[:limit]}{ELLIPSIS}"


def get_context_window(text: str, query: str, chars_before: int = 15, chars_after: int = 30) -> str:
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


def transform_gmail_message(msg: dict[str, Any]) -> dict[str, Any]:
    """Transform a Gmail API or Composio message into the frontend-friendly format,
    keeping every raw key alongside the derived ones."""
    from dateutil.parser import parse as parse_date

    def get_sender(m: dict[str, Any]) -> str:
        return m.get("from") or m.get("sender") or ""

    def get_time(m: dict[str, Any]) -> str:
        # Prefer 'date', then 'messageTimestamp', then fallback
        if m.get("date"):
            return str(m["date"])
        ts = m.get("messageTimestamp")
        if ts:
            try:
                return parse_date(ts).strftime("%Y-%m-%d %H:%M")
            except Exception:
                return str(ts)
        # Gmail API fallback
        if m.get("internalDate"):
            try:
                timestamp = int(m["internalDate"]) / 1000
                return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M")
            except Exception:
                return str(m["internalDate"])
        return ""

    def transform_composio(m: dict[str, Any]) -> dict[str, Any]:
        labels = m.get("labelIds", [])
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
            "isThread": bool(m.get("threadId") and len(labels) > 0),
            "is_unread": "UNREAD" in labels,
        }

    def transform_gmail_api(m: dict[str, Any]) -> dict[str, Any]:
        headers = {h["name"]: h["value"] for h in m.get("payload", {}).get("headers", [])}
        labels = m.get("labelIds", [])
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
            "isThread": bool(m.get("threadId") and len(labels) > 0),
            "is_unread": "UNREAD" in labels,
        }

    # Detect and transform
    if "messageId" in msg and "messageText" in msg:
        return transform_composio(msg)
    return transform_gmail_api(msg)


def decode_message_body(msg: dict[str, Any]) -> str | None:
    """Decode the message body from a Gmail API message."""
    payload = msg.get("payload", {})
    parts = payload.get("parts", [])

    # Handle single-part messages
    if not parts:
        body_data = payload.get("body", {}).get("data", "")
        if body_data:
            return base64.urlsafe_b64decode(body_data.replace("-", "+").replace("_", "/")).decode(
                "utf-8", errors="ignore"
            )
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


class ProjectInfo(TypedDict):
    """The pyproject.toml metadata the health endpoint reports."""

    name: str
    version: str
    description: str


def get_project_info() -> ProjectInfo:
    """Get project info from pyproject.toml file."""
    try:
        # Path to pyproject.toml from this file location
        pyproject_path = Path(__file__).parent.parent.parent / "pyproject.toml"
        with open(pyproject_path, "rb") as f:
            pyproject_data = tomllib.load(f)
            project = pyproject_data.get("project", {})
            return ProjectInfo(
                name=project.get("name", "GAIA API"),
                version=project.get("version", "dev"),
                description=project.get("description", "Backend for GAIA"),
            )
    except Exception:
        return ProjectInfo(name="GAIA API", version="dev", description="Backend for GAIA")


def describe_structure(obj: object, parent: str = "") -> list[str]:
    lines = []

    if isinstance(obj, dict):
        for k, v in obj.items():
            key = f"{parent}.{k}" if parent else k
            if isinstance(v, dict):
                lines.append(key)
                lines.extend(describe_structure(v, key))
            elif isinstance(v, list):
                lines.append(f"{key}: [{len(v)} items]")
                if v and isinstance(v[0], (dict, list)):
                    lines.extend(describe_structure(v[0], f"{key}.0"))
            else:
                lines.append(key)
        return lines

    if isinstance(obj, list):
        lines.append(f"{parent}: [{len(obj)} items]")
        if obj and isinstance(obj[0], (dict, list)):
            lines.extend(describe_structure(obj[0], f"{parent}.0"))
        return lines

    return [parent]
