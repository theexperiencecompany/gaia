"""Skip predicates for nurture steps: True means the user already does the
thing the email teaches, so the step is recorded as skipped and never sent.

All predicates are async so SKIP_PREDICATES stays a uniform awaitable map,
even for the few that only read the already-fetched user document.
"""

from collections.abc import Awaitable, Callable

from app.constants.integrations import GMAIL_INTEGRATION_ID, GOOGLE_CALENDAR_INTEGRATION_ID
from app.db.mongodb.collections import (
    conversations_collection,
    todos_collection,
    workflows_collection,
)
from app.services.oauth.oauth_service import check_multiple_integrations_status

_TODOS_IN_USE_THRESHOLD = 5


# Async without await is intentional: uniform SKIP_PREDICATES interface (see module docstring).
async def onboarding_completed(user: dict) -> bool:  # NOSONAR python:S7503
    """True once the user has finished onboarding."""
    return bool(user.get("onboarding", {}).get("completed"))


async def used_chat(user: dict) -> bool:
    """True once the user has a real (non-onboarding) conversation."""
    count = await conversations_collection.count_documents(
        {"user_id": str(user["_id"]), "is_onboarding_conversation": {"$ne": True}},
        limit=1,
    )
    return count > 0


async def google_suite_connected(user: dict) -> bool:
    """True only when BOTH Gmail and Google Calendar are connected."""
    statuses = await check_multiple_integrations_status(
        [GMAIL_INTEGRATION_ID, GOOGLE_CALENDAR_INTEGRATION_ID], str(user["_id"])
    )
    return all(statuses.values())


async def uses_todos(user: dict) -> bool:
    """True once the user has enough todos to count as using the feature."""
    count = await todos_collection.count_documents(
        {"user_id": str(user["_id"])}, limit=_TODOS_IN_USE_THRESHOLD
    )
    return count >= _TODOS_IN_USE_THRESHOLD


async def has_workflow(user: dict) -> bool:
    """True once the user has created at least one workflow."""
    count = await workflows_collection.count_documents({"user_id": str(user["_id"])}, limit=1)
    return count > 0


# Async without await is intentional: uniform SKIP_PREDICATES interface (see module docstring).
async def linked_platform(user: dict) -> bool:  # NOSONAR python:S7503
    """True once the user linked any chat platform (WhatsApp/Telegram/Slack/Discord)."""
    links = user.get("platform_links") or {}
    return any(isinstance(link, dict) and link.get("id") for link in links.values())


SKIP_PREDICATES: dict[str, Callable[[dict], Awaitable[bool]]] = {
    "onboarding_completed": onboarding_completed,
    "used_chat": used_chat,
    "google_suite_connected": google_suite_connected,
    "uses_todos": uses_todos,
    "has_workflow": has_workflow,
    "linked_platform": linked_platform,
}
