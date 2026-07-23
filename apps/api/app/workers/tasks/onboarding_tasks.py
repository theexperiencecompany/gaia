"""ARQ worker task for post-onboarding personalization."""

from datetime import UTC, datetime

from bson import ObjectId

from app.constants.log_tags import LogTag
from app.db.mongodb.collections import users_collection
from app.models.user_models import OnboardingPhase
from app.services.onboarding.intelligence_job import (
    clear_active_intelligence_job,
    clear_active_workflows_job,
)
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
                f"{LogTag.WORKER} Onboarding intelligence failed for user {user_id}: {e}",
                exc_info=True,
            )
            try:
                # Split-mode early job: leave the phase pending — the workflows
                # phase (or the stuck-personalization cron) completes the flow.
                doc = await users_collection.find_one(
                    {"_id": ObjectId(user_id)}, {"onboarding.pipeline_mode": 1}
                )
                split_mode = ((doc or {}).get("onboarding") or {}).get("pipeline_mode") == "split"
                if not split_mode:
                    await users_collection.update_one(
                        {"_id": ObjectId(user_id)},
                        {
                            "$set": {
                                "onboarding.phase": OnboardingPhase.PERSONALIZATION_COMPLETE,
                                "updated_at": datetime.now(UTC),
                            }
                        },
                    )
                    log.info(
                        f"{LogTag.WORKER} Set phase to PERSONALIZATION_COMPLETE after failure for user {user_id}"
                    )
            except Exception as db_err:
                log.error(
                    f"{LogTag.WORKER} Failed to update onboarding phase after error for user {user_id}: {db_err}",
                    exc_info=True,
                )
            return f"Onboarding intelligence failed for user {user_id}: {e}"
        finally:
            if job_id:
                try:
                    await clear_active_intelligence_job(user_id, job_id)
                except Exception as clear_err:
                    log.warning(
                        f"{LogTag.WORKER} Failed to clear intelligence job id for user {user_id}: {clear_err}"
                    )

        message = f"Onboarding intelligence completed for user {user_id}"
        log.info(f"{LogTag.WORKER} {message}")
        return message


async def process_onboarding_workflows_task(ctx: dict, user_id: str) -> str:
    """ARQ background task for the split-pipeline workflows phase."""
    async with wide_task("process_onboarding_workflows_task", user_id=user_id):
        log.set(user={"id": user_id})
        from app.services.onboarding.intelligence_service import (
            process_onboarding_workflows_phase,
        )

        job_id = ctx.get("job_id")
        try:
            await process_onboarding_workflows_phase(user_id)
        except Exception as e:
            log.error(
                f"{LogTag.WORKER} Onboarding workflows phase failed for user {user_id}: {e}",
                exc_info=True,
            )
            # This IS the completing phase — rescue the user out of the pending
            # state exactly like the full pipeline's failure path.
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
            except Exception as db_err:
                log.error(
                    f"{LogTag.WORKER} Failed to update onboarding phase after error for user {user_id}: {db_err}",
                    exc_info=True,
                )
            return f"Onboarding workflows phase failed for user {user_id}: {e}"
        finally:
            if job_id:
                try:
                    await clear_active_workflows_job(user_id, job_id)
                except Exception as clear_err:
                    log.warning(
                        f"{LogTag.WORKER} Failed to clear workflows job id for user {user_id}: {clear_err}"
                    )

        message = f"Onboarding workflows phase completed for user {user_id}"
        log.info(f"{LogTag.WORKER} {message}")
        return message
