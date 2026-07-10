"""Activation checklist (first-steps widget) progress.

Progress derives from real signals — route visits, integration connects,
platform links, the first Approve — never self-report. Steps satisfied before
the widget ever rendered are pre-checked on first read so long-time users
aren't asked to redo history.
"""

from datetime import UTC, datetime
from typing import Any

from bson import ObjectId

from app.constants.integrations import INTEGRATION_STATUS_CONNECTED
from app.db.mongodb.collections import user_integrations_collection, users_collection
from app.utils.analytics import track

STEP_EXPLORE_WORKFLOWS = "explore_workflows"
STEP_CONNECT_INTEGRATION = "connect_integration"
STEP_LINK_TELEGRAM = "link_telegram"
STEP_VISIT_DASHBOARD = "visit_dashboard"
STEP_FIRST_APPROVE = "first_approve"
STEP_DISMISSED_ALL = "dismissed_all"

ALL_STEPS: tuple[str, ...] = (
    STEP_EXPLORE_WORKFLOWS,
    STEP_CONNECT_INTEGRATION,
    STEP_LINK_TELEGRAM,
    STEP_VISIT_DASHBOARD,
    STEP_FIRST_APPROVE,
)
_VALID_STEPS: frozenset[str] = frozenset((*ALL_STEPS, STEP_DISMISSED_ALL))


async def mark_step(user_id: str, step: str) -> None:
    """Idempotently record a step completion (no-op on repeats or unknown steps)."""
    if step not in _VALID_STEPS:
        return
    result = await users_collection.update_one(
        {"_id": ObjectId(user_id), f"first_steps.{step}": {"$exists": False}},
        {"$set": {f"first_steps.{step}": datetime.now(UTC)}},
    )
    if result.modified_count:
        track(user_id, "first_steps_step_done", {"step": step})


async def get_steps(user_id: str) -> dict[str, Any]:
    """Current progress, pre-checking steps already satisfied by existing state."""
    user = await users_collection.find_one({"_id": ObjectId(user_id)}, {"first_steps": 1}) or {}
    steps: dict[str, Any] = user.get("first_steps", {})

    if STEP_LINK_TELEGRAM not in steps:
        # Read the link field directly (importing PlatformLinkService here would
        # create a cycle — it marks steps on link_account).
        doc = await users_collection.find_one(
            {"_id": ObjectId(user_id)}, {"platform_links.telegram": 1}
        )
        if (doc or {}).get("platform_links", {}).get("telegram", {}).get("id"):
            await mark_step(user_id, STEP_LINK_TELEGRAM)
            steps[STEP_LINK_TELEGRAM] = datetime.now(UTC)
    if STEP_CONNECT_INTEGRATION not in steps:
        # Any connected non-Gmail integration satisfies the step retroactively.
        connected = await user_integrations_collection.find_one(
            {
                "user_id": user_id,
                "status": INTEGRATION_STATUS_CONNECTED,
                "integration_id": {"$ne": "gmail"},
            }
        )
        if connected:
            await mark_step(user_id, STEP_CONNECT_INTEGRATION)
            steps[STEP_CONNECT_INTEGRATION] = datetime.now(UTC)

    return {
        "steps": {step: steps[step].isoformat() if steps.get(step) else None for step in ALL_STEPS},
        "dismissed": STEP_DISMISSED_ALL in steps,
    }
