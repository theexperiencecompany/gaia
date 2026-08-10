from typing import Generic, TypeVar

from pydantic import BaseModel, Field

from app.models.notification.notification_models import BulkActions, NotificationView

DataT = TypeVar("DataT")


class BulkActionRequest(BaseModel):  # type: ignore[explicit-any]
    """Request model for bulk actions"""

    notification_ids: list[str]
    action: BulkActions = Field(..., description="Action to be performed on the notifications")


class BulkActionSummary(BaseModel):  # type: ignore[explicit-any]
    """Per-notification outcome of a bulk action, plus the success tally."""

    results: dict[str, bool] = Field(..., description="Per-notification-ID success flag")
    successful: int
    total: int


class NotificationResponse(BaseModel, Generic[DataT]):  # type: ignore[explicit-any]
    """The ``{success, message, data}`` envelope every notification mutation returns.

    Generic in ``data`` because the endpoints genuinely return different
    payloads under that key — a stored ``NotificationRecord`` (mark-as-read), a
    flattened ``NotificationView`` (get), a ``BulkActionSummary`` (bulk actions),
    or an action handler's free-form result (execute action). Each handler names
    its own ``DataT`` rather than sharing one ``Any``.
    """

    success: bool
    message: str
    data: DataT | None = None


class PaginatedNotificationsResponse(BaseModel):  # type: ignore[explicit-any]
    """Response model for paginated notifications"""

    notifications: list[NotificationView]
    total: int
    limit: int
    offset: int
