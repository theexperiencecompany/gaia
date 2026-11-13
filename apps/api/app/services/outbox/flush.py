"""Flush: tell what was held once its hold has ended.

A flush re-judges each due item with fresh context (the deal ended, the user did it themselves),
places it again as released, and tells what is still to be told, one message per subject. It is
driven three ways: a deferred job scheduled when the item was held, the user's return, and a
sweep for a user whose job was lost. The sweep also drives every other unsent item a dead job
left behind, a bounded number of times, then fails it loudly. Which of them runs first does not
matter: the claim on each item is a compare-and-set, so an item is told once.
"""

from datetime import timedelta

from app.constants.log_tags import LogTag
from app.constants.outbox import (
    OUTBOX_INTAKE_TASK,
    OUTBOX_JOB_ID_PREFIX,
    OUTBOX_RECOVERY_AFTER_SECONDS,
    OUTBOX_RECOVERY_BATCH,
    OUTBOX_RECOVERY_JOB_ID_SUFFIX,
    OUTBOX_RECOVERY_MAX_ATTEMPTS,
)
from app.constants.outbox_attention import (
    CALL_END_FLUSH_DELAY_SECONDS,
    FLUSH_COMPOSE_CONCURRENCY_KEY,
    FLUSH_CONTINUATION_DELAY_SECONDS,
    FLUSH_MAX_CONCURRENT_COMPOSES,
    FLUSH_MAX_ITEMS_PER_RUN,
    FLUSH_SWEEP_INTERVAL_MINUTES,
    HELD_AGE_ALERT_SECONDS,
    RETURN_FLUSH_DELAY_SECONDS,
    HoldReason,
)
from app.constants.websocket import ReportSettledOutcome
from app.db.repositories.outbox_items import outbox_items_repository
from app.models.outbox_models import OutboxItemDocument
from app.services.delivery.presence import read_last_active
from app.services.outbox.deliver import flush_items
from app.services.outbox.digest import settle_dormant
from app.services.outbox.dormancy import is_dormant
from app.services.outbox.flush_queue import release_and_flush, schedule_flush
from app.services.outbox.intake import settle_report
from app.services.outbox.metrics import OUTBOX_ITEMS_FAILED, OUTBOX_ITEMS_RECOVERED
from app.services.outbox.models import ItemFailure, ItemState
from app.services.outbox.settled import announce_settled
from app.utils import clock
from app.utils.concurrency import loop_bound_semaphore
from app.utils.redis_utils import RedisPoolManager
from app.workers.queue import enqueue_worker_job
from shared.py.wide_events import log

#: What a user's return answers: items waiting for a check-in, the gap since the last message, or silence.
_RELEASED_BY_RETURN = (
    HoldReason.CHECKIN,
    HoldReason.GAP,
    HoldReason.DND,
    HoldReason.QUIET_HOURS,
    HoldReason.DORMANT,
)


def _held_for_call(item: OutboxItemDocument) -> bool:
    """Whether the item waited for a call to end, which is no hold of its own kind: it is placed as new."""
    return item.hold is not None and item.hold.reason is HoldReason.IN_CALL


def _held_for_dormancy(item: OutboxItemDocument) -> bool:
    """Whether the item waits for a dormant user's return or the weekly digest."""
    return item.hold is not None and item.hold.reason is HoldReason.DORMANT


async def _settle_dormant_holds(
    user_id: str, due: list[OutboxItemDocument]
) -> list[OutboxItemDocument]:
    """Email what a user who is still away missed; return the due items that remain to be flushed.

    A user who has come back since is told them in chat as every held item is: those stay in due.
    """
    waiting = [item for item in due if _held_for_dormancy(item)]
    if not waiting:
        return due
    if not await is_dormant(user_id, await read_last_active(user_id), clock.now()):
        return due
    await settle_dormant(user_id, waiting)
    return [item for item in due if item not in waiting]


async def flush_due(user_id: str) -> int:
    """Settle the user's held items whose hold has ended and tell what is to be told as one message; return how many were told.

    At most FLUSH_MAX_ITEMS_PER_RUN held items are re-judged per run, the rest by a follow-up job.
    An item whose re-judging fails stays held for the sweep, and never keeps the others from
    being told; the failures are raised once the rest has been told.
    """
    now = clock.now()
    due = await outbox_items_repository.list_due_held(
        user_id, now, limit=FLUSH_MAX_ITEMS_PER_RUN + 1
    )
    more_due = len(due) > FLUSH_MAX_ITEMS_PER_RUN
    due = await _settle_dormant_holds(user_id, due)
    stranded = await outbox_items_repository.list_stranded_queued(user_id)
    if not due and not stranded and not more_due:
        log.info(f"{LogTag.NOTIFICATION} Outbox flush found nothing due", user_id=user_id)
        return 0
    if more_due:
        await schedule_flush(user_id, now + timedelta(seconds=FLUSH_CONTINUATION_DELAY_SECONDS))
    released = [item.report_id for item in stranded]
    failures: list[Exception] = []
    for item in due[:FLUSH_MAX_ITEMS_PER_RUN]:
        try:
            state = await settle_report(
                item.report, prior_hold=item.hold, released=not _held_for_call(item)
            )
        except Exception as error:
            log.error(
                f"{LogTag.NOTIFICATION} Outbox flush could not settle a held item",
                user_id=user_id,
                report_id=item.report_id,
                error=str(error),
                error_type=type(error).__name__,
            )
            failures.append(error)
            counted = await outbox_items_repository.count_failed_settle(
                item.user_id,
                item.report_id,
                now,
                now - timedelta(seconds=OUTBOX_RECOVERY_AFTER_SECONDS),
            )
            if counted is not None and counted.recovery_attempts > OUTBOX_RECOVERY_MAX_ATTEMPTS:
                await _fail_exhausted(counted)
            continue
        if state is ItemState.QUEUED:
            released.append(item.report_id)
    if released:
        async with loop_bound_semaphore(
            FLUSH_COMPOSE_CONCURRENCY_KEY, FLUSH_MAX_CONCURRENT_COMPOSES
        ):
            await flush_items(user_id, released)
    if failures:
        raise ExceptionGroup("outbox flush could not settle every held item", failures)
    return len(released)


