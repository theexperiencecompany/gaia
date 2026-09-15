"""The user's chat-channel priority, as the settings API sends and receives it."""

from pydantic import BaseModel, Field, field_validator

from app.models.chat_models import BOT_CONVERSATION_SOURCES

#: The platform names a priority list may contain. Only bot platforms: a
#: proactive message is a text, and the web app is not somewhere GAIA can text.
CHAT_CHANNEL_VALUES: frozenset[str] = frozenset(s.value for s in BOT_CONVERSATION_SOURCES)


class ChannelPriorityList(BaseModel):
    """An ordered list of chat platforms — GAIA texts the first usable one."""

    priority: list[str] = Field(..., min_length=1)

    @field_validator("priority")
    @classmethod
    def _known_platforms_once_each(cls, value: list[str]) -> list[str]:
        """Reject anything GAIA cannot text on; collapse repeats to the first place.

        A repeat is not a user intent — the second mention can never be reached —
        so it is dropped rather than rejected, and the caller gets back the list
        that was actually stored.
        """
        unknown = [p for p in value if p not in CHAT_CHANNEL_VALUES]
        if unknown:
            raise ValueError(f"unsupported chat platforms: {', '.join(sorted(set(unknown)))}")
        return list(dict.fromkeys(value))
