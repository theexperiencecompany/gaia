"""ARQ worker task for the Gmail personalization pipeline."""

from typing import Any

from app.constants.log_tags import LogTag
from app.services.onboarding.intelligence_job import clear_active_intelligence_job
from shared.py.wide_events import log


async def process_onboarding_intelligence_task(ctx: dict[str, Any], user_id: str) -> str:
    """ARQ background task for the Gmail personalization pipeline."""
    log.set(user_id=user_id, user={"id": user_id})
    from app.services.onboarding.intelligence_service import (  # noqa: PLC0415 -- heavy personalization pipeline kept off worker-task module load path
        process_onboarding_intelligence,
    )

    job_id = ctx.get("job_id")
    try:
        await process_onboarding_intelligence(user_id)
    except Exception as e:
        log.error(
            f"{LogTag.WORKER} Gmail personalization failed",
            user_id=user_id,
            error_type=type(e).__name__,
            error=str(e),
            exc_info=True,
        )
        return f"Gmail personalization failed for user {user_id}: {e}"
    finally:
        if job_id:
            try:
                await clear_active_intelligence_job(user_id, job_id)
            except Exception as clear_err:
                log.warning(
                    f"{LogTag.WORKER} Failed to clear personalization job id",
                    user_id=user_id,
                    job_id=job_id,
                    error_type=type(clear_err).__name__,
                    error=str(clear_err),
                )

    log.info(f"{LogTag.WORKER} Gmail personalization completed", user_id=user_id)
    return f"Gmail personalization completed for user {user_id}"
