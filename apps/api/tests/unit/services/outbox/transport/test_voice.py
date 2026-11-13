"""The voice transport sends the composed words into the call's own room, and says so when the room did not take them."""

from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
from livekit import api
import pytest

from app.services.outbox.metrics import OUTBOX_SPOKEN_FAILED
from app.services.outbox.transport.voice import publish_spoken
from shared.py.voice_call import OUTBOX_SPEECH_TOPIC, SpokenMessage

_MOD = "app.services.outbox.transport.voice"
ROOM = "voice_session_507f1f77bcf86cd799439011_0f3a9c"


def _livekit(send_data: AsyncMock) -> MagicMock:
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    client.room.send_data = send_data
    return client


async def test_the_parts_go_into_the_room_on_the_outbox_speech_topic() -> None:
    send_data = AsyncMock()
    with patch(f"{_MOD}.api.LiveKitAPI", return_value=_livekit(send_data)):
        assert await publish_spoken(ROOM, "msg-1", ["About the flight.", "It is booked."]) is True

    [request] = send_data.await_args.args
    assert (request.room, request.topic) == (ROOM, OUTBOX_SPEECH_TOPIC)
    assert SpokenMessage.model_validate_json(request.data) == SpokenMessage(
        message_id="msg-1", parts=["About the flight.", "It is booked."]
    )


@pytest.mark.parametrize(
    "error",
    [api.TwirpError("not_found", "room does not exist", status=404), aiohttp.ClientError("down")],
)
async def test_a_room_that_did_not_take_it_is_counted_and_reported_false(error: Exception) -> None:
    before = OUTBOX_SPOKEN_FAILED._value.get()
    with patch(f"{_MOD}.api.LiveKitAPI", return_value=_livekit(AsyncMock(side_effect=error))):
        assert await publish_spoken(ROOM, "msg-1", ["Hi."]) is False

    assert OUTBOX_SPOKEN_FAILED._value.get() == before + 1
