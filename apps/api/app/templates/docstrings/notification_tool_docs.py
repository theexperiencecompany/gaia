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

SEND_NOTIFICATION = """
Send a notification to the user on their connected channels (WhatsApp, Telegram, Discord, Slack, in-app).

Use this tool to proactively alert the user about something important that happened or
completed — especially when they are away from the app or the event is time-sensitive.

—WHEN TO USE (use sparingly)—
- A long-running task or workflow just finished and the user asked to be notified
- A critical event occurred that the user explicitly asked to be alerted about
- The user is expecting a result and would miss it without an explicit ping

—WHEN NOT TO USE (do not overnotify)—
- Routine task completions the user can see in the chat
- Every step of a multi-step workflow — only notify at the end
- Informational updates the user did not ask to be pinged about
- More than 1-2 times per session unless the user explicitly requests it

—CHANNEL SELECTION—
- Omit `channels` to send on ALL user-enabled channels automatically (recommended default)
- Pass specific channel names ("whatsapp", "telegram", "discord", "slack", "inapp") to target specific channels
- Use get_notification_preferences first if you need to know what channels are available

—WORKFLOW RUNS—
- When you are executing a saved workflow, the run instructions state whether GAIA already
  sends an automatic completion notification. If it does, do NOT call this tool to announce
  the result — that double-notifies the user. Only call it when the workflow's own
  instructions explicitly ask for an alert (e.g. "ping me on WhatsApp if an email is urgent").

—NOTIFICATION TYPE—
- "info" (default) — general update
- "success" — task completed successfully
- "warning" — something needs attention
- "error" — something failed

Args:
    message: Required notification body text (keep it concise and actionable)
    title: Required short, specific title summarizing the update (e.g. "Reminder",
        "Task completed", "Build failed") — never a generic app name
    channels: Optional list of channel names to target (omit for all enabled channels)
    notification_type: Optional type — "info", "success", "warning", or "error"

Returns:
    Delivery status including which channels received the notification
"""

GET_NOTIFICATION_PREFERENCES = """
Get the user's current notification channel preferences.

Returns which channels (WhatsApp, Telegram, Discord, Slack, in-app) are enabled or disabled
for the user. Use this before calling send_notification when you need to know which
channels are available, or when the user asks about their notification settings.

When to use:
- Before targeting a specific channel to verify it is enabled
- When user asks "which notification channels do I have set up?"
- When you want to inform the user about their notification settings

Returns:
    Dictionary of channel names mapped to their enabled/disabled state
"""
