"""App-shell UI events: sidebar, pins, error boundaries and failed API requests."""

from typing import ClassVar, Literal

from shared.py.analytics.catalog.base import WebEvent
from shared.py.analytics.catalog.properties import Identifier, UrlPath


class UiSidebarCollapsed(WebEvent):
    """The user collapsed the app sidebar."""

    event: ClassVar[str] = "ui:sidebar_collapsed"
    budget_per_user_day: ClassVar[int] = 10


class UiSidebarExpanded(WebEvent):
    """The user expanded the app sidebar."""

    event: ClassVar[str] = "ui:sidebar_expanded"
    budget_per_user_day: ClassVar[int] = 10


class PinViewed(WebEvent):
    """The user opened a pinned message from the pins page."""

    event: ClassVar[str] = "pin:viewed"
    budget_per_user_day: ClassVar[int] = 50

    conversation_id: Identifier
    message_id: Identifier | None = None


class ErrorOccurred(WebEvent):
    """A client error reached a boundary, or a chunk reload failed to recover."""

    event: ClassVar[str] = "error:occurred"
    budget_per_user_day: ClassVar[int] = 10

    error_type: Literal["global_error", "react_error_boundary", "chunk_load"]
    digest: Identifier | None = None
    recovery_action: Literal["terminal"] | None = None


class ErrorRouteErrorShown(WebEvent):
    """The App Router error boundary rendered its retryable error UI."""

    event: ClassVar[str] = "error:route_error_shown"
    budget_per_user_day: ClassVar[int] = 10

    error_type: Literal["app_router_error_boundary"]
    error_digest: Identifier | None = None


class ApiRequestFailed(WebEvent):
    """An API request from the browser failed."""

    event: ClassVar[str] = "api:request_failed"
    budget_per_user_day: ClassVar[int] = 500

    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
    status: int
    url: UrlPath
    # The API envelope's machine code (NOT_AUTHENTICATED, subscription_required); absent on a transport failure.
    error_code: Identifier | None = None


class ApiChunkRecovered(WebEvent):
    """A stale-chunk load error triggered a recovery reload."""

    event: ClassVar[str] = "api:chunk_recovered"
    budget_per_user_day: ClassVar[int] = 10

    error_type: Literal["chunk_load"]
    recovery_action: Literal["reload"]


__all__ = [
    "ApiChunkRecovered",
    "ApiRequestFailed",
    "ErrorOccurred",
    "ErrorRouteErrorShown",
    "PinViewed",
    "UiSidebarCollapsed",
    "UiSidebarExpanded",
]
