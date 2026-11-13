"""Intake: how a report enters the outbox, and what happens to it before anyone is told.

submit is durable: it enqueues an ARQ job keyed by the report id and raises when the
enqueue fails, so a producer never believes a report it lost. The job body is
process_report: insert the item once (a second submit of the same report finds it),
let the latest report of a replace subject stand, have the Judge read what it means for
the user (unless the Rails decide it without one), apply the policy, and send what is to
be told. The verdict is kept on the item either way. A report that waits for its user's
other reports is handed back to the queue deferred by the batch window, so no worker sleeps.
"""

from datetime import timedelta

from app.constants.log_tags import LogTag
from app.constants.outbox import (
    OUTBOX_BATCHED_JOB_ID_SUFFIX,
    OUTBOX_INTAKE_TASK,
    OUTBOX_ITEM_RETENTION_SECONDS,
    OUTBOX_JOB_ID_PREFIX,
)
from app.constants.outbox_attention import HoldReason
from app.constants.outbox_judge import (
    JUDGE_BATCH_WINDOW_SECONDS,
    JUDGE_INTERRUPT_CAP_WINDOW_SECONDS,
)
from app.db.repositories.outbox_items import outbox_items_repository
from app.services.analytics_service import capture
from app.services.outbox.attention import place_item
from app.services.outbox.deliver import flush_subject
from app.services.outbox.flush_queue import schedule_flush
from app.services.outbox.holds import Hold, Placement, Record, Tell
from app.services.outbox.judge import judge_report
from app.services.outbox.judge_models import ItemJudgement
from app.services.outbox.metrics import (
    OUTBOX_ITEMS_DROPPED,
    OUTBOX_ITEMS_HELD,
    OUTBOX_JUDGE_INTERRUPT_CAPPED,
)
from app.services.outbox.models import ItemHold, ItemState, OutboxReport, SubjectMerge
from app.services.outbox.policy import (
    Decision,
    DecisionKind,
    decide,
    is_judge_free,
    is_progress,
    waits_for_batch,
)
from app.services.outbox.watching import is_watched_live
from app.utils import clock
from app.utils.redis_utils import RedisPoolManager
from app.workers.queue import enqueue_worker_job
from shared.py.analytics import Dedupe, UserId
from shared.py.analytics.catalog.delivery import DeliveryItemHeld
from shared.py.wide_events import log


async def submit(report: OutboxReport) -> None:
    """Hand a report to the outbox: durable once this returns, and raises when it cannot be."""
    await _enqueue(report, batched=False)


async def _enqueue(report: OutboxReport, *, batched: bool) -> None:
    pool = await RedisPoolManager.get_pool()
    suffix = OUTBOX_BATCHED_JOB_ID_SUFFIX if batched else ""
    await enqueue_worker_job(
        pool,
        OUTBOX_INTAKE_TASK,
        report.model_dump(mode="json"),
        batched,
        _job_id=f"{OUTBOX_JOB_ID_PREFIX}{report.report_id}{suffix}",
        _defer_by=JUDGE_BATCH_WINDOW_SECONDS if batched else None,
    )


async def _judge_and_decide(
    report: OutboxReport, *, watched_live: bool
) -> tuple[Decision, ItemJudgement | None]:
    """Have the Judge read the report unless the policy needs no one to, and decide with the Rails."""
    if is_judge_free(report, watched_live=watched_live):
        return decide(report, None, watched_live=watched_live), None
    verdict = await judge_report(report)
    raised = await outbox_items_repository.count_raised_interrupts_since(
        report.recipient, clock.now() - timedelta(seconds=JUDGE_INTERRUPT_CAP_WINDOW_SECONDS)
    )
    decision = decide(report, verdict, watched_live=watched_live, interrupts_raised_today=raised)
    if decision.interrupt_capped:
        OUTBOX_JUDGE_INTERRUPT_CAPPED.inc()
        log.error(
            f"{LogTag.NOTIFICATION} Judge asked for more interrupts than the daily cap allows",
            report_id=report.report_id,
        )
    return decision, ItemJudgement(
        verdict=verdict,
        judge_unavailable=verdict is None,
        raised_interrupt=decision.raised_interrupt,
        sensitivity=decision.sensitivity,
    )


