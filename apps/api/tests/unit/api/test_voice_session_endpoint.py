"""The voice worker reports a live call; nobody else can, and never for a room that is not the user's own."""

from collections.abc import Callable
from typing import Any
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from httpx import AsyncClient
import pytest

from app.api.v1.dependencies.oauth_dependencies import get_current_user

BASE = "/api/v1/voice/session"
USER_ID = "507f1f77bcf86cd799439011"
OWN_ROOM = f"voice_session_{USER_ID}_0f3a9c"
_ENDPOINT = "app.api.v1.endpoints.voice"


@pytest.fixture
def as_voice_worker(test_app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    worker = test_app.dependency_overrides[get_current_user]().model_copy(
        update={"user_id": USER_ID, "impersonated": True}
    )
    dependency: Callable[..., Any] = get_current_user
    monkeypatch.setitem(test_app.dependency_overrides, dependency, lambda: worker)


@pytest.mark.usefixtures("as_voice_worker")
async def test_a_heartbeat_marks_the_call_live(client: AsyncClient) -> None:
    with patch(f"{_ENDPOINT}.mark_call_live", AsyncMock()) as mark:
        resp = await client.put(BASE, json={"room_name": OWN_ROOM})

    assert resp.status_code == 204
    mark.assert_awaited_once_with(USER_ID, OWN_ROOM)


@pytest.mark.usefixtures("as_voice_worker")
async def test_ending_the_call_releases_what_waited_for_it(client: AsyncClient) -> None:
    with (
        patch(f"{_ENDPOINT}.end_call", AsyncMock(return_value=True)),
        patch(f"{_ENDPOINT}.release_on_call_end", AsyncMock()) as release,
    ):
        resp = await client.post(f"{BASE}/end", json={"room_name": OWN_ROOM})

    assert resp.status_code == 204
    release.assert_awaited_once_with(USER_ID)


@pytest.mark.usefixtures("as_voice_worker")
async def test_the_late_end_of_an_old_call_releases_nothing(client: AsyncClient) -> None:
    with (
        patch(f"{_ENDPOINT}.end_call", AsyncMock(return_value=False)),
        patch(f"{_ENDPOINT}.release_on_call_end", AsyncMock()) as release,
    ):
        resp = await client.post(f"{BASE}/end", json={"room_name": OWN_ROOM})

    assert resp.status_code == 204
    release.assert_not_awaited()


@pytest.mark.usefixtures("as_voice_worker")
@pytest.mark.parametrize(
    "room", ["voice_session_507f1f77bcf86cd799439099_0f3a9c", "playground", "voice_session_"]
)
async def test_a_room_that_is_not_the_users_own_is_refused(client: AsyncClient, room: str) -> None:
    with patch(f"{_ENDPOINT}.mark_call_live", AsyncMock()) as mark:
        resp = await client.put(BASE, json={"room_name": room})

    assert resp.status_code == 403
    mark.assert_not_awaited()


async def test_a_browser_session_cannot_report_a_call(client: AsyncClient) -> None:
    with patch(f"{_ENDPOINT}.mark_call_live", AsyncMock()) as mark:
        resp = await client.put(BASE, json={"room_name": OWN_ROOM})

    assert resp.status_code == 403
    mark.assert_not_awaited()
