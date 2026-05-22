"""Post-onboarding personalization service."""

from datetime import datetime, timezone
from typing import Any, List

from shared.py.wide_events import log
from app.db.mongodb.collections import users_collection
from app.models.user_models import BioStatus, OnboardingPhase
from app.utils.seeding_utils import seed_onboarding_todo
from bson import ObjectId


async def save_personalization_data(
    user_id: str,
    house: str,
    personality_phrase: str,
    user_bio: str,
    bio_status: BioStatus,
    workflow_ids: List[str],
    account_number: int,
    member_since: str,
    overlay_color: str,
    overlay_opacity: int,
) -> None:
    """
    Save personalization data to user document.

    Args:
        user_id: User identifier
        house: Assigned house
        personality_phrase: Generated phrase
        user_bio: Generated bio
        bio_status: Status of bio generation
        workflow_ids: Suggested workflow IDs
        account_number: User's account number
        member_since: Member since date
        overlay_color: Generated overlay color or gradient
        overlay_opacity: Opacity percentage
    """
    try:
        update_fields: dict[str, Any] = {
            "onboarding.house": house,
            "onboarding.personality_phrase": personality_phrase,
            "onboarding.user_bio": user_bio,
            "onboarding.bio_status": bio_status,
            "onboarding.phase": OnboardingPhase.PERSONALIZATION_COMPLETE,
            "onboarding.account_number": account_number,
            "onboarding.member_since": member_since,
            "onboarding.overlay_color": overlay_color,
            "onboarding.overlay_opacity": overlay_opacity,
            "updated_at": datetime.now(timezone.utc),
        }
        if workflow_ids:
            update_fields["onboarding.suggested_workflows"] = workflow_ids
        await users_collection.update_one(
            {"_id": ObjectId(user_id)},
            {"$set": update_fields},
        )
        log.info(f"Saved personalization data for user {user_id}")

    except Exception as e:
        log.error(f"Error saving personalization data: {e}", exc_info=True)


async def seed_initial_user_data(user_id: str) -> None:
    """Seed the onboarding todo. The welcome conversation is seeded by the
    intelligence pipeline, not here."""
    try:
        log.info(f"Starting data seeding for user {user_id}")
        await seed_onboarding_todo(user_id)
        log.info(f"Completed data seeding for user {user_id}")

    except Exception as e:
        log.error(f"Error in seed_initial_user_data for user {user_id}: {e}")
