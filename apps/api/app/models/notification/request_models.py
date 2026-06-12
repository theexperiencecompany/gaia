from typing import Any

from pydantic import BaseModel, Field

from app.models.notification.notification_models import BulkActions


class BulkActionRequest(BaseModel):
    """Request model for bulk actions"""

    notification_ids: list[str]
    action: BulkActions = Field(..., description="Action to be performed on the notifications")


class NotificationResponse(BaseModel):
    """Response model for notifications"""

    success: bool
    message: str
    data: Any | None = None


class PaginatedNotificationsResponse(BaseModel):
    """Response model for paginated notifications"""

    notifications: list[dict[str, Any]]
    total: int
    limit: int
    offset: int
