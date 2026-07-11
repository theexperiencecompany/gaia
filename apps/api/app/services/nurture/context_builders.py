"""Per-step template context builders.

Run after the skip predicate passes, so a step's copy can adapt to what the
user has already set up. Returned keys merge over the engine's base context,
so a builder may also override cta_label.
"""

from collections.abc import Awaitable, Callable

from app.constants.integrations import GMAIL_INTEGRATION_ID, GOOGLE_CALENDAR_INTEGRATION_ID
from app.services.oauth.oauth_service import check_multiple_integrations_status


async def google_connection_status(user: dict) -> dict:
    statuses = await check_multiple_integrations_status(
        [GMAIL_INTEGRATION_ID, GOOGLE_CALENDAR_INTEGRATION_ID], str(user["_id"])
    )
    gmail = statuses[GMAIL_INTEGRATION_ID]
    calendar = statuses[GOOGLE_CALENDAR_INTEGRATION_ID]
    context: dict = {"gmail_connected": gmail, "calendar_connected": calendar}
    if gmail and not calendar:
        context["cta_label"] = "Connect Google Calendar"
    elif calendar and not gmail:
        context["cta_label"] = "Connect Gmail"
    return context


CONTEXT_BUILDERS: dict[str, Callable[[dict], Awaitable[dict]]] = {
    "google_connection_status": google_connection_status,
}
