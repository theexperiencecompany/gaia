from datetime import datetime, timezone
from typing import Any, Dict, List

from app.config.loggers import app_logger as logger
from app.models.calendar_models import EventCreateRequest
from app.models.notification.notification_models import (
    ActionConfig,
    ActionStyle,
    ActionType,
    ApiCallConfig,
    ChannelConfig,
    ModalConfig,
    NotificationAction,
    NotificationContent,
    NotificationRequest,
    NotificationSourceEnum,
    NotificationType,
    RedirectConfig,
)
from app.services.notification_service import notification_service


class AIProactiveNotificationSource:
    """
    Notification source for AI-initiated proactive actions.

    This class contains static methods to create notifications for various
    AI-driven proactive actions like email composition, calendar events,
    and task creation that are initiated by backend workers.
    """

    @staticmethod
    async def create_calendar_event_notification(
        user_id: str,
        notification_data: List[EventCreateRequest],
        send: bool = True,
    ) -> List[NotificationRequest]:
        """Create (and optionally send) notifications for AI-generated calendar events.

        Args:
            user_id: Target user.
            notification_data: List of events to notify about.
            send: If True (default), dispatch each notification immediately via the
                notification service.  Set to False to return the requests without
                sending (useful for testing or batch handling).
        """
        try:
            requests = [
                NotificationRequest(
                    user_id=user_id,
                    source=NotificationSourceEnum.AI_CALENDAR_EVENT,
                    type=NotificationType.INFO,
                    priority=2,
                    channels=[
                        ChannelConfig(channel_type="inapp", enabled=True, priority=1)
                    ],
                    content=NotificationContent(
                        title="New Calendar Event Created",
                        body=notification.description,
                        actions=[
                            NotificationAction(
                                type=ActionType.API_CALL,
                                label="Confirm Event",
                                style=ActionStyle.SECONDARY,
                                requires_confirmation=True,
                                confirmation_message="Are you sure you want to confirm this event?",
                                config=ActionConfig(
                                    api_call=ApiCallConfig(
                                        endpoint="/api/v1/calendar/event",
                                        method="POST",
                                        payload=notification.model_dump(),
                                        success_message="Event confirmed successfully!",
                                        error_message="Failed to confirm event",
                                        is_internal=True,
                                    )
                                ),
                            ),
                        ],
                    ),
                    metadata={
                        "notification": notification.model_dump(),
                        "event_title": notification.summary,
                        "event_description": notification.description,
                    },
                )
                for notification in notification_data
            ]

            if send:
                for request in requests:
                    await notification_service.create_notification(request)

            return requests
        except Exception as e:
            logger.error(f"Failed to create calendar event notification: {e}")
            return []

    @staticmethod
    def create_mail_composition_notification(
        user_id: str,
        email_data: Dict[str, Any],
    ) -> NotificationRequest:
        """Create notification for AI-composed email drafts with Preview & Edit and Send actions"""

        email_id = email_data.get("email_id", "")
        subject = email_data.get("subject", "Untitled Email")
        body = email_data.get("body", "")
        recipients = email_data.get("to", [])
        recipient_query = email_data.get("recipient_query", "")

        # Create a friendly notification body
        recipient_text = ""
        if recipients:
            if len(recipients) == 1:
                recipient_text = f" to {recipients[0]}"
            else:
                recipient_text = f" to {len(recipients)} recipients"
        elif recipient_query:
            recipient_text = f" based on your request for '{recipient_query}'"

        notification_body = f"I've drafted an email{recipient_text} with the subject '{subject}'. You can preview and edit it before sending."

        # Create Preview & Send Action - Opens modal for editing and sending
        preview_send_action = NotificationAction(
            type=ActionType.MODAL,
            label="Preview & Send",
            style=ActionStyle.PRIMARY,
            config=ActionConfig(
                modal=ModalConfig(
                    component="EmailPreviewModal",
                    props={
                        "email_id": email_id,
                        "subject": subject,
                        "body": body,
                        "recipients": recipients,
                        "mode": "edit",
                        "recipient_query": recipient_query,
                        "notificationId": "{{notification_id}}",
                        "actionId": "{{action_id}}",
                    },
                )
            ),
            icon="mail",
        )

        return NotificationRequest(
            user_id=user_id,
            source=NotificationSourceEnum.AI_EMAIL_DRAFT,
            type=NotificationType.INFO,
            priority=2,
            channels=[ChannelConfig(channel_type="inapp", enabled=True, priority=1)],
            content=NotificationContent(
                title="Email draft ready for review",
                body=notification_body,
                actions=[preview_send_action],
            ),
            metadata={
                "mail_data": {
                    "id": email_id,
                    "subject": subject,
                    "body": body,
                    "recipients": recipients,
                },
                "recipient_query": recipient_query,
                "composed_at": datetime.now(timezone.utc).isoformat(),
            },
        )

    @staticmethod
    def create_todo_creation_notification(
        user_id: str,
        todo_data: Dict[str, Any],
    ) -> NotificationRequest:
        """Create notification for AI-created todo tasks from backend-initiated actions"""

        title = todo_data.get("title", "Untitled Task")
        description = todo_data.get("description", "")
        due_date = todo_data.get("due_date")
        priority = todo_data.get("priority", "none")
        labels = todo_data.get("labels", [])

        # Create a friendly notification body
        notification_body = f"I've created a task '{title}' for you."

        if due_date:
            notification_body += f" It's due on {due_date}."
        if priority and priority != "none":
            notification_body += f" Priority: {priority}."
        if labels:
            notification_body += f" Labels: {', '.join(labels)}."

        notification_body += " Would you like to review or modify it?"

        return NotificationRequest(
            user_id=user_id,
            source=NotificationSourceEnum.AI_TODO_ADDED,
            type=NotificationType.INFO,
            priority=2,
            channels=[ChannelConfig(channel_type="inapp", enabled=True, priority=1)],
            content=NotificationContent(
                title="New task created",
                body=notification_body,
                actions=[
                    NotificationAction(
                        type=ActionType.REDIRECT,
                        label="View Task",
                        style=ActionStyle.PRIMARY,
                        config=ActionConfig(
                            redirect=RedirectConfig(
                                url=f"/todos/?todoId={todo_data.get('id')}",
                                open_in_new_tab=False,
                                close_notification=True,
                            )
                        ),
                    ),
                    NotificationAction(
                        type=ActionType.API_CALL,
                        label="Mark Complete",
                        style=ActionStyle.SECONDARY,
                        config=ActionConfig(
                            api_call=ApiCallConfig(
                                endpoint=f"/api/v1/todos/{todo_data.get('id')}",
                                method="PUT",
                                payload={"completed": True},
                                success_message="Task marked as complete!",
                                error_message="Failed to complete task",
                                is_internal=True,
                            )
                        ),
                    ),
                ],
            ),
            metadata={
                "todo_id": todo_data.get("id"),
                "todo_title": title,
                "todo_description": (
                    description[:200] + "..." if len(description) > 200 else description
                ),
                "todo_priority": priority,
                "todo_labels": labels,
                "todo_due_date": due_date,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )

    @staticmethod
    def create_reminder_notification(
        user_id: str,
        reminder_id: str,
        title: str,
        body: str,
        actions: List[NotificationAction],
    ) -> NotificationRequest:
        """Create notification for AI-generated reminders"""
        return NotificationRequest(
            user_id=user_id,
            source=NotificationSourceEnum.AI_REMINDER,
            type=NotificationType.INFO,
            priority=1,
            channels=[ChannelConfig(channel_type="inapp", enabled=True, priority=1)],
            content=NotificationContent(
                title=title,
                body=body,
                actions=actions,
            ),
            metadata={
                "reminder_id": reminder_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )

    @staticmethod
    async def create_proactive_notification(
        user_id: str,
        conversation_id: str,
        message_id: str,
        title: str,
        body: str,
        source: NotificationSourceEnum,
        send: bool = True,
    ) -> NotificationRequest:
        """Create a generic proactive notification"""
        notification = NotificationRequest(
            user_id=user_id,
            source=source,
            type=NotificationType.INFO,
            priority=1,
            channels=[ChannelConfig(channel_type="inapp", enabled=True, priority=1)],
            content=NotificationContent(
                title=title,
                body=body,
                actions=[
                    NotificationAction(
                        type=ActionType.REDIRECT,
                        label="More Details",
                        style=ActionStyle.PRIMARY,
                        config=ActionConfig(
                            redirect=RedirectConfig(
                                close_notification=True,
                                open_in_new_tab=False,
                                url=f"/c/{conversation_id}?messageId={message_id}",
                            )
                        ),
                        icon="mail",
                    )
                ],
            ),
            metadata={
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )

        if send:
            await notification_service.create_notification(notification)

        return notification
