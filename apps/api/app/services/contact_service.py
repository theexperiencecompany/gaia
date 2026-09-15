"""Service functions for handling contact-related operations."""

from email.utils import getaddresses
from typing import Any


def build_contact_index(
    messages: list[Any],
    filter_query: str | None = None,
) -> dict[str, Any]:
    """Extract unique contacts from already-fetched Gmail message payloads.

    messages is typed Any (an external Gmail proxy response), so the
    isinstance guard below is real — malformed entries are skipped.
    filter_query narrows a broad Gmail q= match (which returns every
    participant on any matched thread) down to the contacts actually asked for.
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
