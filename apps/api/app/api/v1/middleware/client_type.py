"""Which first-party client sent a request: the desktop app, or the web app."""

from starlette.requests import Request

from app.models.chat_models import ConversationSource

CLIENT_TYPE_HEADER = "X-Client-Type"
#: Set by the web client on requests no user action caused (polls, background sync).
REQUEST_ORIGIN_HEADER = "X-GAIA-Request-Origin"
BACKGROUND_REQUEST_ORIGIN = "background"


def request_client_source(request: Request) -> ConversationSource:
    """Return DESKTOP when the desktop app sent request, WEB otherwise.

    The header is self-declared, so it only ever unlocks what is harmless
    anywhere else: desktop-executed tools and the analytics surface.
    """
    # Any default other than "desktop" reads as WEB, so its value cannot matter.
    client_type = request.headers.get(CLIENT_TYPE_HEADER, "").strip().lower()  # pragma: no mutate
    if client_type == ConversationSource.DESKTOP.value:
        return ConversationSource.DESKTOP
    return ConversationSource.WEB
