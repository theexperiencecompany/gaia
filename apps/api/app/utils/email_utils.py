"""
Email utilities for sending various types of emails and parsing email content.

This module provides functions for:
- Sending different types of emails (support, onboarding, engagement)
- Parsing and extracting content from email messages (Gmail/Composio formats)

All emails use Jinja2 templates for HTML generation and Resend for email delivery.
"""

import os
from typing import Optional

import resend
from bson import ObjectId
from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.config.loggers import app_logger as logger
from app.config.settings import settings
from app.models.support_models import SupportEmailNotification, SupportRequestType
from app.db.mongodb.collections import users_collection
from datetime import datetime, timezone


# Initialize Resend with API key
resend.api_key = settings.RESEND_API_KEY

# Get the directory where templates are stored
TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates")

# Initialize Jinja2 environment for template rendering
jinja_env = Environment(
    loader=FileSystemLoader(TEMPLATES_DIR),
    autoescape=select_autoescape(["html", "xml"]),
)

CONTACT_EMAIL = "aryan@heygaia.io"
DISCORD_URL = "https://discord.heygaia.io"
WHATSAPP_URL = "https://whatsapp.heygaia.io"
TWITTER_URL = "https://twitter.com/trygaia"


async def send_support_team_notification(
    notification_data: SupportEmailNotification,
) -> None:
    """
    Send email notification to support team when a new support/feature request is created.

    Args:
        notification_data: Support email notification data containing ticket details

    Raises:
        Exception: If email sending fails
    """
    try:
        subject = f"[{notification_data.ticket_id}] New {notification_data.type.value.title()} Request: {notification_data.title}"
        html_content = generate_support_team_email_html(notification_data)

        for support_email in notification_data.support_emails:
            try:
                resend.Emails.send(
                    {
                        "from": "GAIA Support <support@heygaia.io>",
                        "to": [support_email],
                        "subject": subject,
                        "html": html_content,
                        "reply_to": notification_data.user_email,
                    }
                )
                logger.info(f"Support notification sent to {support_email}")
            except Exception as e:
                logger.error(
                    f"Failed to send support email to {support_email}: {str(e)}"
                )
    except Exception as e:
        logger.error(f"Error sending support team notifications: {str(e)}")
        raise


async def send_support_to_user_email(
    notification_data: SupportEmailNotification,
) -> None:
    """
    Send confirmation email to user that their support request has been received.

    Args:
        notification_data: Support email notification data containing ticket details

    Raises:
        Exception: If email sending fails
    """
    try:
        subject = f"[{notification_data.ticket_id}] Your {notification_data.type.value} request has been received"
        html_content = generate_support_to_user_email_html(notification_data)

        resend.Emails.send(
            {
                "from": "GAIA support <support@heygaia.io>",
                "to": [notification_data.user_email],
                "subject": subject,
                "html": html_content,
            }
        )
        logger.info(f"Confirmation email sent to user {notification_data.user_email}")
    except Exception as e:
        logger.error(f"Failed to send confirmation email to user: {str(e)}")
        raise


def generate_support_team_email_html(data: SupportEmailNotification) -> str:
    """
    Generate HTML email content for support team notifications using Jinja2 template.

    Args:
        data: Support email notification data

    Returns:
        str: Rendered HTML email content

    Raises:
        Exception: If template rendering fails
    """
    try:
        template = jinja_env.get_template("support_to_admin.html")

        request_type_label = (
            "Support Request"
            if data.type == SupportRequestType.SUPPORT
            else "Feature Request"
        )

        # Render template with data
        html_content = template.render(
            request_type_label=request_type_label,
            ticket_id=data.ticket_id,
            title=data.title,
            description=data.description,
            user_name=data.user_name,
            user_email=data.user_email,
            admin_url=f"{settings.FRONTEND_URL}/admin/support/{data.ticket_id}",
            attachments=data.attachments,
        )

        return html_content
    except Exception as e:
        logger.error(f"Error generating support team email HTML: {str(e)}")
        raise


def generate_support_to_user_email_html(data: SupportEmailNotification) -> str:
    """
    Generate HTML email content for user confirmation emails using Jinja2 template.

    Args:
        data: Support email notification data

    Returns:
        str: Rendered HTML email content

    Raises:
        Exception: If template rendering fails
    """
    try:
        template = jinja_env.get_template("support_to_user.html")

        request_type_label = (
            "Support Request"
            if data.type == SupportRequestType.SUPPORT
            else "Feature Request"
        )

        # Render template with data
        html_content = template.render(
            request_type_label=request_type_label,
            user_name=data.user_name,
            ticket_id=data.ticket_id,
            title=data.title,
            description=data.description,
            expected_response_time="24 hours",
            attachments=data.attachments,
        )

        return html_content
    except Exception as e:
        logger.error(f"Error generating support to user email HTML: {str(e)}")
        raise


async def send_pro_subscription_email(
    user_name: str,
    user_email: str,
    discord_url: str = DISCORD_URL,
    whatsapp_url: str = WHATSAPP_URL,
    twitter_url: str = TWITTER_URL,
) -> None:
    """Send welcome email to user who upgraded to Pro subscription."""
    try:
        subject = "Welcome to GAIA Pro! 🚀"
        html_content = generate_pro_subscription_html(
            user_name=user_name,
            discord_url=discord_url,
            whatsapp_url=whatsapp_url,
            twitter_url=twitter_url,
        )

        resend.Emails.send(
            {
                "from": f"Aryan from GAIA <{CONTACT_EMAIL}>",
                "to": [user_email],
                "subject": subject,
                "html": html_content,
                "reply_to": CONTACT_EMAIL,
            }
        )
        logger.info(f"Pro subscription welcome email sent to {user_email}")
    except Exception as e:
        logger.error(f"Failed to send pro subscription email to {user_email}: {str(e)}")
        raise


