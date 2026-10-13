"""Bot events: platform I/O the bot runtime owns, plus the bot routes the API serves."""

from typing import ClassVar, Literal

from shared.py.analytics.catalog.base import BotEvent, ServerEvent
from shared.py.analytics.catalog.properties import Identifier

__all__ = [
    "BotAudioTranscribed",
    "BotAuthInitiated",
    "BotChatCompleted",
    "BotChatStarted",
    "BotCommandExecuted",
    "BotError",
    "BotFileDelivered",
    "BotFileUploaded",
    "BotMessageReceived",
    "BotReactionDelivered",
    "BotSessionReset",
]


class BotMessageReceived(BotEvent):
    """A bot received a slash command or a chat message from a platform user."""

    event: ClassVar[str] = "bot:message_received"
    budget_per_user_day: ClassVar[int] = 50

    interaction_type: Literal["command", "chat"]
    command: Identifier | None = None
    has_args: bool | None = None
    has_raw_text: bool | None = None
    message_length: int | None = None


class BotCommandExecuted(BotEvent):
    """A bot slash command finished, successfully or not."""

    event: ClassVar[str] = "bot:command_executed"
    budget_per_user_day: ClassVar[int] = 10

    command: Identifier
    duration_ms: int
    success: bool
    # The error class name only: raw messages can carry paths or echoed tokens.
    error_type: Identifier | None = None


class BotChatStarted(BotEvent):
    """A bot began streaming a chat turn for a platform user."""

    event: ClassVar[str] = "bot:chat_started"
    budget_per_user_day: ClassVar[int] = 50

    message_length: int
    streaming_enabled: bool


class BotChatCompleted(BotEvent):
    """A bot chat turn finished without an auth or generic error."""

    event: ClassVar[str] = "bot:chat_completed"
    budget_per_user_day: ClassVar[int] = 50

    duration_ms: int
    response_length: int
    streaming_enabled: bool


class BotAuthInitiated(BotEvent):
    """A platform user ran the auth command to link their GAIA account."""

    event: ClassVar[str] = "bot:auth_initiated"
    budget_per_user_day: ClassVar[int] = 10


class BotError(BotEvent):
    """A bot command or chat stream failed."""

    event: ClassVar[str] = "bot:error"
    budget_per_user_day: ClassVar[int] = 10

    context: Identifier
    error_type: Identifier | None = None
    duration_ms: int | None = None


class BotFileUploaded(BotEvent):
    """A platform user sent the bot an attachment; outcome says whether it was ingested."""

    event: ClassVar[str] = "bot:file_uploaded"
    budget_per_user_day: ClassVar[int] = 10

    media_kind: Identifier
    is_voice_note: bool
    outcome: Literal["ingested", "rejected"]


class BotFileDelivered(BotEvent):
    """A bot tried to hand a generated artifact back to the user, successfully or not."""

    event: ClassVar[str] = "bot:file_delivered"
    budget_per_user_day: ClassVar[int] = 50

    success: bool
    bytes: int
    reason: Literal["too_large"] | None = None
    limit: int | None = None
    delivery_kind: Literal["image", "document"] | None = None


class BotReactionDelivered(BotEvent):
    """A bot attached a native emoji reaction, or fell back to sending it as text."""

    event: ClassVar[str] = "bot:reaction_delivered"
    budget_per_user_day: ClassVar[int] = 10

    success: bool
    surface: Literal["live", "outbound"]
    delivery: Literal["native", "fallback_text"]
    reason: Identifier | None = None


class BotSessionReset(ServerEvent):
    """A bot user started a new conversation, archiving the current one."""

    event: ClassVar[str] = "bot:session_reset"
    budget_per_user_day: ClassVar[int] = 50

    platform: Identifier


class BotAudioTranscribed(ServerEvent):
    """The API transcribed a bot voice note; lengths only, the transcript is user speech."""

    event: ClassVar[str] = "bot:audio_transcribed"
    budget_per_user_day: ClassVar[int] = 50

    audio_bytes: int
    transcript_length: int
