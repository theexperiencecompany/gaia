"""Entry points for reporting a message a user should have received and did not."""

from __future__ import annotations

from app.constants.delivery_alerts import RECORD_DELIVERY_FAILURE_TASK
from app.schemas.delivery_failures import DeliveryFailure
from app.utils.redis_utils import RedisPoolManager
from app.workers.queue import enqueue_worker_job
from shared.py.wide_events import log


async def queue_delivery_failure(failure: DeliveryFailure) -> None:
    """Queue failure for Slack alerting; raises if it could not be queued."""
    pool = await RedisPoolManager.get_pool()
    await enqueue_worker_job(pool, RECORD_DELIVERY_FAILURE_TASK, failure.model_dump_json())


async def report_delivery_failure(failure: DeliveryFailure) -> None:
    """Queue failure for Slack alerting from a delivery path that must not fail twice.

    An enqueue error is logged at error level, with what finds the lost message, and
    not raised: the caller is already handling the delivery failure itself.
    """
    try:
        await queue_delivery_failure(failure)
    except Exception as e:
        log.error(
            "delivery failure could not be queued for alerting",
            platform=failure.platform.value,
            kind=failure.kind.value,
            reason=failure.reason,
            error_code=failure.error_code,
            user_id=failure.user_id,
            envelope_id=failure.envelope_id,
            error=str(e),
            error_type=type(e).__name__,
        )
