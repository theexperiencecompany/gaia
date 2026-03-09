"""ARQ worker task for post-onboarding personalization."""

from shared.py.wide_events import log, wide_task
from app.services.onboarding.post_onboarding_service import (
    process_post_onboarding_personalization,
)


async def process_personalization_task(ctx, user_id: str) -> str:
    """ARQ background task to generate personalized onboarding card."""
    async with wide_task("process_personalization_task", user_id=user_id):
        log.set(user={"id": user_id})
        await process_post_onboarding_personalization(user_id)
        log.set(outcome="success")
        return f"Post-onboarding personalization completed for user {user_id}"
