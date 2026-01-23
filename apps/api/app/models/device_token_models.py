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
