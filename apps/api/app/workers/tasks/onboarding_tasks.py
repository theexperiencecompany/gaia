"""ARQ worker task for post-onboarding personalization."""

from datetime import UTC, datetime

from bson import ObjectId

from app.db.mongodb.collections import users_collection
from app.models.user_models import OnboardingPhase
from app.services.onboarding.intelligence_job import clear_active_intelligence_job
from shared.py.wide_events import log, wide_task


async def process_onboarding_intelligence_task(ctx: dict, user_id: str) -> str:
    """ARQ background task for the full onboarding intelligence pipeline."""
    async with wide_task("process_onboarding_intelligence_task", user_id=user_id):
        log.set(user={"id": user_id})
        from app.services.onboarding.intelligence_service import (
            process_onboarding_intelligence,
        )

        job_id = ctx.get("job_id")
        try:
            await process_onboarding_intelligence(user_id)
        except Exception as e:
            log.error(
                f"Onboarding intelligence failed for user {user_id}: {e}",
                exc_info=True,
            )
            try:
                await users_collection.update_one(
                    {"_id": ObjectId(user_id)},
                    {
                        "$set": {
                            "onboarding.phase": OnboardingPhase.PERSONALIZATION_COMPLETE,
                            "updated_at": datetime.now(UTC),
                        }
                    },
                )
                log.info(f"Set phase to PERSONALIZATION_COMPLETE after failure for user {user_id}")
            except Exception as db_err:
                log.error(
                    f"Failed to update onboarding phase after error for user {user_id}: {db_err}",
                    exc_info=True,
                )
            return f"Onboarding intelligence failed for user {user_id}: {e}"
        finally:
            if job_id:
                try:
                    await clear_active_intelligence_job(user_id, job_id)
                except Exception as clear_err:
                    log.warning(
                        f"Failed to clear intelligence job id for user {user_id}: {clear_err}"
                    )

        message = f"Onboarding intelligence completed for user {user_id}"
        log.info(message)
        return message
