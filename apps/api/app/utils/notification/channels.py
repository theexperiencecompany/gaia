import asyncio
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Dict, List

import aiohttp

from app.config.settings import settings
from app.models.notification.notification_models import (
    ActionType,
    ChannelDeliveryStatus,
    NotificationRequest,
    NotificationStatus,
)
from app.services.platform_link_service import PlatformLinkService


# Abstract Base Classes
class ChannelAdapter(ABC):
    """Base class for all notification channel adapters"""

    @property
    @abstractmethod
    def channel_type(self) -> str:
        pass

    @abstractmethod
    def can_handle(self, notification: NotificationRequest) -> bool:
        pass

    @abstractmethod
    async def transform(self, notification: NotificationRequest) -> Dict[str, Any]:
        """Transform notification content for this channel"""
        pass

    @abstractmethod
    async def deliver(
        self, content: Dict[str, Any], user_id: str
    ) -> ChannelDeliveryStatus:
        """Deliver notification via this channel"""
        pass


# Concrete Implementations
class InAppChannelAdapter(ChannelAdapter):
    """In-app notification channel adapter"""

    @property
    def channel_type(self) -> str:
        return "inapp"

    def can_handle(self, notification: NotificationRequest) -> bool:
        return any(ch.channel_type == "inapp" for ch in notification.channels)

    async def transform(self, notification: NotificationRequest) -> Dict[str, Any]:
        """Transform for in-app display"""
        return {
            "id": notification.id,
            "title": notification.content.title,
            "body": notification.content.body,
            "type": notification.type,
            "priority": notification.priority,
            "actions": [
                {
                    "id": action.id,
                    "type": action.type,
                    "label": action.label,
                    "style": action.style,
                    "requires_confirmation": action.requires_confirmation,
                    "confirmation_message": action.confirmation_message,
                    "config": action.config.dict(),
                }
                for action in (notification.content.actions or [])
            ],
            "metadata": notification.metadata,
            "created_at": notification.created_at.isoformat(),
        }

    async def deliver(
        self, content: Dict[str, Any], user_id: str
    ) -> ChannelDeliveryStatus:
        """Store in database and send via WebSocket"""
        try:
            # In a real implementation, you'd:
            # 1. Store in database
            # 2. Send via WebSocket to connected clients
            # 3. Handle offline users

            logging.info(
                f"Delivering in-app notification to user {user_id}: {content['title']}"
            )

            return ChannelDeliveryStatus(
                channel_type="inapp",
                status=NotificationStatus.DELIVERED,
                delivered_at=datetime.now(timezone.utc),
            )
        except Exception as e:
            return ChannelDeliveryStatus(
                channel_type="inapp",
                status=NotificationStatus.PENDING,
                error_message=str(e),
            )


