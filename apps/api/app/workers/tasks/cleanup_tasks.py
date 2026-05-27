"""ARQ cleanup tasks for stuck/failed background processes."""

from datetime import UTC, datetime, timedelta

from app.db.mongodb.collections import users_collection
from app.models.user_models import OnboardingPhase
from app.services.onboarding.intelligence_job import (
    enqueue_intelligence_job,
    is_intelligence_job_live,
)
from shared.py.wide_events import log, wide_task


async def cleanup_stuck_personalization(ctx, max_age_minutes: int = 30) -> str:
    """Re-queue users stuck at personalization_pending past max_age_minutes.

    Skips users whose ARQ job is still live so a slow-but-healthy pipeline is
    never aborted. Keep max_age_minutes >= ARQ job_timeout.
    """
    async with wide_task("cleanup_stuck_personalization", max_age_minutes=max_age_minutes):
        try:
            cutoff_time = datetime.now(UTC) - timedelta(minutes=max_age_minutes)

            stuck_candidates = await users_collection.find(
                {
                    "onboarding.phase": OnboardingPhase.PERSONALIZATION_PENDING.value,
                    "$or": [
                        {"updated_at": {"$lt": cutoff_time}},
                        {"updated_at": {"$exists": False}},
                    ],
                }
            ).to_list(length=50)

            if not stuck_candidates:
                return (
                    f"No stuck users found "
                    f"(checked users older than {max_age_minutes}m at "
                    f"phase=personalization_pending)"
                )

            log.set(stuck_candidates_detected=len(stuck_candidates))

            queued_count = 0
            skipped_live_count = 0
            error_count = 0

            for user in stuck_candidates:
                user_id = str(user["_id"])
                updated_at = user.get("updated_at", "unknown")

                try:
                    if await is_intelligence_job_live(user_id):
                        log.info(
                            "[cleanup] skipping live pipeline",
                            user_id=user_id,
                            last_update=str(updated_at),
                        )
                        skipped_live_count += 1
                        continue

                    job_id = await enqueue_intelligence_job(user_id)
                    if job_id:
                        log.info(
                            "[cleanup] re-queued stuck user",
                            user_id=user_id,
                            last_update=str(updated_at),
                            job_id=job_id,
                        )
                        queued_count += 1
                    else:
                        log.warning(
                            "[cleanup] enqueue returned no job",
                            user_id=user_id,
                        )
                        error_count += 1

                except Exception as e:
                    log.exception(
                        f"[cleanup] error re-queueing user {user_id}: {e}",
                    )
                    error_count += 1

            log.set(
                jobs_queued=queued_count,
                jobs_skipped_live=skipped_live_count,
            )
            return (
                f"Cleanup completed: {queued_count} re-queued, "
                f"{skipped_live_count} skipped (live), "
                f"{error_count} errors "
                f"(found {len(stuck_candidates)} candidates)"
            )

        except Exception as e:
            error_msg = f"Error in cleanup_stuck_personalization: {e}"
            log.exception(error_msg)
            return error_msg
