"""Domain senders for every platform email GAIA delivers."""

from app.config.settings import settings
from app.constants.email import (
    CONTACT_EMAIL,
    DISCORD_URL,
    FOUNDER_MEETING_URL,
    FOUNDER_SENDER,
    SUPPORT_SENDER,
    TWITTER_URL,
    WHATSAPP_URL,
)
from app.constants.log_tags import LogTag
from app.models.support_models import SupportEmailNotification, SupportRequestType
from app.services.email.models import EmailMessage
from app.services.email.providers import get_email_provider
from app.services.email.providers.base import MarketingContactsProvider
from app.services.email.service import render_email_template, send_email
from app.utils.notification.unsubscribe import build_unsubscribe_headers, build_unsubscribe_url
from shared.py.wide_events import log


def _support_request_type_label(request_type: SupportRequestType) -> str:
    return "Support Request" if request_type == SupportRequestType.SUPPORT else "Feature Request"


async def send_support_team_notification(
    notification_data: SupportEmailNotification,
) -> None:
    """Email the support team when a new support/feature request is created."""
    log.set(
        ticket_id=notification_data.ticket_id,
        request_type=notification_data.type.value,
        user_email=notification_data.user_email,
    )
    try:
        subject = f"[{notification_data.ticket_id}] New {notification_data.type.value.title()} Request: {notification_data.title}"
        html_content = render_email_template(
            "support_to_admin.html",
            request_type_label=_support_request_type_label(notification_data.type),
            ticket_id=notification_data.ticket_id,
            title=notification_data.title,
            description=notification_data.description,
            user_name=notification_data.user_name,
            user_email=notification_data.user_email,
            admin_url=f"{settings.FRONTEND_URL}/admin/support/{notification_data.ticket_id}",
            attachments=notification_data.attachments,
        )

        for support_email in notification_data.support_emails:
            try:
                await send_email(
                    EmailMessage(
                        sender=SUPPORT_SENDER,
                        to=[support_email],
                        subject=subject,
                        html=html_content,
                        reply_to=notification_data.user_email,
                    )
                )
                log.info(f"{LogTag.MAIL} Support notification sent to {support_email}")
            except Exception as e:
                log.error(f"{LogTag.MAIL} Failed to send support email to {support_email}: {e!s}")
    except Exception as e:
        log.error(f"{LogTag.MAIL} Error sending support team notifications: {e!s}")
        raise


async def send_support_to_user_email(
    notification_data: SupportEmailNotification,
) -> None:
    """Email the user confirming their support request was received."""
    try:
        subject = f"[{notification_data.ticket_id}] Your {notification_data.type.value} request has been received"
        html_content = render_email_template(
            "support_to_user.html",
            request_type_label=_support_request_type_label(notification_data.type),
            user_name=notification_data.user_name,
            ticket_id=notification_data.ticket_id,
            title=notification_data.title,
            description=notification_data.description,
            expected_response_time="24 hours",
            attachments=notification_data.attachments,
        )

        await send_email(
            EmailMessage(
                sender=SUPPORT_SENDER,
                to=[notification_data.user_email],
                subject=subject,
                html=html_content,
            )
        )
        log.info(f"{LogTag.MAIL} Confirmation email sent to user {notification_data.user_email}")
    except Exception as e:
        log.error(f"{LogTag.MAIL} Failed to send confirmation email to user: {e!s}")
        raise


async def send_pro_subscription_email(user_name: str, user_email: str) -> None:
    """Send welcome email to user who upgraded to Pro subscription."""
    try:
        html_content = render_email_template(
            "subscribed.html",
            user_name=user_name,
            discord_url=DISCORD_URL,
            whatsapp_url=WHATSAPP_URL,
            twitter_url=TWITTER_URL,
        )

        await send_email(
            EmailMessage(
                sender=FOUNDER_SENDER,
                to=[user_email],
                subject="Welcome to GAIA Pro! 🚀",
                html=html_content,
                reply_to=CONTACT_EMAIL,
            )
        )
        log.info(f"{LogTag.MAIL} Pro subscription welcome email sent to {user_email}")
    except Exception as e:
        log.error(f"{LogTag.MAIL} Failed to send pro subscription email to {user_email}: {e!s}")
        raise


async def send_welcome_email(user_email: str, user_name: str | None = None) -> None:
    """Send welcome email to a new user."""
    try:
        html_content = render_email_template(
            "welcome.html",
            user_name=user_name,
            contact_email=CONTACT_EMAIL,
            discord_url=DISCORD_URL,
            whatsapp_url=WHATSAPP_URL,
            twitter_url=TWITTER_URL,
            founder_meeting_url=FOUNDER_MEETING_URL,
            cta_url=f"{settings.FRONTEND_URL}/login",
            cta_label="Get Started",
        )

        await send_email(
            EmailMessage(
                sender=FOUNDER_SENDER,
                to=[user_email],
                subject="From the founder of GAIA, personally",
                html=html_content,
                reply_to=CONTACT_EMAIL,
            )
        )
        log.info(f"{LogTag.MAIL} Welcome email sent to {user_email}")
    except Exception as e:
        log.error(f"{LogTag.MAIL} Failed to send welcome email to {user_email}: {e!s}")
        raise


async def add_marketing_contact(user_email: str, user_name: str | None = None) -> None:
    """Add a new user to the marketing audience, if the provider supports one.

    Best-effort: never raises, so signup succeeds even when the provider call fails.
    """
    try:
        provider = get_email_provider()
        if not isinstance(provider, MarketingContactsProvider):
            log.info(
                f"{LogTag.MAIL} Email provider has no marketing audience; skipping contact {user_email}"
            )
            return
        await provider.add_contact(user_email, user_name)
        log.info(f"{LogTag.MAIL} Contact added to marketing audience: {user_email}")
    except Exception as e:
        log.error(f"{LogTag.MAIL} Failed to add marketing contact for {user_email}: {e!s}")


async def send_inactive_user_email(
    user_email: str, user_id: str, user_name: str | None = None
) -> None:
    """Send the re-engagement email to an inactive user.

    Send/skip throttling is the caller's policy (see workers/tasks/user_tasks.py).
    """
    try:
        html_content = render_email_template(
            "inactive.html",
            user_name=user_name,
            contact_email=CONTACT_EMAIL,
            cta_url=f"{settings.FRONTEND_URL}/login",
            cta_label="Log In",
            unsubscribe_url=build_unsubscribe_url(user_id),
        )

        await send_email(
            EmailMessage(
                sender=FOUNDER_SENDER,
                to=[user_email],
                subject="We miss you at GAIA 🌱",
                html=html_content,
                reply_to=CONTACT_EMAIL,
                headers=build_unsubscribe_headers(user_id),
            )
        )
        log.info(f"{LogTag.MAIL} Inactive user email sent to {user_email}")
    except Exception as e:
        log.error(f"{LogTag.MAIL} Failed to send inactive user email to {user_email}: {e!s}")
        raise
