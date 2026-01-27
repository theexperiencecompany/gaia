"""Bot platform response schemas."""

from typing import List, Optional

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


class ConnectedIntegration(BaseModel):
    """User integration info for bot display."""

    id: str
    name: str
    status: str  # "created" = orange dot, "connected" = green dot


class BotSettingsResponse(BaseModel):
    """Response payload for user settings in bot."""

    authenticated: bool
    user_name: Optional[str] = None
    profile_image_url: Optional[str] = None
    account_created_at: Optional[str] = None
    selected_model_name: Optional[str] = None
    selected_model_icon_url: Optional[str] = None
    connected_integrations: List[ConnectedIntegration] = []