async def settle_report(
    report: OutboxReport,
    *,
    prior_hold: ItemHold | None = None,
    released: bool = False,
) -> ItemState | None:
    """Judge a report, decide and place it; return the state it was left in, None when another worker settled it first.

    QUEUED means it is to be told now, HELD that it waits for an instant (a flush is scheduled),
    DROPPED that it is recorded and never alerted. released says it already waited out a hold.
    """
    watched_live = is_progress(report) and await is_watched_live(report)
    decision, judgement = await _judge_and_decide(report, watched_live=watched_live)
    verdict = judgement.verdict if judgement is not None else None
    drop_reason = decision.drop_reason if decision.kind is DecisionKind.RECORD_ONLY else None
    placement: Placement = Tell()
    if drop_reason is None:
        placement = await place_item(
            report, decision.urgency, verdict, prior_hold=prior_hold, released=released
        )
        if isinstance(placement, Record):
            drop_reason = placement.reason
    if drop_reason is not None:
        dropped = await outbox_items_repository.drop(
            report.recipient, report.report_id, drop_reason, judgement=judgement
        )
        if dropped is None:
            return None
        OUTBOX_ITEMS_DROPPED.labels(reason=drop_reason.value).inc()
        log.info(
            f"{LogTag.NOTIFICATION} Outbox report recorded, not alerted",
            drop_reason=drop_reason.value,
        )
        return ItemState.DROPPED
    if isinstance(placement, Hold):
        return await _hold(report, decision, judgement, placement, prior_hold)
    queued = await outbox_items_repository.queue(
        report.recipient,
        report.report_id,
        urgency=decision.urgency,
        mode=decision.mode,
        judgement=judgement,
    )
    return ItemState.QUEUED if queued is not None else None


async def _hold(
    report: OutboxReport,
    decision: Decision,
    judgement: ItemJudgement | None,
    placement: Hold,
    prior_hold: ItemHold | None,
) -> ItemState | None:
    now = clock.now()
    deferrals = prior_hold.deferrals if prior_hold is not None else 0
    hold = ItemHold(
        reason=placement.reason,
        until=placement.until,
        since=prior_hold.since if prior_hold is not None else now,
        deferrals=deferrals + (1 if placement.reason is HoldReason.WAIT_FOR_RUN else 0),
    )
    held = await outbox_items_repository.hold(
        report.recipient,
        report.report_id,
        hold,
        urgency=decision.urgency,
        mode=decision.mode,
        judgement=judgement,
    )
    if held is None:
        return None
    await schedule_flush(report.recipient, placement.until)
    OUTBOX_ITEMS_HELD.labels(reason=placement.reason.value).inc()
    capture(
        UserId(report.recipient),
        DeliveryItemHeld(reason=placement.reason.value, max_class=decision.urgency.name.lower()),
        Dedupe(key=f"{report.report_id}:{int(placement.until.timestamp())}", occurred_at=now),
    )
    log.info(
        f"{LogTag.NOTIFICATION} Outbox report held",
        hold_reason=placement.reason.value,
        hold_until=placement.until.isoformat(),
    )
    return ItemState.HELD


async def _queue_if_to_be_told(report: OutboxReport, *, batched: bool) -> bool:
    """Run a received report through supersede, the Judge and the policy; True when it is queued to be told.

    False also when it was handed back to the queue to wait for its user's other reports,
    and when it was held or recorded.
    """
    if (
        report.subject.merge is SubjectMerge.REPLACE
        and not await outbox_items_repository.apply_replace(report)
    ):
        log.info(f"{LogTag.NOTIFICATION} Outbox report superseded by a newer one")
        return False
    watched_live = is_progress(report) and await is_watched_live(report)
    if (
        not batched
        and waits_for_batch(report)
        and not is_judge_free(report, watched_live=watched_live)
    ):
        await _enqueue(report, batched=True)
        return False
    return await settle_report(report) is ItemState.QUEUED


async def process_report(report: OutboxReport, *, batched: bool = False) -> None:
    """Take a submitted report in and, when it is to be told, tell it.

    Idempotent on (recipient, report_id): a report already settled is left alone, and
    one a crashed attempt left received or queued is carried on from where it stopped.
    batched says the report already waited for its user's other reports.
    """
    log.set_ns(
        "outbox",
        report_id=report.report_id,
        producer=report.producer.value,
        subject_kind=report.subject.kind.value,
    )
    stored = await outbox_items_repository.insert_if_new(
        report, expires_at=clock.now() + timedelta(seconds=OUTBOX_ITEM_RETENTION_SECONDS)
    )
    state = stored.item.state
    if state is ItemState.RECEIVED:
        if not await _queue_if_to_be_told(report, batched=batched):
            return
    elif state is not ItemState.QUEUED:
        log.info(
            f"{LogTag.NOTIFICATION} Outbox report already taken in",
            created=stored.created,
            item_state=state.value,
        )
        return
    await flush_subject(report.recipient, report.subject.id)