async def send_welcome_email(user_email: str, user_name: Optional[str] = None) -> None:
    """Send welcome email to new user using Jinja2 template."""
    try:
        subject = "From the founder of GAIA, personally"
        html_content = generate_welcome_email_html(user_name)

        if html_content is None:
            raise ValueError("Failed to generate email HTML content")

        resend.Emails.send(
            {
                "from": f"Aryan from GAIA <{CONTACT_EMAIL}>",
                "to": [user_email],
                "subject": subject,
                "html": html_content,
                "reply_to": CONTACT_EMAIL,
            }
        )
        logger.info(f"Welcome email sent to {user_email}")
    except Exception as e:
        logger.error(f"Failed to send welcome email to {user_email}: {str(e)}")
        raise


async def add_contact_to_resend(
    user_email: str, user_name: Optional[str] = None
) -> None:
    """Add new user contact to Resend audience."""
    try:
        # Split name into first and last name
        first_name = ""
        last_name = ""

        if user_name:
            name_parts = user_name.strip().split()
            first_name = name_parts[0] if name_parts else ""
            last_name = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""

        params: resend.Contacts.CreateParams = {
            "email": user_email,
            "first_name": first_name,
            "last_name": last_name,
            "unsubscribed": False,
            "audience_id": settings.RESEND_AUDIENCE_ID,
        }

        resend.Contacts.create(params)
        logger.info(f"Contact added to Resend audience: {user_email}")
    except Exception as e:
        logger.error(
            f"Failed to add contact to Resend audience for {user_email}: {str(e)}"
        )
        # Don't raise exception - user creation should still succeed even if contact addition fails


def generate_welcome_email_html(user_name: Optional[str] = None) -> str | None:
    """Generate HTML email content for welcome email using Jinja2 template."""
    try:
        template = jinja_env.get_template("welcome.html")

        # Render template with data
        html_content = template.render(
            user_name=user_name,
            contact_email=CONTACT_EMAIL,
            discord_url=DISCORD_URL,
            whatsapp_url=WHATSAPP_URL,
            twitter_url=TWITTER_URL,
        )

        return html_content
    except Exception as e:
        logger.error(f"Error generating welcome email HTML: {str(e)}")
        raise


async def send_inactive_user_email(
    user_email: str, user_name: Optional[str] = None, user_id: Optional[str] = None
) -> bool:
    """
    Send email to inactive user and track when sent to prevent spam.

    Args:
        user_email: Email address of the inactive user
        user_name: Name of the user (optional)
        user_id: User ID for tracking (optional)

    Returns:
        True if email was sent, False if skipped
    """

    try:
        # If user_id provided, check if we should send email
        if user_id:
            user = await users_collection.find_one({"_id": ObjectId(user_id)})
            if not user:
                logger.error(f"User {user_id} not found")
                return False

            now = datetime.now(timezone.utc)
            last_active = user.get("last_active_at")
            last_email_sent = user.get("last_inactive_email_sent")

            # Ensure datetimes are timezone-aware for comparison
            if last_active and last_active.tzinfo is None:
                last_active = last_active.replace(tzinfo=timezone.utc)
            if last_email_sent and last_email_sent.tzinfo is None:
                last_email_sent = last_email_sent.replace(tzinfo=timezone.utc)

            # Check if user is inactive long enough (7+ days)
            if not last_active or (now - last_active).days < 7:
                return False

            # Skip if email sent in last 7 days
            if last_email_sent and (now - last_email_sent).days < 7:
                return False

            # Max 2 emails: first after 7 days, second after 14 days
            days_inactive = (now - last_active).days
            if last_email_sent and days_inactive >= 14:
                return False  # Already sent 2 emails, stop

        subject = "We miss you at GAIA 🌱"
        html_content = generate_inactive_user_email_html(user_name)

        resend.Emails.send(
            {
                "from": f"Aryan from GAIA <{CONTACT_EMAIL}>",
                "to": [user_email],
                "subject": subject,
                "html": html_content,
                "reply_to": CONTACT_EMAIL,
            }
        )

        # Update tracking if user_id provided
        if user_id:
            await users_collection.update_one(
                {"_id": ObjectId(user_id)},
                {"$set": {"last_inactive_email_sent": datetime.now(timezone.utc)}},
            )

        logger.info(f"Inactive user email sent to {user_email}")
        return True

    except Exception as e:
        logger.error(f"Failed to send inactive user email to {user_email}: {str(e)}")
        raise


def generate_pro_subscription_html(
    user_name: str, discord_url: str, whatsapp_url: str, twitter_url: str
) -> str:
    """Generate HTML email for pro subscription welcome using the Jinja2 template."""
    try:
        template = jinja_env.get_template("subscribed.html")
        html_content = template.render(
            user_name=user_name,
            discord_url=discord_url,
            whatsapp_url=whatsapp_url,
            twitter_url=twitter_url,
        )
        return html_content
    except Exception as e:
        logger.error(f"Error generating pro subscription email HTML: {str(e)}")
        raise


def generate_inactive_user_email_html(user_name: Optional[str] = None) -> str:
    """Generate HTML email content for inactive user email using Jinja2 template."""
    try:
        template = jinja_env.get_template("inactive.html")

        # Render template with data
        html_content = template.render(
            user_name=user_name,
            contact_email=CONTACT_EMAIL,
        )

        return html_content
    except Exception as e:
        logger.error(f"Error generating inactive user email HTML: {str(e)}")
        raise
