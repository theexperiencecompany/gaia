"""
Service functions for handling contact-related operations.
"""

from email.utils import getaddresses
from typing import Any


def build_contact_index(
    messages: list[dict[str, Any]],
    filter_query: str | None = None,
) -> dict[str, Any]:
    """Extract unique contacts from already-fetched Gmail message payloads.

    Used by the Composio-proxy variant of GET_CONTACT_LIST: instead of relying
    on `googleapiclient` to fetch messages, callers fetch via the proxy and
    pass the resulting message dicts (with `payload.headers`) into this helper.

    Args:
        messages: Gmail message payload dicts as returned by
            `users.messages.get` with format=metadata or full
        filter_query: Optional substring to filter contacts by name or email.
            Gmail's `q=` matches anywhere in a message (subject, body, etc.),
            so a search for "john" can return threads with hundreds of
            unrelated participants. Without this filter the caller would see
            every From/To/Cc/Reply-To address on every matched thread.

    Returns:
        Dict with `success`, `contacts` (list of {name, email}), and `count`
    """
    contact_dict: dict[str, dict[str, str]] = {}
    query_lower = filter_query.lower() if filter_query else None

    for message in messages:
        if not isinstance(message, dict):
            continue
        headers = {
            h["name"]: h["value"]
            for h in message.get("payload", {}).get("headers", [])
            if isinstance(h, dict) and "name" in h and "value" in h
        }

        # email.utils.getaddresses correctly handles names with embedded
        # commas (e.g., '"Doe, John" <john@example.com>') that a naive
        # split-on-comma would mangle.
        raw_values = [
            headers[field] for field in ("From", "To", "Cc", "Reply-To") if headers.get(field)
        ]
        for name, email in getaddresses(raw_values):
            if "@" not in email or "." not in email:
                continue
            if query_lower and query_lower not in name.lower() and query_lower not in email.lower():
                continue
            if email not in contact_dict or (name and not contact_dict[email]["name"]):
                contact_dict[email] = {"name": name, "email": email}

    contacts = sorted(contact_dict.values(), key=lambda x: x["name"] or x["email"])
    return {
        "success": True,
        "contacts": contacts,
        "count": len(contacts),
    }
