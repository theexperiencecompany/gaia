"""ARQ worker task for post-onboarding personalization."""

from app.services.onboarding.post_onboarding_service import (
    process_post_onboarding_personalization,
)


async def process_personalization_task(ctx, user_id: str) -> str:
    """
    ARQ background task to generate personalized onboarding card.

    Args:
        ctx: ARQ context (unused but required)
        user_id: User ID to process personalization for

    Returns:
        Processing result message
    """
    try:
        await process_post_onboarding_personalization(user_id)
        return f"Post-onboarding personalization completed for user {user_id}"
    except Exception as e:
        return f"Fatal error in post-onboarding personalization for user {user_id}: {e}"
