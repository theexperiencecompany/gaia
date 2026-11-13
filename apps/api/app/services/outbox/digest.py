"""The weekly email to a user who has been away: what the outbox kept for them instead of messaging them.

A dormant user's routine and background items wait held for the next digest slot. At the slot,
while the user is still away, those items are worded as one email and recorded as told there. A
user who cannot be emailed (unsubscribed, no address, email not set up) keeps them held for the
next slot, and their return tells them in chat as one catch-up like any other held item.
"""

from app.constants.log_tags import LogTag
from app.constants.notifications import CHANNEL_TYPE_EMAIL
from app.constants.websocket import ReportSettledOutcome
from app.db.repositories.outbox_items import outbox_items_repository
from app.models.outbox_models import OutboxItemDocument
from app.models.user_models import AuthenticatedUser
from app.services.analytics_service import capture
from app.services.email import email_delivery_configured, send_outbox_digest_email
from app.services.outbox.compose import compose_digest
from app.services.outbox.deliver import OutboxUserNotFoundError, locale_of
from app.services.outbox.flush_queue import schedule_flush
from app.services.outbox.holds import next_digest
from app.services.outbox.judge_context import user_clock
from app.services.outbox.metrics import OUTBOX_ITEMS_DROPPED
from app.services.outbox.models import DropReason, ItemHold
from app.services.outbox.prerendered import PrerenderedKind, prerendered_text
from app.services.outbox.settled import announce_items_settled
from app.utils import clock
from app.utils.auth_utils import load_user_context
from app.utils.channel_preferences import normalize_channel_preferences
from shared.py.analytics import Dedupe, UserId
from shared.py.analytics.catalog.delivery import DeliveryDigestSent
from shared.py.wide_events import log


async def _can_email(user: AuthenticatedUser) -> bool:
    """Whether the user has not turned email off and email delivery is set up."""
    if not normalize_channel_preferences(user.notification_channel_prefs)[CHANNEL_TYPE_EMAIL]:
        return False
    return await email_delivery_configured()


async def _hold_for_next_slot(user: AuthenticatedUser, items: list[OutboxItemDocument]) -> None:
    """Keep the items waiting for the user's return, and look at them again at the next digest slot."""
    now = clock.now()
    until = next_digest(user.user_id, user_clock(user), now)
    for item in items:
        if item.hold is None or item.urgency is None or item.mode is None:
            raise ValueError(f"outbox item {item.report_id} is not held for a digest")
        await outbox_items_repository.hold(
            user.user_id,
            item.report_id,
            ItemHold(
                reason=item.hold.reason,
                until=until,
                since=item.hold.since,
                deferrals=item.hold.deferrals,
            ),
            urgency=item.urgency,
            mode=item.mode,
        )
    await schedule_flush(user.user_id, until)
    log.info(
        f"{LogTag.NOTIFICATION} Dormant user cannot be emailed; their items keep waiting for them",
        user_id=user.user_id,
        items=len(items),
        next_slot=until.isoformat(),
    )


async def _record_digested(
    user: AuthenticatedUser,
    items: list[OutboxItemDocument],
    included: list[str],
    skipped: list[str],
) -> None:
    """Record the items the email told, and the ones it left out as not worth telling."""
    reasons = {
        **dict.fromkeys(included, DropReason.DIGESTED),
        **dict.fromkeys(skipped, DropReason.COMPOSE_SKIPPED),
    }
    for item in items:
        reason = reasons.get(item.report_id)
        if reason is None:
            continue
        if await outbox_items_repository.drop(user.user_id, item.report_id, reason) is not None:
            OUTBOX_ITEMS_DROPPED.labels(reason=reason.value).inc()
    await announce_items_settled(
        [item for item in items if item.report_id in reasons], ReportSettledOutcome.RECORDED
    )


async def _email_digest(
    user: AuthenticatedUser, address: str, items: list[OutboxItemDocument]
) -> None:
    locale = locale_of(user)
    composed = await compose_digest(items, user_id=user.user_id, locale=locale)
    first_report_id = items[0].report_id
    if composed.included:
        await send_outbox_digest_email(
            address,
            user.user_id,
            prerendered_text(PrerenderedKind.DIGEST_SUBJECT, locale),
            composed.parts,
            idempotency_key=f"outbox-digest:{first_report_id}",
        )
        capture(
            UserId(user.user_id),
            DeliveryDigestSent(items_count=len(composed.included)),
            Dedupe(key=f"digest:{first_report_id}", occurred_at=clock.now()),
        )
    await _record_digested(user, items, composed.included, composed.skipped)


async def settle_dormant(user_id: str, items: list[OutboxItemDocument]) -> None:
    """Email a dormant user the items held for them, or keep holding them when they cannot be emailed.

    Raises OutboxUserNotFoundError when user_id is no user, and whatever sending the email raises,
    which leaves the items held for the job's retry.
    """
    user = await load_user_context(user_id)
    if user is None:
        raise OutboxUserNotFoundError(user_id)
    if user.email and await _can_email(user):
        await _email_digest(user, user.email, items)
    else:
        await _hold_for_next_slot(user, items)
