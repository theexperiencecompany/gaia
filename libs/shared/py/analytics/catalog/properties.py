"""The property kinds an analytics event may carry: counts, enums, ids, durations, booleans.

A str field is legal only as one of the id kinds below, each a pattern that
rejects whitespace, so message text, names and emails cannot be sent as a property.
"""

from dataclasses import dataclass
from typing import Annotated

from pydantic import StringConstraints


@dataclass(frozen=True, slots=True)
class IdKind:
    """Marks a constrained str as a sanctioned id kind; any other str field fails the catalog."""

    name: str


#: A Mongo ObjectId in its 24-hex string form.
ObjectIdStr = Annotated[str, StringConstraints(pattern=r"^[0-9a-fA-F]{24}$"), IdKind("object_id")]

#: A machine identifier: a uuid, a slug, a tool name, a flag key. No whitespace, no "@".
Identifier = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Za-z0-9_.:/#+\-]{1,256}$"),
    IdKind("identifier"),
]

#: A URL path with no query string, e.g. "/api/v1/chat-stream". No whitespace, "@", "?" or "#".
UrlPath = Annotated[str, StringConstraints(pattern=r"^/[^\s@?#]*$"), IdKind("url_path")]

#: A hostname as urlsplit returns it, internationalised names included. One token: no whitespace, "@" or "/".
Hostname = Annotated[str, StringConstraints(pattern=r"^[^\s@/]{1,253}$"), IdKind("hostname")]

#: An ISO 4217 currency code as the payment provider reports it ("USD", "inr").
CurrencyCode = Annotated[str, StringConstraints(pattern=r"^[A-Za-z]{3}$"), IdKind("currency_code")]

#: A single emoji: short and non-ASCII only, so no word can pass as one, or a keycap (1️⃣ #️⃣ *️⃣).
Emoji = Annotated[
    str,
    # The keycap code points are literal (not \x{...}) so the exported JSON-schema pattern is valid ECMAScript.
    StringConstraints(pattern="^(?:[0-9#*]\ufe0f?\u20e3|[^\\x00-\\x7F]{1,16})$"),
    IdKind("emoji"),
]

__all__ = ["CurrencyCode", "Emoji", "Hostname", "IdKind", "Identifier", "ObjectIdStr", "UrlPath"]
