"""A GAIA app reports that the user is looking at it, and which app it is is read from who sent the request."""

from unittest.mock import AsyncMock, patch

from httpx import AsyncClient
import pytest

from app.models.chat_models import ConversationSource

URL = "/api/v1/presence/focus"
_ENDPOINT = "app.api.v1.endpoints.presence"


async def test_a_web_heartbeat_marks_the_web_app_in_view(client: AsyncClient) -> None:
    with patch(f"{_ENDPOINT}.mark_focused", AsyncMock()) as mark:
        resp = await client.put(URL)

    assert resp.status_code == 204
    [call] = mark.await_args_list
    assert call.args[1] is ConversationSource.WEB


async def test_the_desktop_app_names_itself_in_the_client_type_header(client: AsyncClient) -> None:
    with patch(f"{_ENDPOINT}.mark_focused", AsyncMock()) as mark:
        resp = await client.put(URL, headers={"X-Client-Type": "desktop"})

    assert resp.status_code == 204
    assert mark.await_args.args[1] is ConversationSource.DESKTOP


async def test_leaving_the_app_clears_its_surface(client: AsyncClient) -> None:
    with patch(f"{_ENDPOINT}.clear_focus", AsyncMock()) as clear:
        resp = await client.delete(URL, headers={"X-Client-Type": "desktop"})

    assert resp.status_code == 204
    assert clear.await_args.args[1] is ConversationSource.DESKTOP


@pytest.mark.parametrize("method", ["put", "delete"])
async def test_the_mobile_app_does_not_report_focus(client: AsyncClient, method: str) -> None:
    with (
        patch(f"{_ENDPOINT}.mark_focused", AsyncMock()) as mark,
        patch(f"{_ENDPOINT}.clear_focus", AsyncMock()) as clear,
    ):
        resp = await client.request(method, URL, headers={"X-Client-Type": "mobile"})

    assert resp.status_code == 400
    mark.assert_not_awaited()
    clear.assert_not_awaited()
