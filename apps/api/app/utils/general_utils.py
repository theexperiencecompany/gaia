import base64
from collections.abc import Mapping
from datetime import datetime
import json
from pathlib import Path
import tomllib
from typing import TypedDict

from pydantic import BaseModel, ConfigDict, Field

from app.models.composio_schemas.gmail import GmailHeader, GmailMessagePart
from app.models.integrations.gmail_messages import (
    ComposioGmailMessage,
    GmailApiMessage,
    GmailMessageTimestamps,
)
from app.models.mail_models import GmailMessageSummary

ELLIPSIS = "…"


def is_json_safe(value: object) -> bool:
    """Whether value survives a JSON round trip.

    The honest test for "can this be persisted", rather than a proxy like
    isinstance-on-scalars.
    """
    try:
        json.dumps(value)
    except (TypeError, ValueError):
        return False
    return True


def clip_text(text: str, limit: int) -> str:
    """Cap text at limit characters, marking the cut.

    So a reader (or a model) can tell truncation apart from the real end.
    """
    return text if len(text) <= limit else f"{text[:limit]}{ELLIPSIS}"


def get_context_window(text: str, query: str, chars_before: int = 15, chars_after: int = 30) -> str:
    """Return the text window around the search query, with chars_before/chars_after of context."""
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


def _message_time(m: GmailMessageTimestamps) -> str:
    # Prefer 'date', then 'messageTimestamp', then fallback
    from dateutil.parser import parse as parse_date  # noqa: PLC0415 -- cycle

    if m.date:
        return str(m.date)
    if m.message_timestamp:
        try:
            return parse_date(m.message_timestamp).strftime("%Y-%m-%d %H:%M")
        except Exception:
            return str(m.message_timestamp)
    # Gmail API fallback
    if m.internal_date:
        try:
            timestamp = int(m.internal_date) / 1000
            return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M")
        except Exception:
            return str(m.internal_date)
    return ""


def transform_gmail_message(msg: Mapping[str, object]) -> GmailMessageSummary:
    """Transform a Gmail API or Composio message into the frontend-friendly format.

    Keeps every raw key alongside the derived ones.
    """
    # messageId is the discriminator: a Gmail API resource carries id, never messageId.
    # messageText cannot be part of the test: Composio omits it under verbose=false.
    # Every derived key is a string, so the result validates whatever was left null.
    if "messageId" in msg:
        composio = ComposioGmailMessage.model_validate(msg)
        labels = composio.label_ids or []
        return GmailMessageSummary.model_validate(
            {
                **msg,
                "id": composio.message_id or "",
                "threadId": composio.thread_id or "",
                "from": composio.from_ or composio.sender or "",
                "to": composio.to or "",
                "cc": composio.cc or "",
                "replyTo": composio.reply_to or "",
                "subject": composio.subject or "",
                "time": _message_time(composio),
                "snippet": composio.snippet or composio.message_text or "",
                "body": composio.body or composio.message_text or "",
                "isThread": bool(composio.thread_id and len(labels) > 0),
                "is_unread": "UNREAD" in labels,
                "labelIds": labels,
            }
        )

    gmail = GmailApiMessage.model_validate(msg)
    headers = gmail.payload.headers if gmail.payload else []
    labels = gmail.label_ids or []
    return GmailMessageSummary.model_validate(
        {
            **msg,
            "id": gmail.id or "",
            "threadId": gmail.thread_id or "",
            "from": _header(headers, "From"),
            "to": _header(headers, "To"),
            "cc": _header(headers, "Cc"),
            "replyTo": _header(headers, "Reply-To"),
            "subject": _header(headers, "Subject"),
            "time": _message_time(gmail),
            "snippet": gmail.snippet or "",
            "body": decode_message_body(gmail),
            "isThread": bool(gmail.thread_id and len(labels) > 0),
            "is_unread": "UNREAD" in labels,
            "labelIds": labels,
        }
    )


def _header(headers: list[GmailHeader], name: str) -> str:
    """Return the last header named name (a repeated header resolved the way a dict of them did)."""
    return next((h.value or "" for h in reversed(headers) if h.name == name), "")


def _decode_part_data(data: str) -> str:
    return base64.urlsafe_b64decode(data).decode(errors="ignore")


def decode_message_body(msg: GmailApiMessage) -> str:
    """Decode the message body from a Gmail API message; empty when it carries none."""
    payload = msg.payload or GmailMessagePart()
    parts = payload.parts

    # Handle single-part messages
    if not parts:
        body_data = payload.body.data if payload.body else None
        if body_data:
            return _decode_part_data(body_data)
        return ""

    # For multipart messages, prioritize HTML over plain text
    html_body = None
    plain_body = None

    for part in parts:
        # any non-text/* fallback is skipped alike
        part_mime_type = part.mime_type or ""  # pragma: no mutate
        body_data = part.body.data if part.body else None

        if body_data:
            decoded_content = _decode_part_data(body_data)

            if part_mime_type == "text/html":
                html_body = decoded_content
            elif part_mime_type == "text/plain":
                plain_body = decoded_content

    # Return HTML if available (frontend expects HTML), otherwise plain text
    return html_body or plain_body or ""


class ProjectInfo(TypedDict):
    """The pyproject.toml metadata the health endpoint reports."""

    name: str
    version: str
    description: str


class _PyprojectProject(BaseModel):
    """The ``[project]`` table of pyproject.toml, defaulted key by key."""

    model_config = ConfigDict(extra="ignore")

    name: str = "GAIA API"
    version: str = "dev"
    description: str = "Backend for GAIA"


class _Pyproject(BaseModel):
    model_config = ConfigDict(extra="ignore")

    project: _PyprojectProject = Field(default_factory=_PyprojectProject)


def get_project_info() -> ProjectInfo:
    """Get project info from pyproject.toml file."""
    try:
        # Path to pyproject.toml from this file location
        pyproject_path = Path(__file__).parent.parent.parent / "pyproject.toml"
        with open(pyproject_path, "rb") as f:
            project = _Pyproject.model_validate(tomllib.load(f)).project
            return ProjectInfo(
                name=project.name,
                version=project.version,
                description=project.description,
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
