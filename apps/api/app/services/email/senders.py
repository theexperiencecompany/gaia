"""Domain senders for every platform email GAIA delivers."""

from datetime import UTC, datetime, timedelta

from app.config.rate_limits import derive_pro_benefits, get_feature_info
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
from app.db.repositories.users import user_repository
from app.models.support_models import SupportEmailNotification, SupportRequestType
from app.models.user_models import UserDocument
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
                log.info(f"{LogTag.MAIL} Support notification sent to", support_email=support_email)
            except Exception as e:
                log.error(
                    f"{LogTag.MAIL} Failed to send support email to",
                    support_email=support_email,
                    error=str(e),
                    error_type=type(e).__name__,
                )
    except Exception as e:
        log.error(
            f"{LogTag.MAIL} Error sending support team notifications",
            error=str(e),
            error_type=type(e).__name__,
        )
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
        log.info(
            f"{LogTag.MAIL} Confirmation email sent to user",
            user_email=notification_data.user_email,
        )
    except Exception as e:
        log.error(
            f"{LogTag.MAIL} Failed to send confirmation email to user",
            error=str(e),
            error_type=type(e).__name__,
        )
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
        log.info(f"{LogTag.MAIL} Pro subscription welcome email sent to", user_email=user_email)
    except Exception as e:
        log.error(
            f"{LogTag.MAIL} Failed to send pro subscription email to",
            user_email=user_email,
            error=str(e),
            error_type=type(e).__name__,
        )
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
        log.info(f"{LogTag.MAIL} Welcome email sent to", user_email=user_email)
    except Exception as e:
        log.error(
            f"{LogTag.MAIL} Failed to send welcome email to",
            user_email=user_email,
            error=str(e),
            error_type=type(e).__name__,
        )
        raise


async def add_marketing_contact(user_email: str, user_name: str | None = None) -> None:
    """Add a new user to the marketing audience, if the provider supports one.

    Best-effort: never raises, so signup succeeds even when the provider call fails.
    """
    try:
        provider = get_email_provider()
        if not isinstance(provider, MarketingContactsProvider):
            log.info(
                f"{LogTag.MAIL} Email provider has no marketing audience; skipping contact",
                user_email=user_email,
            )
            return
        await provider.add_contact(user_email, user_name)
        log.info(f"{LogTag.MAIL} Contact added to marketing audience", user_email=user_email)
    except Exception as e:
        log.error(
            f"{LogTag.MAIL} Failed to add marketing contact for",
            user_email=user_email,
            error=str(e),
            error_type=type(e).__name__,
        )


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
        log.info(f"{LogTag.MAIL} Inactive user email sent to", user_email=user_email)
    except Exception as e:
        log.error(
            f"{LogTag.MAIL} Failed to send inactive user email to",
            user_email=user_email,
            error=str(e),
            error_type=type(e).__name__,
        )
        raise


async def send_badge_earned_email(
    user_email: str,
    user_name: str | None,
    tier: str,
    top_label: str,
) -> None:
    """Congratulate a user the first time they reach an activity badge tier.

    Send-once semantics live with the caller (``sync_activity_tiers`` promotes
    monotonically), so this stays a dumb sender like the rest of this module.
    """
    html_content = render_email_template(
        "badge_earned.html",
        user_name=user_name,
        tier_name=tier.capitalize(),
        top_label=top_label,
        usage_url=f"{settings.FRONTEND_URL}/settings/usage",
        contact_email=CONTACT_EMAIL,
    )

    await send_email(
        EmailMessage(
            sender=FOUNDER_SENDER,
            to=[user_email],
            subject=f"You're in the top {top_label} of GAIA users",
            html=html_content,
            reply_to=CONTACT_EMAIL,
        )
    )
    log.info(f"{LogTag.MAIL} Badge earned email sent", tier=tier)


#: One limit email of any kind per user per week, shared by both senders.
LIMIT_EMAIL_WINDOW = timedelta(days=7)


