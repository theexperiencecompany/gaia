"""Which first-party client a request declares itself as."""

import pytest
from starlette.requests import Request

from app.api.v1.middleware.client_type import CLIENT_TYPE_HEADER, request_client_source
from app.models.chat_models import ConversationSource


def _request(client_type: str | None) -> Request:
    headers = (
        [] if client_type is None else [(CLIENT_TYPE_HEADER.lower().encode(), client_type.encode())]
    )
    return Request(
        {"type": "http", "method": "POST", "path": "/api/v1/chat-stream", "headers": headers}
    )


@pytest.mark.unit
class TestRequestClientSource:
    @pytest.mark.parametrize(
        ("client_type", "expected"),
        [
            ("mobile", ConversationSource.MOBILE),
            (" Mobile ", ConversationSource.MOBILE),
            ("desktop", ConversationSource.DESKTOP),
            ("DESKTOP", ConversationSource.DESKTOP),
        ],
    )
    def test_a_declared_app_is_its_own_surface(
        self, client_type: str, expected: ConversationSource
    ) -> None:
        assert request_client_source(_request(client_type)) is expected

    @pytest.mark.parametrize("client_type", [None, "", "web", "telegram", "workflow_system", "tv"])
    def test_anything_else_is_the_web_app(self, client_type: str | None) -> None:
        """Only the two apps may declare themselves: a forged bot or system source would reroute delivery."""
        assert request_client_source(_request(client_type)) is ConversationSource.WEB
