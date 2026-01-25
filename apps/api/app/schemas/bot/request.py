"""Bot platform request schemas."""

from typing import Optional

from pydantic import BaseModel


class BotChatRequest(BaseModel):
    """Request payload for bot chat messages."""

    message: str
    platform: str
    platform_user_id: str
    channel_id: Optional[str] = None
