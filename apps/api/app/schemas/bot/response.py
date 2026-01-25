"""Bot platform response schemas."""

from pydantic import BaseModel


class BotChatResponse(BaseModel):
    """Response payload for bot chat messages."""

    response: str
    conversation_id: str
    authenticated: bool


class AuthStatusResponse(BaseModel):
    """Response payload for auth status check."""

    authenticated: bool
    platform: str
    platform_user_id: str
