"""Results held for the daily brief: whether one may wait, and the release when none will run.

A result waits only while a daily brief will run to carry it. The weekly digest zooms out
on the week and carries no held items, so a user without a live daily brief (weekly
only, briefs off, or a daily switched off) is sent each result now, and moving off the
daily brief releases everything it was holding, at once, in the app.
"""

from app.constants.briefing import DAILY_BRIEFING_WORKFLOW_KEY, HELD_SECTION_TITLE
from app.db.repositories.pending_brief_items import pending_brief_items_repository
from app.db.repositories.workflows import workflow_repository
from app.models.brief_models import PendingBriefItemDocument
from app.models.notification.notification_models import (
    NotificationContent,
    NotificationRequest,
    NotificationSourceEnum,
)
from app.services.notification_service import notification_service
from shared.py.wide_events import log


async def daily_brief_is_live(user_id: str) -> bool:
    """Whether a daily brief will run for the user: its workflow exists and is switched on."""
    workflow = await workflow_repository.find_system_workflow(user_id, DAILY_BRIEFING_WORKFLOW_KEY)
    return workflow is not None and workflow.activated


async def held_items(user_id: str) -> list[PendingBriefItemDocument]:
    """Return what is held for the user's next daily brief, oldest first."""
    return await pending_brief_items_repository.list_for_user(user_id, sort=[("created_at", 1)])


def held_text(doc: PendingBriefItemDocument) -> str:
    """One line for a held result: where it came from and its report's first line."""
    first_line = next((line.strip() for line in doc.text.splitlines() if line.strip()), "")
    return f"{doc.source_title}: {first_line}"


async def release_held_items(user_id: str) -> None:
    """Send everything held as one in-app notification now, and clear it."""
    held = await held_items(user_id)
    if not held:
        return
    await notification_service.create_notification(
        NotificationRequest(
            user_id=user_id,
            source=NotificationSourceEnum.BACKGROUND_JOB,
            content=NotificationContent(
                title=HELD_SECTION_TITLE, body="\n".join(held_text(doc) for doc in held)
            ),
        )
    )
    released = await pending_brief_items_repository.consume(user_id, [doc.id for doc in held])
    log.info("briefing.held_items_released", user_id=user_id, released=released)
