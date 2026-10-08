"""The tools list includes desktop-executed tools only for the desktop app."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.requests import Request

from app.api.v1.endpoints.tools import list_available_tools
from app.api.v1.middleware.client_type import CLIENT_TYPE_HEADER
from app.models.user_models import AuthenticatedUser

MODULE = "app.api.v1.endpoints.tools"


def _request(headers: dict[str, str]) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/tools",
            "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        }
    )


@pytest.mark.parametrize(
    ("headers", "include_desktop"),
    [({CLIENT_TYPE_HEADER: "desktop"}, True), ({}, False), ({CLIENT_TYPE_HEADER: "web"}, False)],
)
async def test_desktop_tools_are_listed_only_for_the_desktop_app(
    headers: dict[str, str], include_desktop: bool
) -> None:
    with (
        patch(f"{MODULE}.get_available_tools", AsyncMock(return_value=MagicMock())),
        patch(f"{MODULE}.filter_tools_response") as filter_tools,
    ):
        await list_available_tools(_request(headers), AuthenticatedUser(user_id="u1"))

    assert filter_tools.call_args.kwargs == {"include_desktop": include_desktop}
