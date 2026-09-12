"""The user's chat-channel priority, as the settings API sends and receives it."""

from typing import Literal, get_args

from pydantic import BaseModel, Field, field_validator

from app.models.chat_models import BOT_CONVERSATION_SOURCES

#: The platform names a priority list may contain. Only bot platforms: a
#: proactive message is a text, and the web app is not somewhere GAIA can text.
#: Spelled out so the OpenAPI schema (and the generated client type) carries the
#: closed set; ``CHAT_CHANNEL_VALUES`` below pins it to BOT_CONVERSATION_SOURCES.
ChatChannel = Literal["whatsapp", "telegram", "discord", "slack", "imessage"]

CHAT_CHANNEL_VALUES: frozenset[str] = frozenset(s.value for s in BOT_CONVERSATION_SOURCES)
if set(get_args(ChatChannel)) != CHAT_CHANNEL_VALUES:
    raise RuntimeError("ChatChannel must list exactly BOT_CONVERSATION_SOURCES")


class ChannelPriorityList(BaseModel):
    """An ordered list of chat platforms — GAIA texts the first usable one."""

    priority: list[ChatChannel] = Field(..., min_length=1)

    @field_validator("priority")
    @classmethod
    def _known_platforms_once_each(cls, value: list[ChatChannel]) -> list[ChatChannel]:
        """Collapse repeats to the first place; the Literal already rejects unknowns.

        A repeat is not a user intent — the second mention can never be reached —
        so it is dropped rather than rejected, and the caller gets back the list
        that was actually stored.
        """
        return list(dict.fromkeys(value))
