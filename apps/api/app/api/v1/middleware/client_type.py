"""Which first-party client sent a request: the desktop app, the mobile app, or the web app."""

from starlette.requests import Request

from app.models.chat_models import ConversationSource

CLIENT_TYPE_HEADER = "X-Client-Type"
#: Set by the web client on requests no user action caused (polls, background sync).
REQUEST_ORIGIN_HEADER = "X-GAIA-Request-Origin"
BACKGROUND_REQUEST_ORIGIN = "background"

#: The clients that declare themselves; anything else, or no header, is the web app.
_DECLARED_CLIENTS: frozenset[ConversationSource] = frozenset(
    {ConversationSource.DESKTOP, ConversationSource.MOBILE}
)


def request_client_source(request: Request) -> ConversationSource:
    """Return DESKTOP or MOBILE when that app sent request, WEB otherwise.

    The header is self-declared, so it only ever unlocks what is harmless
    anywhere else: desktop-executed tools, the presence surface and analytics.
    """
    # Any default naming no declared client reads as WEB, so its value cannot matter.
    client_type = request.headers.get(CLIENT_TYPE_HEADER, "").strip().lower()  # pragma: no mutate
    declared = ConversationSource.coerce(client_type)
    return declared if declared in _DECLARED_CLIENTS else ConversationSource.WEB
