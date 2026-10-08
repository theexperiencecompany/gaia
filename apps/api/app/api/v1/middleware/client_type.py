"""Which first-party client sent a request: the desktop app, or the web app."""

from starlette.requests import Request

from app.models.chat_models import ConversationSource

CLIENT_TYPE_HEADER = "X-Client-Type"


def request_client_source(request: Request) -> ConversationSource:
    """Return DESKTOP when the desktop app sent request, WEB otherwise.

    The header is self-declared, so it only ever unlocks what is harmless
    anywhere else: desktop-executed tools and the analytics surface.
    """
    client_type = request.headers.get(CLIENT_TYPE_HEADER, "").strip().lower()
    if client_type == ConversationSource.DESKTOP.value:
        return ConversationSource.DESKTOP
    return ConversationSource.WEB
