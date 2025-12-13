from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from app.models.notification.notification_models import (
    BulkActions,
    NotificationRequest,
)


class CreateNotificationRequest(BaseModel):
    """Request model for creating notifications"""

    notification_request: NotificationRequest


class BulkActionRequest(BaseModel):
    """Request model for bulk actions"""

    notification_ids: List[str]
    action: BulkActions = Field(
        ..., description="Action to be performed on the notifications"
    )


class SnoozeRequest(BaseModel):
    """Request model for snoozing notifications"""

    snooze_until: datetime


class NotificationResponse(BaseModel):
    """Response model for notifications"""

    success: bool
    message: str
    data: Optional[Any] = None


class PaginatedNotificationsResponse(BaseModel):
    """Response model for paginated notifications"""

    notifications: List[Dict[str, Any]]
    total: int
    limit: int
    offset: int
