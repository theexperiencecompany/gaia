"""
User-related ARQ tasks.
"""

from datetime import datetime, timedelta, timezone

from shared.py.wide_events import log, wide_task


async def check_inactive_users(ctx: dict) -> str:
    """
    Check for inactive users and send emails to those inactive for more than 7 days.
    Emails are sent only once after 7 days and once more after 14 days to avoid spam.

    Args:
        ctx: ARQ context

    Returns:
        Processing result message
    """
    async with wide_task("check_inactive_users"):
        from app.db.mongodb.collections import users_collection
        from app.utils.email_utils import send_inactive_user_email

        log.info("Checking for inactive users")

        now = datetime.now(timezone.utc)
        seven_days_ago = now - timedelta(days=7)

        # Convert to naive datetime for comparison with potentially naive database values
        seven_days_ago_naive = seven_days_ago.replace(tzinfo=None)

        # Find users inactive for 7+ days who haven't gotten email recently
        inactive_users = await users_collection.find(
            {
                "last_active_at": {"$lt": seven_days_ago_naive},
                "is_active": {"$ne": False},
                "$or": [
                    {"last_inactive_email_sent": {"$exists": False}},
                    {"last_inactive_email_sent": {"$lt": seven_days_ago_naive}},
                ],
            }
        ).to_list(length=None)

        log.set(inactive_users_detected=len(inactive_users))

        email_count = 0
        email_failures = 0
        for user in inactive_users:
            try:
                sent = await send_inactive_user_email(
                    user_email=user["email"],
                    user_name=user.get("name"),
                    user_id=str(user["_id"]),
                )

                if sent:
                    email_count += 1
                    log.info(f"Sent inactive email to {user['email']}")

            except Exception as e:
                email_failures += 1
                log.error(f"Failed to send email to {user['email']}: {str(e)}")

        log.set(emails_sent=email_count, email_failures=email_failures)
        message = (
            f"Processed {len(inactive_users)} inactive users, sent {email_count} emails"
        )
        log.info(message)
        return message
