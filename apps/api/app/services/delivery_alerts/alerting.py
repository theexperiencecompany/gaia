"""Turns reported delivery failures into Slack incidents (runs in the ARQ worker)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import time

from app.constants.delivery_alerts import (
    DELIVERY_INCIDENT_LOCK_ACQUIRE_SECONDS,
    DELIVERY_INCIDENT_LOCK_LEASE_SECONDS,
    DELIVERY_INCIDENT_LOCK_MAX_HOLD_SECONDS,
    DELIVERY_INCIDENT_LOCK_RENEW_SECONDS,
    DELIVERY_INCIDENT_REFRESH_SECONDS,
    DELIVERY_INCIDENT_THREAD_LIMIT,
    REFRESH_DELIVERY_INCIDENT_TASK,
    REFRESH_JOB_ID_TEMPLATE,
)
from app.db.redis import redis_cache
from app.db.repositories.users import user_repository
from app.schemas.delivery_failures import DeliveryFailure
from app.services.delivery_alerts.incidents import (
    attach_slack_message,
    discard_incident,
    incident_fingerprint,
    incident_lock_key,
    read_incident,
    record_occurrence,
)
from app.services.delivery_alerts.slack import AlertRecipient, get_delivery_alerts_slack
from app.utils.redis_lock import DistributedLock
from app.utils.redis_utils import RedisPoolManager
from app.workers.queue import enqueue_worker_job
from shared.py.wide_events import log


async def _resolve_recipient(failure: DeliveryFailure) -> AlertRecipient:
    if failure.user_id:
        user = await user_repository.get(failure.user_id)
        return AlertRecipient(user_id=failure.user_id, email=user.email if user else None)
    if failure.destination_id and not failure.is_channel:
        user = await user_repository.get_by_platform_id(
            failure.platform.value, failure.destination_id
        )
        if user is not None:
            return AlertRecipient(user_id=user.id, email=user.email)
    return AlertRecipient(user_id=None, email=None)


async def _schedule_refresh(fingerprint: str) -> None:
    """Enqueue one refresh per incident per bucket, run at the bucket's end.

    The failure is recorded first, so the parent message catches up within one bucket.
    """
    bucket = int(time.time()) // DELIVERY_INCIDENT_REFRESH_SECONDS
    run_at = datetime.fromtimestamp((bucket + 1) * DELIVERY_INCIDENT_REFRESH_SECONDS, UTC)
    pool = await RedisPoolManager.get_pool()
    await enqueue_worker_job(
        pool,
        REFRESH_DELIVERY_INCIDENT_TASK,
        fingerprint,
        _job_id=REFRESH_JOB_ID_TEMPLATE.format(fingerprint=fingerprint, bucket=bucket),
        _defer_until=run_at,
        _expires=timedelta(seconds=DELIVERY_INCIDENT_REFRESH_SECONDS * 4),
    )


async def alert_delivery_failure(failure: DeliveryFailure) -> None:
    """Record failure in its incident; post the incident or a thread reply as due."""
    log.set(
        delivery_failure={
            "platform": failure.platform.value,
            "kind": failure.kind.value,
            "reason": failure.reason,
            "error_code": failure.error_code,
            "reporter": failure.reporter,
            "envelope_id": failure.envelope_id,
        }
    )
    slack = await get_delivery_alerts_slack()
    if slack is None:
        log.warning(
            "delivery failure not posted: Slack delivery alerts are not configured",
            platform=failure.platform.value,
            kind=failure.kind.value,
        )
        return

    recipient = await _resolve_recipient(failure)
    failure = failure.model_copy(update={"user_id": recipient.user_id})
    log.set_ns("delivery_failure", user_id=recipient.user_id)

    redis = redis_cache.client
    fingerprint = incident_fingerprint(failure)
    lock = DistributedLock(
        incident_lock_key(fingerprint),
        lease_seconds=DELIVERY_INCIDENT_LOCK_LEASE_SECONDS,
        acquire_timeout_seconds=DELIVERY_INCIDENT_LOCK_ACQUIRE_SECONDS,
        renew_seconds=DELIVERY_INCIDENT_LOCK_RENEW_SECONDS,
        max_hold_seconds=DELIVERY_INCIDENT_LOCK_MAX_HOLD_SECONDS,
    )
    async with lock.hold() as held:
        if not held:
            # Unlocked, two failures could each open the incident and post it twice.
            raise RuntimeError(f"delivery incident lock not acquired for {fingerprint}")
        incident = await record_occurrence(redis, failure)
        ts = incident.slack_ts
        if ts is None:
            try:
                ts = await slack.post_incident(incident)
            except Exception:
                # Left in place, every later failure would count toward an incident
                # nobody can see; dropped, the next one opens it again.
                await discard_incident(redis, fingerprint)
                raise
            await attach_slack_message(redis, fingerprint, ts)
        if incident.count <= DELIVERY_INCIDENT_THREAD_LIMIT:
            await slack.post_occurrence(ts, failure, recipient)

    log.set(delivery_incident={"fingerprint": fingerprint, "count": incident.count})
    await _schedule_refresh(fingerprint)


async def refresh_delivery_incident(fingerprint: str) -> None:
    """Re-render an incident's parent message with its current numbers."""
    log.set(delivery_incident={"fingerprint": fingerprint})
    slack = await get_delivery_alerts_slack()
    if slack is None:
        return
    incident = await read_incident(redis_cache.client, fingerprint)
    if incident is None or incident.slack_ts is None:
        log.set_ns("delivery_incident", state="closed" if incident is None else "unposted")
        return
    await slack.update_incident(incident, incident.slack_ts)
    log.set_ns("delivery_incident", count=incident.count)
