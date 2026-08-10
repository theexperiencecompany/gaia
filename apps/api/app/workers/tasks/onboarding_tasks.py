"""ARQ worker task for post-onboarding personalization."""

from typing import Any

from app.constants.log_tags import LogTag
from app.db.repositories.users import user_repository
from app.models.user_models import OnboardingPhase
from app.services.onboarding.intelligence_job import (
    clear_active_intelligence_job,
    clear_active_workflows_job,
)
from shared.py.wide_events import log


async def process_onboarding_intelligence_task(ctx: dict[str, Any], user_id: str) -> str:
    """ARQ background task for the full onboarding intelligence pipeline."""
    log.set(user_id=user_id, user={"id": user_id})
    from app.services.onboarding.intelligence_service import (
        process_onboarding_intelligence,
    )

    job_id = ctx.get("job_id")
    try:
        await process_onboarding_intelligence(user_id)
    except Exception as e:
        log.error(
            f"{LogTag.WORKER} Onboarding intelligence failed",
            user_id=user_id,
            error_type=type(e).__name__,
            error=str(e),
            exc_info=True,
        )
        try:
            # Split-mode early job: leave the phase pending — the workflows
            # phase (or the stuck-personalization cron) completes the flow.
            doc = await user_repository.get(user_id)
            split_mode = ((doc.onboarding if doc else None) or {}).get("pipeline_mode") == "split"
            if not split_mode:
                await user_repository.set_pipeline_completion(
                    user_id, phase=OnboardingPhase.PERSONALIZATION_COMPLETE
                )
                log.info(
                    f"{LogTag.WORKER} Set phase to PERSONALIZATION_COMPLETE after failure",
                    user_id=user_id,
                )
        except Exception as db_err:
            log.error(
                f"{LogTag.WORKER} Failed to update onboarding phase after error",
                user_id=user_id,
                error_type=type(db_err).__name__,
                error=str(db_err),
                exc_info=True,
            )
        return f"Onboarding intelligence failed for user {user_id}: {e}"
    finally:
        if job_id:
            try:
                await clear_active_intelligence_job(user_id, job_id)
            except Exception as clear_err:
                log.warning(
                    f"{LogTag.WORKER} Failed to clear intelligence job id",
                    user_id=user_id,
                    job_id=job_id,
                    error_type=type(clear_err).__name__,
                    error=str(clear_err),
                )

    log.info(f"{LogTag.WORKER} Onboarding intelligence completed", user_id=user_id)
    return f"Onboarding intelligence completed for user {user_id}"


async def process_onboarding_workflows_task(ctx: dict[str, Any], user_id: str) -> str:
    """ARQ background task for the split-pipeline workflows phase."""
    log.set(user_id=user_id, user={"id": user_id})
    from app.services.onboarding.intelligence_service import (
        process_onboarding_workflows_phase,
    )

    job_id = ctx.get("job_id")
    try:
        await process_onboarding_workflows_phase(user_id)
    except Exception as e:
        log.error(
            f"{LogTag.WORKER} Onboarding workflows phase failed",
            user_id=user_id,
            error_type=type(e).__name__,
            error=str(e),
            exc_info=True,
        )
        # This IS the completing phase — rescue the user out of the pending
        # state exactly like the full pipeline's failure path.
        try:
            await user_repository.set_pipeline_completion(
                user_id, phase=OnboardingPhase.PERSONALIZATION_COMPLETE
            )
        except Exception as db_err:
            log.error(
                f"{LogTag.WORKER} Failed to update onboarding phase after error",
                user_id=user_id,
                error_type=type(db_err).__name__,
                error=str(db_err),
                exc_info=True,
            )
        return f"Onboarding workflows phase failed for user {user_id}: {e}"
    finally:
        if job_id:
            try:
                await clear_active_workflows_job(user_id, job_id)
            except Exception as clear_err:
                log.warning(
                    f"{LogTag.WORKER} Failed to clear workflows job id",
                    user_id=user_id,
                    job_id=job_id,
                    error_type=type(clear_err).__name__,
                    error=str(clear_err),
                )

    log.info(f"{LogTag.WORKER} Onboarding workflows phase completed", user_id=user_id)
    return f"Onboarding workflows phase completed for user {user_id}"