async def release_on_return(user_id: str) -> None:
    """End the holds a user's return answers and flush them just after, so the reply goes first."""
    await release_and_flush(
        user_id, _RELEASED_BY_RETURN, delay=timedelta(seconds=RETURN_FLUSH_DELAY_SECONDS)
    )


async def release_on_call_end(user_id: str) -> None:
    """End the holds a live call put on the user's items, and a dormant user's, and flush them once it has closed.

    A call is a sign of presence like any message: a user who was away and called is back.
    """
    await release_and_flush(
        user_id,
        (HoldReason.IN_CALL, HoldReason.DORMANT),
        delay=timedelta(seconds=CALL_END_FLUSH_DELAY_SECONDS),
    )


async def _fail_exhausted(item: OutboxItemDocument) -> None:
    """Fail an unsent item that used up its attempts, loudly; nothing when it was settled meanwhile."""
    if await outbox_items_repository.fail_exhausted(item.user_id, item.report_id) is None:
        return
    OUTBOX_ITEMS_FAILED.labels(reason=ItemFailure.RECOVERY_EXHAUSTED.value).inc()
    await announce_settled(item.report, ReportSettledOutcome.FAILED)
    log.error(
        f"{LogTag.NOTIFICATION} Outbox item never left the queue; gave up on it",
        user_id=item.user_id,
        report_id=item.report_id,
        item_state=item.state.value,
        recovery_attempts=item.recovery_attempts,
    )


async def _recover(item: OutboxItemDocument) -> None:
    """Drive one stranded unsent item again, or fail it when it has used up its attempts."""
    if item.recovery_attempts > OUTBOX_RECOVERY_MAX_ATTEMPTS:
        await _fail_exhausted(item)
        return
    OUTBOX_ITEMS_RECOVERED.labels(state=item.state.value).inc()
    log.error(
        f"{LogTag.NOTIFICATION} Outbox item stranded; the sweep drives it again",
        user_id=item.user_id,
        report_id=item.report_id,
        item_state=item.state.value,
        recovery_attempts=item.recovery_attempts,
    )
    if item.state is ItemState.RECEIVED:
        pool = await RedisPoolManager.get_pool()
        await enqueue_worker_job(
            pool,
            OUTBOX_INTAKE_TASK,
            item.report.model_dump(mode="json"),
            False,
            _job_id=(
                f"{OUTBOX_JOB_ID_PREFIX}{item.report_id}"
                f"{OUTBOX_RECOVERY_JOB_ID_SUFFIX}{item.recovery_attempts}"
            ),
        )
        return
    if item.state is ItemState.COMPOSING:
        await outbox_items_repository.requeue_composing(item.user_id, item.report_id)
    await schedule_flush(item.user_id, clock.now())


async def sweep_lost_flushes() -> int:
    """Drive what a lost job left unsent: due holds, and received, queued or composing items gone stale; return how many users got a flush.

    An item driven OUTBOX_RECOVERY_MAX_ATTEMPTS times and still stranded is failed, loudly.
    """
    now = clock.now()
    overdue = await outbox_items_repository.users_with_due_held(
        now - timedelta(minutes=FLUSH_SWEEP_INTERVAL_MINUTES)
    )
    for user_id in overdue:
        log.error(
            f"{LogTag.NOTIFICATION} Outbox flush job was lost; the sweep flushes", user_id=user_id
        )
        await schedule_flush(user_id, now)
    for item in await outbox_items_repository.claim_recovery(
        now,
        now - timedelta(seconds=OUTBOX_RECOVERY_AFTER_SECONDS),
        limit=OUTBOX_RECOVERY_BATCH,
    ):
        await _recover(item)
    stale = await outbox_items_repository.count_overdue_held_since_before(
        now, now - timedelta(seconds=HELD_AGE_ALERT_SECONDS)
    )
    if stale:
        log.error(f"{LogTag.NOTIFICATION} Outbox items held past the age alert", items=stale)
    return len(overdue)
