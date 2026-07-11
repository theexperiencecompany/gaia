"""Skip predicates for nurture steps: True means the user already does the
thing the email teaches, so the step is recorded as skipped and never sent."""

from collections.abc import Awaitable, Callable

from app.constants.integrations import GMAIL_INTEGRATION_ID
from app.db.mongodb.collections import (
    conversations_collection,
    todos_collection,
    workflows_collection,
)
from app.services.oauth.oauth_service import check_integration_status

_TODOS_IN_USE_THRESHOLD = 5


async def onboarding_completed(user: dict) -> bool:
    return bool(user.get("onboarding", {}).get("completed"))


async def used_chat(user: dict) -> bool:
    count = await conversations_collection.count_documents(
        {"user_id": str(user["_id"]), "is_onboarding_conversation": {"$ne": True}},
        limit=1,
    )
    return count > 0


async def gmail_connected(user: dict) -> bool:
    return await check_integration_status(GMAIL_INTEGRATION_ID, str(user["_id"]))


async def uses_todos(user: dict) -> bool:
    count = await todos_collection.count_documents(
        {"user_id": str(user["_id"])}, limit=_TODOS_IN_USE_THRESHOLD
    )
    return count >= _TODOS_IN_USE_THRESHOLD


async def has_workflow(user: dict) -> bool:
    count = await workflows_collection.count_documents({"user_id": str(user["_id"])}, limit=1)
    return count > 0


async def linked_platform(user: dict) -> bool:
    links = user.get("platform_links") or {}
    return any(isinstance(link, dict) and link.get("id") for link in links.values())


SKIP_PREDICATES: dict[str, Callable[[dict], Awaitable[bool]]] = {
    "onboarding_completed": onboarding_completed,
    "used_chat": used_chat,
    "gmail_connected": gmail_connected,
    "uses_todos": uses_todos,
    "has_workflow": has_workflow,
    "linked_platform": linked_platform,
}
