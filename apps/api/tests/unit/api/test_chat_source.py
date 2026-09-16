"""Unit tests for chat source resolution and voice categorization."""

from starlette.requests import Request

from app.api.v1.endpoints.chat import _resolve_source
from app.models.chat_models import BOT_CONVERSATION_SOURCES, ConversationSource, SourceCategory


def _request_with_client_type(value: str | None) -> Request:
    headers = [(b"x-client-type", value.encode())] if value is not None else []
    return Request({"type": "http", "headers": headers})


class TestResolveSource:
    def test_desktop_header_maps_to_desktop(self) -> None:
        assert _resolve_source(_request_with_client_type("desktop")) == "desktop"

    def test_voice_header_maps_to_voice(self) -> None:
        assert _resolve_source(_request_with_client_type("voice")) == "voice"

    def test_missing_header_defaults_to_web(self) -> None:
        assert _resolve_source(_request_with_client_type(None)) == "web"

    def test_unknown_header_defaults_to_web(self) -> None:
        assert _resolve_source(_request_with_client_type("toaster")) == "web"


class TestVoiceCategory:
    def test_voice_categorizes_as_ui(self) -> None:
        # First-party interactive: same effective category voice turns always
        # had via the web fallback, now with an honest source string.
        assert SourceCategory.from_source(ConversationSource.VOICE) == SourceCategory.UI
        assert SourceCategory.from_source("voice") == SourceCategory.UI

    def test_voice_is_not_a_bot_source(self) -> None:
        assert ConversationSource.VOICE not in BOT_CONVERSATION_SOURCES
