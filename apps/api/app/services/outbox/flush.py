"""Flush: tell what was held once its hold has ended.

A flush re-judges each due item with fresh context (the deal ended, the user did it themselves),
places it again as released, and tells what is still to be told, one message per subject. It is
driven three ways: a deferred job scheduled when the item was held, the user's return, and a
sweep for a user whose job was lost. Which of them runs first does not matter: the claim on each
item is a compare-and-set, so an item is told once.
"""

from datetime import timedelta

from app.constants.log_tags import LogTag
from app.constants.outbox_attention import (
    FLUSH_COMPOSE_CONCURRENCY_KEY,
    FLUSH_MAX_CONCURRENT_COMPOSES,
    FLUSH_SWEEP_INTERVAL_MINUTES,
    HELD_AGE_ALERT_SECONDS,
    RETURN_FLUSH_DELAY_SECONDS,
    HoldReason,
)
from app.db.repositories.outbox_items import outbox_items_repository
from app.services.outbox.deliver import flush_items
from app.services.outbox.flush_queue import schedule_flush
from app.services.outbox.intake import settle_report
from app.services.outbox.models import ItemState
from app.utils import clock
from app.utils.concurrency import loop_bound_semaphore
from shared.py.wide_events import log

#: What a user's return answers: items waiting for a check-in or for the gap since the last message.
_RELEASED_BY_RETURN = (HoldReason.CHECKIN, HoldReason.GAP)


async def flush_due(user_id: str) -> int:
    """Settle the user's held items whose hold has ended and tell what is to be told as one message; return how many were told."""
    due = await outbox_items_repository.list_due_held(user_id, clock.now())
    if not due:
        log.info(f"{LogTag.NOTIFICATION} Outbox flush found nothing due", user_id=user_id)
        return 0
    released: list[str] = []
    for item in due:
        state = await settle_report(item.report, prior_hold=item.hold, released=True)
        if state is ItemState.QUEUED:
            released.append(item.report_id)
    if released:
        async with loop_bound_semaphore(
            FLUSH_COMPOSE_CONCURRENCY_KEY, FLUSH_MAX_CONCURRENT_COMPOSES
        ):
            await flush_items(user_id, released)
    return len(released)


async def release_on_return(user_id: str) -> None:
    """End the holds a user's return answers and flush them just after, so the reply goes first."""
    now = clock.now()
    if await outbox_items_repository.release_held(user_id, _RELEASED_BY_RETURN, now):
        await schedule_flush(user_id, now + timedelta(seconds=RETURN_FLUSH_DELAY_SECONDS))


async def sweep_lost_flushes() -> int:
    """Flush every user whose held items are overdue past the sweep interval, a lost job's leavings; return how many users."""
    now = clock.now()
    overdue = await outbox_items_repository.users_with_due_held(
        now - timedelta(minutes=FLUSH_SWEEP_INTERVAL_MINUTES)
    )
    for user_id in overdue:
        log.error(
            f"{LogTag.NOTIFICATION} Outbox flush job was lost; the sweep flushes", user_id=user_id
        )
        await schedule_flush(user_id, now)
    stale = await outbox_items_repository.count_held_since_before(
        now - timedelta(seconds=HELD_AGE_ALERT_SECONDS)
    )
    if stale:
        log.error(f"{LogTag.NOTIFICATION} Outbox items held past the age alert", items=stale)
    return len(overdue)
