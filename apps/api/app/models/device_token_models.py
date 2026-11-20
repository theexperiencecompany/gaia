"""
Device Token Models for Push Notifications
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from app.db.repositories.base import UserScopedDocument


class PlatformType(str, Enum):
    """Platform types for push notifications"""

    IOS = "ios"
    ANDROID = "android"


class PushTokenRequest(BaseModel):
    """Request model for registering a device token"""

    token: str = Field(..., description="Expo push token")
    platform: PlatformType = Field(..., description="Device platform (ios or android)")
    device_id: str | None = Field(None, description="Optional device identifier")


class PushTokenResponse(BaseModel):
    """Response model for device token operations"""

    success: bool = Field(..., description="Operation success status")
    message: str = Field(..., description="Response message")


class DeviceTokenDocument(UserScopedDocument):
    """One Expo push token and the user whose device currently holds it."""

    token: str
    platform: PlatformType
    device_id: str | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class DeviceTokenUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    platform: PlatformType | None = None
    device_id: str | None = None
    is_active: bool | None = None
