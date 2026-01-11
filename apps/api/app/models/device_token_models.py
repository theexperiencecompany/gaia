"""
Device Token Models for Push Notifications
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class PlatformType(str, Enum):
    """Platform types for push notifications"""

    IOS = "ios"
    ANDROID = "android"


class DeviceTokenRequest(BaseModel):
    """Request model for registering a device token"""

    token: str = Field(..., description="Expo push token")
    platform: PlatformType = Field(..., description="Device platform (ios or android)")
    device_id: Optional[str] = Field(None, description="Optional device identifier")


class DeviceTokenResponse(BaseModel):
    """Response model for device token operations"""

    success: bool = Field(..., description="Operation success status")
    message: str = Field(..., description="Response message")


class DeviceToken(BaseModel):
    """Device token document stored in MongoDB"""

    user_id: str = Field(..., description="User ID who owns this device")
    token: str = Field(..., description="Expo push token")
    platform: PlatformType = Field(..., description="Device platform")
    device_id: Optional[str] = Field(None, description="Device identifier")
    is_active: bool = Field(default=True, description="Whether token is active")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Token creation timestamp",
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Last update timestamp",
    )

    class Config:
        json_schema_extra = {
            "example": {
                "user_id": "user123",
                "token": "ExponentPushToken[xxxxxxxxxxxxxxxxxxxxxx]",
                "platform": "ios",
                "device_id": "iPhone 15 Pro",
                "is_active": True,
                "created_at": "2026-01-11T10:00:00Z",
                "updated_at": "2026-01-11T10:00:00Z",
            }
        }
