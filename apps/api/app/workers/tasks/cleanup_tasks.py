"""ARQ cleanup tasks for stuck/failed background processes."""

from datetime import datetime, timedelta, timezone

from app.config.loggers import arq_worker_logger as logger
from app.db.mongodb.collections import users_collection
from app.models.user_models import BioStatus
from app.utils.redis_utils import RedisPoolManager


async def cleanup_stuck_personalization(ctx, max_age_minutes: int = 30) -> str:
    """
    Find users stuck in PROCESSING/PENDING bio_status and re-queue personalization.

    This task runs periodically to clean up stuck states caused by:
    - Network failures during email processing
    - LLM timeouts
    - Mem0 API failures
    - Process crashes

    Instead of directly processing, this queues ARQ jobs to avoid blocking.

    Args:
        ctx: ARQ context
        max_age_minutes: How long to wait before considering a status "stuck"

    Returns:
        Summary of cleanup actions
    """
    try:
        cutoff_time = datetime.now(timezone.utc) - timedelta(minutes=max_age_minutes)

        # Find users stuck in PROCESSING or PENDING for too long
        stuck_users = await users_collection.find(
            {
                "onboarding.completed": True,
                "onboarding.bio_status": {
                    "$in": [
                        BioStatus.PROCESSING,
                        "processing",
                        BioStatus.PENDING,
                        "pending",
                    ]
                },
                "$or": [
                    # Updated more than max_age_minutes ago
                    {"updated_at": {"$lt": cutoff_time}},
                    # No updated_at field (old documents)
                    {"updated_at": {"$exists": False}},
                ],
            }
        ).to_list(length=50)  # Limit to 50 at a time to avoid overwhelming ARQ

        if not stuck_users:
            return f"No stuck users found (checked users older than {max_age_minutes}m)"

        # Get ARQ pool to queue jobs
        pool = await RedisPoolManager.get_pool()

        queued_count = 0
        error_count = 0

        for user in stuck_users:
            user_id = str(user["_id"])
            bio_status = user.get("onboarding", {}).get("bio_status")
            updated_at = user.get("updated_at", "unknown")

            try:
                # Queue personalization job instead of running directly
                job = await pool.enqueue_job("process_personalization_task", user_id)

                if job:
                    logger.info(
                        f"Re-queued personalization for stuck user {user_id} "
                        f"(status={bio_status}, last_update={updated_at}, job_id={job.job_id})"
                    )
                    queued_count += 1
                else:
                    logger.warning(f"Failed to queue job for user {user_id}")
                    error_count += 1

            except Exception as e:
                logger.error(
                    f"Error queuing personalization for user {user_id}: {e}",
                    exc_info=True,
                )
                error_count += 1

        return (
            f"Cleanup completed: {queued_count} users re-queued, "
            f"{error_count} errors (found {len(stuck_users)} stuck users)"
        )

    except Exception as e:
        error_msg = f"Error in cleanup_stuck_personalization: {e}"
        logger.error(error_msg, exc_info=True)
        return error_msg
