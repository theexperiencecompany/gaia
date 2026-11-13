"""The voice transport: words said aloud in the user's live call, through the call's own room."""

import aiohttp
from livekit import api

from app.config.settings import settings
from app.constants.log_tags import LogTag
from app.services.outbox.metrics import OUTBOX_SPOKEN_FAILED
from shared.py.voice_call import OUTBOX_SPEECH_TOPIC, SpokenMessage
from shared.py.wide_events import log


async def publish_spoken(room_name: str, message_id: str, parts: list[str]) -> bool:
    """Send the composed parts into the call's room for the voice worker to say; False when the room did not take them.

    Best-effort by contract: the message is recorded and shown in the app either way, so a
    room that closed a moment ago is logged and counted, never raised on.
    """
    payload = SpokenMessage(message_id=message_id, parts=parts).model_dump_json().encode()
    try:
        async with api.LiveKitAPI(
            settings.LIVEKIT_URL, settings.LIVEKIT_API_KEY, settings.LIVEKIT_API_SECRET
        ) as livekit:
            await livekit.room.send_data(
                api.SendDataRequest(
                    room=room_name,
                    data=payload,
                    kind=api.DataPacket.Kind.RELIABLE,
                    topic=OUTBOX_SPEECH_TOPIC,
                )
            )
    except (api.TwirpError, aiohttp.ClientError, TimeoutError) as e:
        OUTBOX_SPOKEN_FAILED.inc()
        log.error(
            f"{LogTag.NOTIFICATION} Spoken outbox message not delivered to the call",
            room=room_name,
            error_type=type(e).__name__,
            error=str(e),
        )
        return False
    return True
