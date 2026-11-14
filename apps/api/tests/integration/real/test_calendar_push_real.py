"""A calendar write tells the user's clients once, through the real Redis broadcast channel.

The web calendar caches events in React Query and re-reads them only on this push
or a reconnect, so a write that does not push leaves every open tab stale, and a
read that pushes refetches the calendar for nothing. The proxy call to Composio is the seam.
"""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
import pytest

from app.constants.calendar import CALENDAR_CHANGED_EVENT
from app.models.calendar_models import EventDeleteRequest, EventUpdateRequest
from app.services import calendar_service
from tests.helpers import published_broadcasts

USER = "calendar_push_user"
GOOGLE_EVENT = {
    "id": "evt_1",
    "summary": "Standup",
    "start": {"dateTime": "2026-11-14T09:00:00+00:00"},
    "end": {"dateTime": "2026-11-14T09:30:00+00:00"},
}


@pytest.fixture
def google() -> Iterator[AsyncMock]:
    with patch.object(calendar_service, "proxy_request", new_callable=AsyncMock) as proxy:
        proxy.return_value = GOOGLE_EVENT
        yield proxy


async def test_deleting_an_event_pushes_one_calendar_change(google, broadcast_channel) -> None:
    await calendar_service.delete_calendar_event(EventDeleteRequest(event_id="evt_1"), USER)

    assert await published_broadcasts(broadcast_channel) == [
        {"user_id": USER, "message": {"type": CALENDAR_CHANGED_EVENT}}
    ]


async def test_an_update_reads_then_writes_and_pushes_once(google, broadcast_channel) -> None:
    await calendar_service.update_calendar_event(
        EventUpdateRequest(event_id="evt_1", summary="Retro"), USER
    )

    assert [request.args[0].method for request in google.await_args_list] == ["GET", "PUT"]
    assert await published_broadcasts(broadcast_channel) == [
        {"user_id": USER, "message": {"type": CALENDAR_CHANGED_EVENT}}
    ]


async def test_a_read_pushes_nothing(google, broadcast_channel) -> None:
    google.return_value = {"items": []}

    await calendar_service.list_calendars(USER)

    assert await published_broadcasts(broadcast_channel) == []


async def test_a_refused_write_pushes_nothing(google, broadcast_channel) -> None:
    google.side_effect = HTTPException(status_code=500, detail="boom")

    with pytest.raises(HTTPException):
        await calendar_service.delete_calendar_event(EventDeleteRequest(event_id="evt_1"), USER)

    assert await published_broadcasts(broadcast_channel) == []
