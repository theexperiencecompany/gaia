"""Signup's outbound ESP deliveries, as a durable ARQ job plus its recovery sweep.

The welcome email and the marketing-audience contact are HTTP round-trips to an
external provider, so signup must not wait on them. Running them as an
in-process fire-and-forget task made signup fast but left the delivery with no
owner: nothing drains those tasks on shutdown, so an API restart mid-send
dropped both effects without even reaching their own failure loggers — the user
silently never got the founder email and never entered the nurture sequence.

Queued in Redis instead, the job outlives the process that enqueued it: ARQ only
removes a job from the queue once it finishes, so a worker that dies mid-send
leaves the job to be picked up and re-run.

That made the *job* durable but not the *intent*, which is what the other two
pieces here are for. Each landed delivery stamps the user (``SignupDelivery``),
so a re-run after a mid-send death resumes instead of mailing the same person
twice, and the enqueue carries a per-user job id so two enqueues collapse into
one job. A signup whose enqueue never reached Redis at all leaves both stamps
missing, and ``sweep_undelivered_signup_emails`` finishes it later — before
that, a single Redis hiccup lost both deliveries forever with no record
anywhere that they were owed.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from datetime import UTC, datetime, timedelta
from typing import Any

from app.constants.email import (
    SIGNUP_EMAIL_SWEEP_LOOKBACK_DAYS,
    SIGNUP_EMAIL_SWEEP_MAX_USERS_PER_RUN,
    WELCOME_EMAIL_RESEND_WINDOW,
    SignupDelivery,
)
from app.constants.log_tags import LogTag
from app.db.repositories.users import user_repository
from app.services.email import add_marketing_contact, send_welcome_email
from app.services.email.signup_delivery import enqueue_signup_emails
from app.utils.redis_utils import RedisPoolManager
from shared.py.wide_events import UserContext, log

# Bounds each ESP round-trip on its own. Without it a provider that accepts the
# connection and never answers holds a worker slot for the job's whole timeout
# (30 minutes) and the other delivery is never reported either.
SIGNUP_EMAIL_TIMEOUT_SECONDS = 10


async def _send_welcome(user_id: str, email: str, signup_name: str | None) -> None:
    """Deliver the welcome email and stamp it; a failure is recorded, never raised."""
    try:
        async with asyncio.timeout(SIGNUP_EMAIL_TIMEOUT_SECONDS):
            await send_welcome_email(email, signup_name, user_id=user_id)
        await user_repository.stamp_signup_deliveries(user_id, [SignupDelivery.WELCOME_EMAIL])
        log.info(f"{LogTag.OAUTH} Welcome email sent to new user", user={"id": user_id})
    except Exception as e:
        log.error(
            f"{LogTag.OAUTH} Failed to send welcome email to",
            user={"id": user_id},
            error=str(e),
            error_type=type(e).__name__,
        )


async def _add_contact(user_id: str, email: str, signup_name: str | None) -> None:
    """Add the signup to the marketing audience and stamp it; a failure is recorded, never raised."""
    try:
        async with asyncio.timeout(SIGNUP_EMAIL_TIMEOUT_SECONDS):
            await add_marketing_contact(email, signup_name, user_id=user_id)
        await user_repository.stamp_signup_deliveries(user_id, [SignupDelivery.MARKETING_CONTACT])
        log.info(
            f"{LogTag.OAUTH} Contact added to marketing audience for new user",
            user={"id": user_id},
        )
    except Exception as e:
        log.error(
            f"{LogTag.OAUTH} Failed to add marketing contact for",
            user={"id": user_id},
            error=str(e),
            error_type=type(e).__name__,
        )


async def deliver_signup_emails(_ctx: dict[str, Any], user_id: str) -> str:
    """Run whichever signup deliveries this user is still owed, concurrently.

    Only the user id is queued: the stored row is the one source of the address
    and name, so a sweep re-enqueue cannot disagree with signup about either,
    and reading it is also what makes the job resumable — an already-stamped
    delivery is skipped rather than sent again.

    Both failure paths are swallowed on purpose: the account already exists, so
    there is nothing to roll back, and raising here would only make ARQ retry a
    welcome email the provider may well have already sent. The missing stamp is
    what hands the delivery to the sweep, and the wide event is where a lost one
    is diagnosed.
    """
    log.set(user=UserContext(id=user_id))
    user = await user_repository.get(user_id)
    if user is None or not user.email:
        log.set(skipped=True)
        return f"skip {user_id}: no user row or no email to deliver to"

    deliveries: list[Coroutine[Any, Any, None]] = []
    if user.welcome_email_sent_at is None:
        if (
            user.created_at is None
            or datetime.now(UTC) - user.created_at > WELCOME_EMAIL_RESEND_WINDOW
        ):
            log.set(welcome_email_abandoned=True)
        else:
            deliveries.append(_send_welcome(user_id, user.email, user.name))
    if user.marketing_contact_added_at is None:
        deliveries.append(_add_contact(user_id, user.email, user.name))
    if not deliveries:
        log.set(skipped=True)
        return f"skip {user_id}: both signup deliveries already landed"

    await asyncio.gather(*deliveries, return_exceptions=True)
    return f"Signup deliveries attempted for {user_id}"


async def sweep_undelivered_signup_emails(_ctx: dict[str, Any]) -> str:
    """Re-enqueue the signup deliveries of anyone whose stamps are still missing.

    The safety net for the enqueue itself: a Redis hiccup during signup loses
    the job with nothing left behind but the user's un-stamped row, and this is
    what reads that row. Idempotent twice over — the per-user job id dedups
    against a job already queued, and the job skips whatever already landed.
    """
    created_since = datetime.now(UTC) - timedelta(days=SIGNUP_EMAIL_SWEEP_LOOKBACK_DAYS)
    candidate_ids = await user_repository.find_undelivered_signup_ids(
        created_since, limit=SIGNUP_EMAIL_SWEEP_MAX_USERS_PER_RUN
    )

    pool = await RedisPoolManager.get_pool()
    enqueued = 0
    for user_id in candidate_ids:
        if await enqueue_signup_emails(pool, user_id) is not None:
            enqueued += 1

    log.set(signup_delivery_candidates=len(candidate_ids), enqueued=enqueued)
    return (
        f"sweep_undelivered_signup_emails enqueued {enqueued} "
        f"of {len(candidate_ids)} undelivered signup(s)"
    )
