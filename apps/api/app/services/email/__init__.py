"""Platform transactional email — see README.md for how to add or swap providers."""

from app.services.email.models import EmailMessage
from app.services.email.senders import (
    add_marketing_contact,
    send_inactive_user_email,
    send_pro_subscription_email,
    send_support_team_notification,
    send_support_to_user_email,
    send_welcome_email,
)
from app.services.email.service import render_email_template, send_email

__all__ = [
    "EmailMessage",
    "add_marketing_contact",
    "render_email_template",
    "send_email",
    "send_inactive_user_email",
    "send_pro_subscription_email",
    "send_support_team_notification",
    "send_support_to_user_email",
    "send_welcome_email",
]
