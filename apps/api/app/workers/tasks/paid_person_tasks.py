"""The durable half of a billing change's paid-state person properties.

The Dodo webhook writes the subscription row, then re-reads it to set the
person's paid state. A Mongo failure on that read is not recoverable by the
provider's retry: a redelivery reads the row as unchanged and skips the sync.
The webhook hands it here, where ARQ owns the retries.
"""

from arq import Retry
from pymongo.errors import PyMongoError

from app.constants.log_tags import LogTag
from app.constants.payments import PAID_PERSON_SYNC_RETRY_DELAY
from app.services.payments.subscription_events import sync_paid_person_properties
from app.workers.task_envelope import ArqJobContext
from shared.py.wide_events import log

RETRY_BACKOFF_BASE = 2


async def sync_paid_person_properties_task(
    ctx: ArqJobContext, user_id: str, dodo_subscription_id: str
) -> str:
    """Set the user's paid-state person properties from their subscription row as it stands now."""
    job_try = ctx.get("job_try", 1)
    log.set(user={"id": user_id}, paid_person_sync={"subscription_id": dodo_subscription_id})
    try:
        await sync_paid_person_properties(user_id, dodo_subscription_id)
    except PyMongoError as e:
        defer = PAID_PERSON_SYNC_RETRY_DELAY * RETRY_BACKOFF_BASE ** (job_try - 1)
        log.warning(
            f"{LogTag.PAYMENT} Paid person properties sync could not read the row; retrying",
            error_type=type(e).__name__,
            defer_seconds=defer.total_seconds(),
        )
        raise Retry(defer=defer) from e
    return f"sync_paid_person_properties {dodo_subscription_id}"
