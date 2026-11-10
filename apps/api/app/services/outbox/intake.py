"""Intake: how a report enters the outbox, and what happens to it before anyone is told.

submit is durable: it enqueues an ARQ job keyed by the report id and raises when the
enqueue fails, so a producer never believes a report it lost. The job body is
process_report: insert the item once (a second submit of the same report finds it),
let the latest report of a replace subject stand, apply the policy, and send what
is to be told.
"""

from datetime import timedelta

from app.constants.log_tags import LogTag
from app.constants.outbox import (
    OUTBOX_INTAKE_TASK,
    OUTBOX_ITEM_RETENTION_SECONDS,
    OUTBOX_JOB_ID_PREFIX,
)
from app.db.repositories.outbox_items import outbox_items_repository
from app.services.outbox.deliver import flush_subject
from app.services.outbox.metrics import OUTBOX_ITEMS_DROPPED
from app.services.outbox.models import ItemState, OutboxReport, SubjectMerge
from app.services.outbox.policy import DecisionKind, decide
from app.utils import clock
from app.utils.redis_utils import RedisPoolManager
from app.workers.queue import enqueue_worker_job
from shared.py.wide_events import log


async def submit(report: OutboxReport) -> None:
    """Hand a report to the outbox: durable once this returns, and raises when it cannot be."""
    pool = await RedisPoolManager.get_pool()
    await enqueue_worker_job(
        pool,
        OUTBOX_INTAKE_TASK,
        report.model_dump(mode="json"),
        _job_id=f"{OUTBOX_JOB_ID_PREFIX}{report.report_id}",
    )


async def _queue_if_to_be_told(report: OutboxReport) -> bool:
    """Run a received report through supersede and the policy; True when it is queued to be told."""
    if (
        report.subject.merge is SubjectMerge.REPLACE
        and not await outbox_items_repository.apply_replace(report)
    ):
        log.info(f"{LogTag.NOTIFICATION} Outbox report superseded by a newer one")
        return False
    decision = decide(report)
    if decision.kind is DecisionKind.RECORD_ONLY and decision.drop_reason is not None:
        dropped = await outbox_items_repository.drop(
            report.recipient, report.report_id, decision.drop_reason
        )
        if dropped is not None:
            OUTBOX_ITEMS_DROPPED.labels(reason=decision.drop_reason.value).inc()
        log.info(
            f"{LogTag.NOTIFICATION} Outbox report recorded, not alerted",
            drop_reason=decision.drop_reason.value,
        )
        return False
    queued = await outbox_items_repository.queue(
        report.recipient, report.report_id, urgency=decision.urgency, mode=decision.mode
    )
    return queued is not None


async def process_report(report: OutboxReport) -> None:
    """Take a submitted report in and, when it is to be told, tell it.

    Idempotent on (recipient, report_id): a report already settled is left alone, and
    one a crashed attempt left received or queued is carried on from where it stopped.
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
        if not await _queue_if_to_be_told(report):
            return
    elif state is not ItemState.QUEUED:
        log.info(
            f"{LogTag.NOTIFICATION} Outbox report already taken in",
            created=stored.created,
            item_state=state.value,
        )
        return
    await flush_subject(report.recipient, report.subject.id)
