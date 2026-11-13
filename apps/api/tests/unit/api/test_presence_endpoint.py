"""A GAIA app reports that the user is looking at it, and which app it is is read from who sent the request."""

from unittest.mock import AsyncMock, patch

import fakeredis.aioredis
from httpx import AsyncClient
import pytest

from app.models.chat_models import ConversationSource

URL = "/api/v1/presence/focus"
TAB = {"client_id": "tab-1"}
_ENDPOINT = "app.api.v1.endpoints.presence"


async def test_a_web_heartbeat_marks_the_web_app_in_view(client: AsyncClient) -> None:
    with patch(f"{_ENDPOINT}.mark_focused", AsyncMock(return_value=False)) as mark:
        resp = await client.put(URL, params=TAB)

    assert resp.status_code == 204
    [call] = mark.await_args_list
    assert call.args[1:] == (ConversationSource.WEB, "tab-1")


async def test_the_desktop_app_names_itself_in_the_client_type_header(client: AsyncClient) -> None:
    with patch(f"{_ENDPOINT}.mark_focused", AsyncMock(return_value=False)) as mark:
        resp = await client.put(URL, params=TAB, headers={"X-Client-Type": "desktop"})

    assert resp.status_code == 204
    assert mark.await_args.args[1] is ConversationSource.DESKTOP


@pytest.mark.parametrize("method", ["put", "delete"])
async def test_a_client_that_does_not_name_itself_is_refused(
    client: AsyncClient, method: str
) -> None:
    resp = await client.request(method, URL)

    assert resp.status_code == 422


async def test_the_first_beat_after_the_user_was_away_is_their_return_and_later_beats_are_not(
    client: AsyncClient, fake_redis: fakeredis.aioredis.FakeRedis
) -> None:
    with patch(f"{_ENDPOINT}.release_on_return", AsyncMock()) as released:
        await client.put(URL, params=TAB)
        await client.put(URL, params=TAB)
        await client.put(URL, params={"client_id": "tab-2"})
        released.assert_awaited_once()

        await client.delete(URL, params=TAB)
        await client.delete(URL, params={"client_id": "tab-2"})
        await client.put(URL, params=TAB)

    assert released.await_count == 2


async def test_leaving_the_app_clears_its_surface(client: AsyncClient) -> None:
    with patch(f"{_ENDPOINT}.clear_focus", AsyncMock()) as clear:
        resp = await client.delete(URL, params=TAB, headers={"X-Client-Type": "desktop"})

    assert resp.status_code == 204
    assert clear.await_args.args[1:] == (ConversationSource.DESKTOP, "tab-1")


@pytest.mark.parametrize("method", ["put", "delete"])
async def test_the_mobile_app_does_not_report_focus(client: AsyncClient, method: str) -> None:
    with (
        patch(f"{_ENDPOINT}.mark_focused", AsyncMock()) as mark,
        patch(f"{_ENDPOINT}.clear_focus", AsyncMock()) as clear,
    ):
        resp = await client.request(method, URL, params=TAB, headers={"X-Client-Type": "mobile"})

    assert resp.status_code == 400
    mark.assert_not_awaited()
    clear.assert_not_awaited()
