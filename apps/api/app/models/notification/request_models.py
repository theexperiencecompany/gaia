from typing import Generic, TypeVar

from pydantic import BaseModel, Field

from app.models.notification.notification_models import (
    BulkActions,
    NotificationFilters,
    NotificationView,
)

DataT = TypeVar("DataT")


class BulkActionRequest(BaseModel):
    """Request model for bulk actions"""

    notification_ids: list[str]
    action: BulkActions = Field(..., description="Action to be performed on the notifications")


class BulkActionSummary(BaseModel):
    """Per-notification outcome of a bulk action, plus the success tally."""

    results: dict[str, bool] = Field(..., description="Per-notification-ID success flag")
    successful: int
    total: int


class NotificationQuery(NotificationFilters):
    """One notification listing: the shared filter set plus its paging window.

    The API layer, the agent tool and the eval suite all build one of these and
    hand it down unchanged, so the read path has a single argument list instead
    of the same six values re-declared at every layer. It extends
    ``NotificationFilters`` rather than restating it, so the filter vocabulary
    stays defined in exactly one place.
    """

    limit: int = 50
    offset: int = 0


class NotificationResponse(BaseModel, Generic[DataT]):
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


class PaginatedNotificationsResponse(BaseModel):
    """Response model for paginated notifications"""

    notifications: list[NotificationView]
    total: int
    limit: int
    offset: int
