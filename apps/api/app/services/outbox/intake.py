"""Intake: how a report enters the outbox, and what happens to it before anyone is told.

submit is durable: it enqueues an ARQ job keyed by the report id and raises when the
enqueue fails, so a producer never believes a report it lost. The job body is
process_report: insert the item once (a second submit of the same report finds it),
let the latest report of a replace subject stand, have the Judge read what it means for
the user (unless the policy decides it without one), apply the policy, and send what is to
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
from app.constants.outbox_judge import (
    JUDGE_BATCH_WINDOW_SECONDS,
    JUDGE_INTERRUPT_CAP_WINDOW_SECONDS,
)
from app.db.repositories.outbox_items import outbox_items_repository
from app.services.outbox.deliver import flush_subject
from app.services.outbox.judge import judge_report
from app.services.outbox.judge_models import ItemJudgement
from app.services.outbox.metrics import OUTBOX_ITEMS_DROPPED, OUTBOX_JUDGE_INTERRUPT_CAPPED
from app.services.outbox.models import ItemState, OutboxReport, SubjectMerge
from app.services.outbox.policy import (
    Decision,
    DecisionKind,
    decide,
    is_progress,
    record_only_reason,
    waits_for_batch,
)
from app.services.outbox.watching import is_watched_live
from app.utils import clock
from app.utils.redis_utils import RedisPoolManager
from app.workers.queue import enqueue_worker_job
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
    if record_only_reason(report, watched_live=watched_live) is not None:
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


async def _queue_if_to_be_told(report: OutboxReport, *, batched: bool) -> bool:
    """Run a received report through supersede, the Judge and the policy; True when it is queued to be told.

    False also when it was handed back to the queue to wait for its user's other reports.
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
        and record_only_reason(report, watched_live=watched_live) is None
    ):
        await _enqueue(report, batched=True)
        return False
    decision, judgement = await _judge_and_decide(report, watched_live=watched_live)
    if decision.kind is DecisionKind.RECORD_ONLY and decision.drop_reason is not None:
        dropped = await outbox_items_repository.drop(
            report.recipient, report.report_id, decision.drop_reason, judgement=judgement
        )
        if dropped is not None:
            OUTBOX_ITEMS_DROPPED.labels(reason=decision.drop_reason.value).inc()
        log.info(
            f"{LogTag.NOTIFICATION} Outbox report recorded, not alerted",
            drop_reason=decision.drop_reason.value,
        )
        return False
    queued = await outbox_items_repository.queue(
        report.recipient,
        report.report_id,
        urgency=decision.urgency,
        mode=decision.mode,
        judgement=judgement,
    )
    return queued is not None


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