class EmailChannelAdapter(ChannelAdapter):
    """Email notification channel adapter"""

    @property
    def channel_type(self) -> str:
        return "email"

    def can_handle(self, notification: NotificationRequest) -> bool:
        return any(ch.channel_type == "email" for ch in notification.channels)

    async def transform(self, notification: NotificationRequest) -> Dict[str, Any]:
        """Transform for email delivery"""
        # Convert actions to email-friendly format
        action_links = []
        for action in notification.content.actions or []:
            if action.type == ActionType.REDIRECT:
                if not action.config.redirect:
                    logging.warning(
                        f"Redirect action {action.id} missing config for notification {notification.id}"
                    )
                    continue

                action_links.append(
                    {"text": action.label, "url": action.config.redirect.url}
                )
            elif action.type == ActionType.API_CALL:
                # Create a secure callback URL for API actions
                callback_url = (
                    f"/api/notifications/{notification.id}/actions/{action.id}/execute"
                )
                action_links.append(
                    {
                        "text": action.label,
                        "url": f"https://your-app.com{callback_url}?token=secure_token",
                    }
                )

        return {
            "subject": f"[Notification] {notification.content.title}",
            "html_body": self._generate_html_email(notification, action_links),
            "text_body": self._generate_text_email(notification, action_links),
            "metadata": notification.metadata,
        }

    def _generate_html_email(
        self, notification: NotificationRequest, action_links: List[Dict]
    ) -> str:
        """Generate HTML email content"""
        actions_html = ""
        if action_links:
            actions_html = "<div style='margin-top: 20px;'>"
            for link in action_links:
                actions_html += f"""
                <a href="{link["url"]}"
                   style="display: inline-block; padding: 10px 20px; margin: 5px;
                          background-color: #007bff; color: white; text-decoration: none;
                          border-radius: 5px;">
                    {link["text"]}
                </a>
                """
            actions_html += "</div>"

        return f"""
        <html>
        <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
            <h2 style="color: #333;">{notification.content.title}</h2>
            <p style="color: #666; line-height: 1.6;">{notification.content.body}</p>
            {actions_html}
            <hr style="margin: 30px 0; border: none; border-top: 1px solid #eee;">
            <p style="color: #999; font-size: 12px;">
                This notification was sent from your AI Assistant at {notification.created_at.strftime("%Y-%m-%d %H:%M:%S UTC")}
            </p>
        </body>
        </html>
        """

    def _generate_text_email(
        self, notification: NotificationRequest, action_links: List[Dict]
    ) -> str:
        """Generate plain text email content"""
        text = f"{notification.content.title}\n\n{notification.content.body}\n\n"

        if action_links:
            text += "Actions:\n"
            for link in action_links:
                text += f"- {link['text']}: {link['url']}\n"

        text += f"\n---\nSent at {notification.created_at.strftime('%Y-%m-%d %H:%M:%S UTC')}"
        return text

    async def deliver(
        self, content: Dict[str, Any], user_id: str
    ) -> ChannelDeliveryStatus:
        """Send email via email service"""
        try:
            # In a real implementation, you'd integrate with:
            # - SendGrid, AWS SES, Mailgun, etc.
            # - Get user's email from user service

            logging.info(f"Sending email to user {user_id}: {content['subject']}")

            # Simulate email sending
            await asyncio.sleep(0.1)  # Simulate network delay

            return ChannelDeliveryStatus(
                channel_type="email",
                status=NotificationStatus.DELIVERED,
                delivered_at=datetime.now(timezone.utc),
            )
        except Exception as e:
            return ChannelDeliveryStatus(
                channel_type="email",
                status=NotificationStatus.PENDING,
                error_message=str(e),
            )


class TelegramChannelAdapter(ChannelAdapter):
    """Delivers notifications to a user's linked Telegram account."""

    @property
    def channel_type(self) -> str:
        return "telegram"

    def can_handle(self, notification: NotificationRequest) -> bool:
        return True

    async def transform(self, notification: NotificationRequest) -> Dict[str, Any]:
        content = notification.content
        title = content.title or ""
        body = content.body or ""
        text = f"*{title}*\n{body}" if title else body
        return {"text": text}

    async def deliver(
        self, content: Dict[str, Any], user_id: str
    ) -> ChannelDeliveryStatus:
        linked = await PlatformLinkService.get_linked_platforms(user_id)
        telegram_info = linked.get("telegram")

        if not telegram_info:
            return ChannelDeliveryStatus(
                channel_type=self.channel_type,
                status=NotificationStatus.PENDING,
                skipped=True,
                error_message="telegram not linked",
            )

        chat_id = telegram_info.get("id")
        if not chat_id:
            return ChannelDeliveryStatus(
                channel_type=self.channel_type,
                status=NotificationStatus.PENDING,
                skipped=True,
                error_message="telegram chat_id missing",
            )

        token = settings.TELEGRAM_BOT_TOKEN
        if not token:
            return ChannelDeliveryStatus(
                channel_type=self.channel_type,
                status=NotificationStatus.PENDING,
                skipped=True,
                error_message="telegram bot token not configured",
            )

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": content["text"],
            "parse_mode": "Markdown",
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload) as resp:
                    if resp.status == 200:
                        return ChannelDeliveryStatus(
                            channel_type=self.channel_type,
                            status=NotificationStatus.DELIVERED,
                            delivered_at=datetime.now(timezone.utc),
                        )
                    error = await resp.text()
                    return ChannelDeliveryStatus(
                        channel_type=self.channel_type,
                        status=NotificationStatus.PENDING,
                        error_message=f"Telegram API error {resp.status}: {error}",
                    )
        except Exception as exc:
            return ChannelDeliveryStatus(
                channel_type=self.channel_type,
                status=NotificationStatus.PENDING,
                error_message=str(exc),
            )
