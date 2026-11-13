from pydantic import BaseModel

from app.schemas.common import ResponseModel


class ChannelPreferences(ResponseModel):
    """User notification channel preferences."""

    telegram: bool = True
    discord: bool = True
    whatsapp: bool = True
    slack: bool = True


class ChannelPreferencesUpdate(BaseModel):
    """Request body for updating channel preferences."""

    telegram: bool | None = None
    discord: bool | None = None
    whatsapp: bool | None = None
    slack: bool | None = None