async def _limit_email_recipient(user_id: str) -> UserDocument | None:
    """The user a limit email may go to, or None (missing/no email/weekly dedupe).

    Both limit emails — the interactive upsell and the background
    workflows-paused note — share this one weekly window via
    ``last_limit_email_sent``, so a user never gets more than one limit email
    of any kind in a 7-day span.
    """
    user = await user_repository.get(user_id)
    if user is None or not user.email:
        log.warning(
            f"{LogTag.MAIL} Limit email skipped — user not found or no email",
            user={"id": user_id},
        )
        return None

    # One nudge per week: a daily 429 toast is expected UX; a daily email is spam.
    # The window is CLAIMED, not merely read: both senders share it, and reading
    # eligibility here then stamping it after the send let two concurrent hits
    # both pass and both send. The claim is a conditional update, so exactly one
    # caller wins; the loser returns None and sends nothing.
    claimed = await user_repository.claim_limit_email_slot(
        user_id, stale_before=datetime.now(UTC) - LIMIT_EMAIL_WINDOW
    )
    if claimed is None:
        return None
    return user


async def send_limit_reached_email(
    user_id: str,
    hit_feature: str,
) -> bool:
    """Upsell email when a FREE user hits a usage wall, deduped to 1/week.

    The benefits list is derived live from FEATURE_LIMITS — the same config
    that enforces the limits — so the email can never promise something the
    plan doesn't deliver. Returns True if sent, False if skipped (dedupe or
    missing user/email).
    """
    user = await _limit_email_recipient(user_id)
    if user is None:
        return False

    feature_title = get_feature_info(hit_feature).title
    html_content = render_email_template(
        "limit_reached.html",
        user_name=user.name,
        hit_feature_title=feature_title,
        benefits=derive_pro_benefits(hit_feature),
        pricing_url=f"{settings.FRONTEND_URL}/pricing",
        contact_email=CONTACT_EMAIL,
    )

    try:
        await send_email(
            EmailMessage(
                sender=FOUNDER_SENDER,
                to=[user.email],
                subject="You hit your GAIA limit today — here's what Pro unlocks",
                html=html_content,
                reply_to=CONTACT_EMAIL,
            )
        )
    except Exception:
        # The slot was claimed before sending; hand it back so a failed
        # send does not silence this user for the rest of the week.
        await user_repository.release_limit_email_slot(user_id, user.last_limit_email_sent)
        raise
    log.info(f"{LogTag.MAIL} Limit-reached upsell email sent", user={"id": user_id})
    return True


async def send_workflows_paused_email(user_id: str) -> bool:
    """Tell a FREE user their background workflows are taking a break today.

    Sent when a workflow run — not a user action — hits the daily usage wall,
    so the copy explains what happened to the work GAIA does for them in the
    background instead of claiming they personally hit a limit. Shares the
    weekly dedupe window with the interactive upsell email. Returns True if
    sent, False if skipped (dedupe or missing user/email).
    """
    user = await _limit_email_recipient(user_id)
    if user is None:
        return False

    html_content = render_email_template(
        "workflows_paused.html",
        user_name=user.name,
        workflows_url=f"{settings.FRONTEND_URL}/workflows",
        pricing_url=f"{settings.FRONTEND_URL}/pricing",
        contact_email=CONTACT_EMAIL,
    )

    try:
        await send_email(
            EmailMessage(
                sender=FOUNDER_SENDER,
                to=[user.email],
                subject="GAIA is taking a break until tomorrow",
                html=html_content,
                reply_to=CONTACT_EMAIL,
            )
        )
    except Exception:
        # The slot was claimed before sending; hand it back so a failed
        # send does not silence this user for the rest of the week.
        await user_repository.release_limit_email_slot(user_id, user.last_limit_email_sent)
        raise
    log.info(f"{LogTag.MAIL} Workflows-paused email sent", user={"id": user_id})
    return True
