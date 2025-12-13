"""Docstrings for notification-related tools."""

GET_NOTIFICATIONS = """
Get user notifications with filtering options.

Retrieves notifications from the user's notification inbox with support
for filtering by status, type, and source. Returns a notification list UI.

When to use:
- When user asks to see their notifications
- When checking for specific type or status of notifications
- When browsing notification history

Args:
    status: Optional NotificationStatus enum (pending/delivered/read/archived)
    notification_type: Optional NotificationType enum (info/warning/error/success)
    source: Optional NotificationSourceEnum for filtering by source
    limit: Maximum results (default: 50)
    offset: Pagination offset (default: 0)

Returns:
    List of notification objects in a notification list UI component
"""

SEARCH_NOTIFICATIONS = """
Search notifications by content.

Performs text search across notification titles and body content with
optional status filtering. Returns matching notifications in a list UI.

When to use:
- When user wants to find specific notifications by content
- When searching for notifications about a particular topic

Args:
    query: Required search text to match against notification content
    status: Optional NotificationStatus enum for filtering
    limit: Maximum results (default: 20)

Returns:
    List of matching notifications in a notification list UI component
"""

GET_NOTIFICATION_COUNT = """
Get count of notifications with optional filtering.

Returns the total count of notifications matching the filter criteria.

When to use:
- When user asks how many notifications they have
- When displaying notification statistics

Args:
    status: Optional NotificationStatus enum for filtering

Returns:
    Total count of matching notifications
"""

MARK_NOTIFICATIONS_READ = """
Mark notifications as read.

Marks one or more notifications as read. Accepts a list of notification IDs
and handles both single and bulk operations.

When to use:
- When user marks notifications as read
- When processing notification interactions

Args:
    notification_ids: Required list of notification IDs to mark as read

Returns:
    Success status of the operation
"""
