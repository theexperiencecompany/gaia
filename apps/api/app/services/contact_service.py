"""Service functions for handling contact-related operations."""

from email.utils import getaddresses

from app.models.composio_schemas.gmail import GmailContact, GmailContactList
from app.models.integrations.gmail_messages import GmailApiMessage

_ADDRESS_HEADERS = ("From", "To", "Cc", "Reply-To")


def _display_order(contact: GmailContact) -> str:
    return contact["name"] or contact["email"]


def build_contact_index(
    messages: list[GmailApiMessage],
    filter_query: str | None = None,
) -> GmailContactList:
    """Extract unique contacts from already-fetched Gmail messages' address headers.

    filter_query narrows a broad Gmail q= match (which returns every
    participant on any matched thread) down to the contacts actually asked for.
    """
    contact_dict: dict[str, GmailContact] = {}
    query_lower = filter_query.lower() if filter_query else None

    for message in messages:
        message_headers = message.payload.headers if message.payload else []
        # A repeated header resolves to its last value.
        headers = {h.name: h.value for h in message_headers}

        # email.utils.getaddresses correctly handles names with embedded
        # commas (e.g., '"Doe, John" <john@example.com>') that a naive
        # split-on-comma would mangle.
        raw_values = [value for field in _ADDRESS_HEADERS if (value := headers.get(field))]
        for name, email in getaddresses(raw_values):
            if "@" not in email or "." not in email:
                continue
            if query_lower and query_lower not in name.lower() and query_lower not in email.lower():
                continue
            known: GmailContact | None = contact_dict.get(email)
            if known is None or (name and not known["name"]):
                contact_dict[email] = {"name": name, "email": email}

    contacts = sorted(contact_dict.values(), key=_display_order)
    return {
        "success": True,
        "contacts": contacts,
        "count": len(contacts),
    }
