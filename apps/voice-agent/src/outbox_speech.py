"""Saying what the outbox sends into the call: the words compose wrote, spoken at a turn boundary."""

import asyncio

from livekit import rtc
from livekit.agents import AgentSession, UserStateChangedEvent
from pydantic import ValidationError

from shared.py.voice_call import OUTBOX_SPEECH_TOPIC, SpokenMessage
from shared.py.wide_events import log
from src.constants import LogTag
from src.utils import sanitize_for_tts


def parse_outbox_speech(packet: rtc.DataPacket) -> SpokenMessage | None:
    """Return the message a data packet carries for the outbox speech topic; None for any other packet.

    Only the API publishes on the topic, as a server: a packet a participant sent on it is
    refused, so no one in the room can put words in GAIA's mouth.
    """
    if packet.topic != OUTBOX_SPEECH_TOPIC:
        return None
    if packet.participant is not None:
        log.warning(
            f"{LogTag.AGENT} Refused outbox speech sent by a participant",
            phase="outbox_speech_refused",
            participant=packet.participant.identity,
        )
        return None
    try:
        return SpokenMessage.model_validate_json(packet.data)
    except ValidationError as e:
        log.error(
            f"{LogTag.AGENT} Outbox speech is not a spoken message",
            phase="outbox_speech_invalid",
            error=str(e),
        )
        return None


async def _until_user_stops_speaking(session: AgentSession) -> None:
    if session.user_state != "speaking":
        return
    stopped = asyncio.Event()

    def _on_user_state_changed(event: UserStateChangedEvent) -> None:
        if event.new_state != "speaking":
            stopped.set()

    session.on("user_state_changed", _on_user_state_changed)
    try:
        await stopped.wait()
    finally:
        session.off("user_state_changed", _on_user_state_changed)


async def say_when_free(session: AgentSession, message: SpokenMessage) -> None:
    """Say each part once the user is done speaking; the session queues it behind what the agent is saying."""
    await _until_user_stops_speaking(session)
    for part in message.parts:
        spoken = sanitize_for_tts(part)
        if spoken:
            session.say(spoken)
    log.info(
        f"{LogTag.AGENT} Outbox message spoken",
        phase="outbox_speech_said",
        message_id=message.message_id,
        parts=len(message.parts),
    )


def listen_for_outbox_speech(
    room: rtc.Room, session: AgentSession, tasks: set[asyncio.Task[None]]
) -> None:
    """Say every outbox message the API sends into the room; tasks keeps each saying alive until it is done."""

    @room.on("data_received")
    def _on_data(packet: rtc.DataPacket) -> None:
        message = parse_outbox_speech(packet)
        if message is None:
            return
        task = asyncio.create_task(say_when_free(session, message))
        tasks.add(task)

        def _done(finished: asyncio.Task[None]) -> None:
            tasks.discard(finished)
            if not finished.cancelled() and finished.exception():
                log.error(
                    f"{LogTag.AGENT} Outbox message not spoken",
                    exc_info=finished.exception(),
                    message_id=message.message_id,
                )

        task.add_done_callback(_done)
