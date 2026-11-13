"""What the outbox sends into the call is spoken as composed, at a turn boundary, and only when the API sent it."""

import asyncio
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock

from livekit import rtc
from livekit.agents import AgentSession
from src.outbox_speech import listen_for_outbox_speech, parse_outbox_speech, say_when_free

from shared.py.voice_call import OUTBOX_SPEECH_TOPIC, SpokenMessage

MESSAGE = SpokenMessage(message_id="msg-1", parts=["About the flight.", "It is *booked*."])


def _packet(
    data: bytes, *, topic: str | None = OUTBOX_SPEECH_TOPIC, participant: object = None
) -> rtc.DataPacket:
    return cast(
        rtc.DataPacket,
        SimpleNamespace(data=data, topic=topic, participant=participant, kind=0),
    )


class _Session:
    """The slice of AgentSession the speaker uses: user state, state-change listeners and say."""

    def __init__(self, user_state: str = "listening") -> None:
        self.user_state = user_state
        self.said: list[str] = []
        self.listeners: list[Any] = []

    def on(self, _event: str, handler: Any) -> None:
        self.listeners.append(handler)

    def off(self, _event: str, handler: Any) -> None:
        self.listeners.remove(handler)

    def say(self, text: str) -> None:
        self.said.append(text)

    def user_stops_speaking(self) -> None:
        self.user_state = "listening"
        for handler in list(self.listeners):
            handler(SimpleNamespace(new_state="listening"))


def test_a_message_the_api_sent_is_read_from_the_packet() -> None:
    assert parse_outbox_speech(_packet(MESSAGE.model_dump_json().encode())) == MESSAGE


def test_a_packet_on_another_topic_is_not_for_the_speaker() -> None:
    assert parse_outbox_speech(_packet(b"{}", topic="backend-stream-event")) is None


def test_a_packet_a_participant_sent_on_the_topic_is_refused() -> None:
    sender = SimpleNamespace(identity="user_1")

    assert (
        parse_outbox_speech(_packet(MESSAGE.model_dump_json().encode(), participant=sender)) is None
    )


def test_a_payload_that_is_not_a_spoken_message_is_dropped() -> None:
    assert parse_outbox_speech(_packet(b'{"message_id": "m", "parts": []}')) is None
    assert parse_outbox_speech(_packet(b"not json")) is None


async def _test_each_part_is_said_sanitised_when_the_user_is_not_speaking() -> None:
    session = _Session()

    await say_when_free(cast(AgentSession, session), MESSAGE)

    assert session.said == ["About the flight.", "It is booked ."]


async def _test_nothing_is_said_over_the_user_until_they_stop() -> None:
    session = _Session(user_state="speaking")
    saying = asyncio.create_task(say_when_free(cast(AgentSession, session), MESSAGE))
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert session.said == []

    session.user_stops_speaking()
    await saying

    assert len(session.said) == 2
    assert session.listeners == []


async def _test_a_data_packet_in_the_room_is_spoken() -> None:
    handlers: dict[str, Any] = {}
    room = MagicMock()
    room.on.side_effect = lambda event: lambda handler: handlers.setdefault(event, handler)
    session = _Session()
    tasks: set[asyncio.Task[None]] = set()

    listen_for_outbox_speech(room, cast(AgentSession, session), tasks)
    handlers["data_received"](_packet(MESSAGE.model_dump_json().encode()))
    await asyncio.gather(*tasks)

    assert session.said == ["About the flight.", "It is booked ."]
    assert tasks == set()


def test_each_part_is_said_sanitised_when_the_user_is_not_speaking() -> None:
    asyncio.run(_test_each_part_is_said_sanitised_when_the_user_is_not_speaking())


def test_nothing_is_said_over_the_user_until_they_stop() -> None:
    asyncio.run(_test_nothing_is_said_over_the_user_until_they_stop())


def test_a_data_packet_in_the_room_is_spoken() -> None:
    asyncio.run(_test_a_data_packet_in_the_room_is_spoken())
