"""Skip predicates for nurture steps: True means the user already does the
thing the email teaches, so the step is recorded as skipped and never sent.

All predicates are async so SKIP_PREDICATES stays a uniform awaitable map,
even for the few that only read the already-fetched user document.
"""

from collections.abc import Awaitable, Callable, Mapping

from app.constants.integrations import GMAIL_INTEGRATION_ID, GOOGLE_CALENDAR_INTEGRATION_ID
from app.db.repositories.conversations import conversation_repository
from app.db.repositories.todos import todo_repository
from app.db.repositories.workflows import workflow_repository
from app.models.user_models import UserDocument
from app.services.oauth.oauth_service import check_multiple_integrations_status

_TODOS_IN_USE_THRESHOLD = 5


# Async without await is intentional: uniform SKIP_PREDICATES interface (see module docstring).
async def onboarding_completed(user: UserDocument) -> bool:  # NOSONAR python:S7503
    """True once the user has finished onboarding."""
    return bool((user.onboarding or {}).get("completed"))


async def used_chat(user: UserDocument) -> bool:
    """True once the user has a real (non-onboarding) conversation."""
    return await conversation_repository.count_non_onboarding(user.id) > 0


async def google_suite_connected(user: UserDocument) -> bool:
    """True only when BOTH Gmail and Google Calendar are connected."""
    statuses = await check_multiple_integrations_status(
        [GMAIL_INTEGRATION_ID, GOOGLE_CALENDAR_INTEGRATION_ID], user.id
    )
    return all(statuses.values())


async def uses_todos(user: UserDocument) -> bool:
    """True once the user has enough todos to count as using the feature."""
    return await todo_repository.count_for_user(user.id) >= _TODOS_IN_USE_THRESHOLD


async def has_workflow(user: UserDocument) -> bool:
    """True once the user has at least one workflow (auto-generated todo
    workflows included — their presence still signals the feature is in play)."""
    return await workflow_repository.count_for_user(user.id, exclude_todo_workflows=False) > 0


# Async without await is intentional: uniform SKIP_PREDICATES interface (see module docstring).
async def linked_platform(user: UserDocument) -> bool:  # NOSONAR python:S7503
    """True once the user linked any chat platform (WhatsApp/Telegram/Slack/Discord)."""
    links = user.platform_links or {}
    return any(isinstance(link, dict) and link.get("id") for link in links.values())


SKIP_PREDICATES: Mapping[str, Callable[[UserDocument], Awaitable[bool]]] = {
    "onboarding_completed": onboarding_completed,
    "used_chat": used_chat,
    "google_suite_connected": google_suite_connected,
    "uses_todos": uses_todos,
    "has_workflow": has_workflow,
    "linked_platform": linked_platform,
}
