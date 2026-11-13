"""What the API and the voice worker agree on about a live call: its heartbeat and the words sent into it."""

from typing import Final

from pydantic import BaseModel, ConfigDict, Field

#: A voice room is named voice_session_{user_id}_{uuid_hex} by the API's /token endpoint.
VOICE_ROOM_PREFIX: Final = "voice_session_"

#: The LiveKit data topic the API publishes a message to be spoken on; the worker only listens to it.
OUTBOX_SPEECH_TOPIC: Final = "outbox.speech"

#: How often the worker tells the API the call is still live.
CALL_HEARTBEAT_SECONDS: Final = 60


def voice_room_name(user_id: str, nonce: str) -> str:
    """Name the room of one voice session; nonce tells a user's sessions apart."""
    return f"{VOICE_ROOM_PREFIX}{user_id}_{nonce}"


def voice_room_user_id(room_name: str) -> str:
    """Return the user a voice room belongs to; ValueError for a room the API did not name."""
    user_id, _, nonce = room_name.removeprefix(VOICE_ROOM_PREFIX).rpartition("_")
    if not room_name.startswith(VOICE_ROOM_PREFIX) or not user_id or not nonce:
        raise ValueError(
            f"Room {room_name!r} is not a {VOICE_ROOM_PREFIX}{{user_id}}_{{uuid}} room"
        )
    return user_id


class SpokenMessage(BaseModel):
    """One outbox message to be said aloud: the words compose wrote, one part per utterance."""

    model_config = ConfigDict(frozen=True)

    message_id: str
    parts: list[str] = Field(min_length=1)
