"""Existing-user rollout — no cold starts.

For each existing user: provision the briefing workflows, then announce on all
connected channels. Users we can derive a goal for get a normal "briefings are
here" announcement and a real first briefing next morning; users we can't get a
short bootstrap interview and their briefings are held (``briefing_bootstrap``
marker) until a goal memory arrives or the grace window elapses.
"""

from datetime import UTC, datetime

from bson import ObjectId

from app.constants.todos import gaia_assigned_filter
from app.db.mongodb.collections import (
    todos_collection,
    user_integrations_collection,
    users_collection,
)
from app.models.notification.notification_models import (
    NotificationContent,
    NotificationRequest,
    NotificationSourceEnum,
    NotificationType,
)
from app.services.briefing import context
from app.services.briefing.service import BOOTSTRAP_FIELD
from app.services.notification_service import notification_service
from app.services.system_workflows.provisioner import provision_briefing_workflows
from app.services.user_service import get_user_by_id
from app.utils.analytics import track
from shared.py.wide_events import log

# When we can't derive a goal AND the account is this sparse, interview instead
# of guessing.
_SPARSE_INTEGRATION_MAX = 1

_ANNOUNCE_TITLE = "Your daily briefing starts tomorrow"
_ANNOUNCE_BODY = (
    "Every morning I'll curate your list, look back at what shipped, and plan the "
    "day in one short brief — with work a single reply releases. First one lands "
    "tomorrow morning. Change the time or turn it off anytime in your workflows."
)

_BOOTSTRAP_TITLE = "Let's set up your daily briefing"
_BOOTSTRAP_BODY = (
    "I'm about to start sending you a morning brief. Three quick things so it's "
    "actually useful:\n"
    "1. What are you working on right now?\n"
    "2. What should I take off your plate?\n"
    "3. What hour do you want your briefing?\n"
    "Reply here and your first brief lands the next morning."
)


async def _is_sparse_account(user_id: str) -> bool:
    integrations = await user_integrations_collection.count_documents({"user_id": user_id})
    if integrations > _SPARSE_INTEGRATION_MAX:
        return False
    gaia_todos = await todos_collection.count_documents(
        {"user_id": user_id, **gaia_assigned_filter()}
    )
    return gaia_todos == 0


async def _announce(user_id: str, title: str, body: str) -> None:
    await notification_service.create_notification(
        NotificationRequest(
            user_id=user_id,
            source=NotificationSourceEnum.BACKGROUND_JOB,
            type=NotificationType.INFO,
            priority=2,
            content=NotificationContent(title=title, body=body),
            metadata={"briefing_announcement": True},
        )
    )


async def announce_and_provision(user_id: str) -> str:
    """Roll out briefings to one existing user. Returns the path taken.

    ``"normal"`` — goal derivable, standard announcement, briefings begin next day.
    ``"bootstrap"`` — sparse + no goal, interview announcement, briefings held.
    """
    log.set(service="briefing_rollout", operation="announce_and_provision", user_id=user_id)
    user = await get_user_by_id(user_id)
    if not user:
        log.warning("briefing_rollout.unknown_user", user_id=user_id)
        return "skipped"
    user["user_id"] = user_id

    await provision_briefing_workflows(user_id)

    _, has_goal = await context.format_goal_block(user_id, user)
    if not has_goal and await _is_sparse_account(user_id):
        await users_collection.update_one(
            {"_id": ObjectId(user_id)},
            {"$set": {BOOTSTRAP_FIELD: {"pending": True, "since": datetime.now(UTC)}}},
        )
        await _announce(user_id, _BOOTSTRAP_TITLE, _BOOTSTRAP_BODY)
        track(user_id, "briefing_announced", {"path": "bootstrap"})
        return "bootstrap"

    await _announce(user_id, _ANNOUNCE_TITLE, _ANNOUNCE_BODY)
    track(user_id, "briefing_announced", {"path": "normal"})
    return "normal"
