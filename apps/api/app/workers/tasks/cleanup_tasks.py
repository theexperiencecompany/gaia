"""ARQ cleanup tasks for stuck/failed background processes."""

from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any

from app.constants.log_tags import LogTag
from app.db.repositories.users import user_repository
from app.models.user_models import UserDocument
from app.services.onboarding.intelligence_job import (
    enqueue_gmail_personalization,
    is_intelligence_job_live,
)
from shared.py.wide_events import log


class _RequeueOutcome(Enum):
    """Result of attempting to re-queue one stuck user's onboarding job."""

    QUEUED = "queued"
    SKIPPED = "skipped"  # Live job or still awaiting user input — not stuck.
    ERROR = "error"


async def _requeue_stuck_user(user: UserDocument) -> _RequeueOutcome:
    """Re-queue the personalization job for one stuck user, skipping any whose
    ARQ job is still live (a slow-but-healthy pipeline is never aborted).

    Legacy safety net: only users who submitted onboarding before the pipeline
    moved to Gmail-connect can still be at personalization_pending, and
    enqueue_gmail_personalization no-ops for any of them whose pipeline
    already ran."""
    user_id = user.id
    last_update = str(user.updated_at) if user.updated_at is not None else "unknown"

    if await is_intelligence_job_live(user_id):
        log.info(
            f"{LogTag.WORKER} skipping live pipeline",
            user_id=user_id,
            last_update=last_update,
        )
        return _RequeueOutcome.SKIPPED

    job_id = await enqueue_gmail_personalization(user_id)
    if not job_id:
        log.warning(f"{LogTag.WORKER} enqueue returned no job", user_id=user_id)
        return _RequeueOutcome.ERROR
    log.info(
        f"{LogTag.WORKER} re-queued stuck user",
        user_id=user_id,
        last_update=last_update,
        job_id=job_id,
    )
    return _RequeueOutcome.QUEUED


async def cleanup_stuck_personalization(ctx: dict[str, Any], max_age_minutes: int = 30) -> str:  # noqa: ARG001 -- ARQ injects ctx positionally into every registered task
    """Re-queue users stuck at personalization_pending past max_age_minutes.

    Skips users whose ARQ job is still live so a slow-but-healthy pipeline is
    never aborted. Keep max_age_minutes >= ARQ job_timeout.
    """
    log.set(max_age_minutes=max_age_minutes)
    try:
        cutoff_time = datetime.now(UTC) - timedelta(minutes=max_age_minutes)

        stuck_candidates = await user_repository.find_stuck_personalization(cutoff_time, limit=50)

        if not stuck_candidates:
            return (
                f"No stuck users found "
                f"(checked users older than {max_age_minutes}m at "
                f"phase=personalization_pending)"
            )

        log.set(stuck_candidates_detected=len(stuck_candidates))

        tally = {
            _RequeueOutcome.QUEUED: 0,
            _RequeueOutcome.SKIPPED: 0,
            _RequeueOutcome.ERROR: 0,
        }
        for user in stuck_candidates:
            user_id = user.id
            try:
                outcome = await _requeue_stuck_user(user)
            except Exception as e:
                log.exception(
                    f"{LogTag.WORKER} error re-queueing user",
                    user_id=user_id,
                    error_type=type(e).__name__,
                    error=str(e),
                )
                outcome = _RequeueOutcome.ERROR
            tally[outcome] += 1

        log.set(
            jobs_queued=tally[_RequeueOutcome.QUEUED],
            jobs_skipped_live=tally[_RequeueOutcome.SKIPPED],
        )
        return (
            f"Cleanup completed: {tally[_RequeueOutcome.QUEUED]} re-queued, "
            f"{tally[_RequeueOutcome.SKIPPED]} skipped (live), "
            f"{tally[_RequeueOutcome.ERROR]} errors "
            f"(found {len(stuck_candidates)} candidates)"
        )

    except Exception as e:
        log.exception(
            f"{LogTag.WORKER} Error in cleanup_stuck_personalization",
            error_type=type(e).__name__,
            error=str(e),
        )
        return f"Error in cleanup_stuck_personalization: {e}"
