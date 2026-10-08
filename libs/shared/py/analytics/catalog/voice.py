"""Voice events: the LiveKit worker's sessions and the web app's voice mode and wake word."""

from typing import ClassVar

from shared.py.analytics.catalog.base import VoiceEvent, WebEvent
from shared.py.analytics.catalog.properties import Identifier


class VoiceSessionStarted(VoiceEvent):
    """The voice worker joined a room minted for a known GAIA user."""

    event: ClassVar[str] = "voice:session_started"
    budget_per_user_day: ClassVar[int] = 20

    room: Identifier


class VoiceSessionEnded(VoiceEvent):
    """A voice session shut down; carries its usage shape, no transcript lengths."""

    event: ClassVar[str] = "voice:session_ended"
    budget_per_user_day: ClassVar[int] = 50

    user_turns: int
    user_speaking_ms: float
    tts_characters: int
    stt_audio_duration_s: float
    tokens_used: int


class VoiceModeStarted(WebEvent):
    """The browser connected the microphone and the LiveKit room for voice mode."""

    event: ClassVar[str] = "voice:mode_started"
    budget_per_user_day: ClassVar[int] = 10

    conversation_id: Identifier | None = None


class VoiceModeStopped(WebEvent):
    """The browser left a connected voice-mode room."""

    event: ClassVar[str] = "voice:mode_stopped"
    budget_per_user_day: ClassVar[int] = 20

    conversation_id: Identifier | None = None


class VoiceTranscriptionReceived(WebEvent):
    """The browser received the first live transcription of a new user utterance."""

    event: ClassVar[str] = "voice:transcription_received"
    budget_per_user_day: ClassVar[int] = 20

    conversation_id: Identifier | None = None


class WakeWordDetected(WebEvent):
    """The desktop wake-word listener heard the wake phrase."""

    event: ClassVar[str] = "wake_word:detected"
    budget_per_user_day: ClassVar[int] = 50


__all__ = [
    "VoiceModeStarted",
    "VoiceModeStopped",
    "VoiceSessionEnded",
    "VoiceSessionStarted",
    "VoiceTranscriptionReceived",
    "WakeWordDetected",
]
