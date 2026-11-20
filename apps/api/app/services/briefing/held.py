"""Results held for the daily brief: whether one may wait, and the release when none will run.

A result waits only while a daily brief will run to carry it. The weekly digest zooms out
on the week and carries no held items, so a user whose daily brief will not run (weekly
only, briefs off, switched off, wound down or backing off a winback) is
sent each result now, and whatever was held when the loop stops is released at once, in
the app.
"""

from collections.abc import Collection, Iterable
from dataclasses import dataclass

from app.constants.briefing import (
    DAILY_BRIEFING_WORKFLOW_KEY,
    HELD_RELEASE_TITLE,
    BriefingRunOutcome,
    BriefItemSource,
)
from app.constants.workflows import WorkflowDelivery
from app.db.repositories.briefing_state import briefing_state_repository
from app.db.repositories.pending_brief_items import pending_brief_items_repository
from app.db.repositories.users import user_repository
from app.db.repositories.workflows import workflow_repository
from app.models.brief_models import PendingBriefItemDocument
from app.models.notification.notification_models import (
    NotificationContent,
    NotificationRequest,
    NotificationSourceEnum,
)
from app.services.briefing import wind_down
from app.services.briefing.formats import opening_line
from app.services.briefing.lookback import compute_winback_state
from app.services.notification_service import notification_service
from shared.py.wide_events import log


async def brief_will_carry(user_id: str) -> bool:
    """Whether a daily brief will run to carry a held result.

    Not while its workflow is off, the loop is wound down, or a winback is backing off: each run skips before it reads the held.
    """
    workflow = await workflow_repository.find_system_workflow(user_id, DAILY_BRIEFING_WORKFLOW_KEY)
    if workflow is None or not workflow.activated:
        return False
    user = await user_repository.get(user_id)
    if user is None:
        raise LookupError(f"Daily brief workflow {workflow.id} belongs to no user {user_id}")
    state = await briefing_state_repository.state_for(user_id)
    if await wind_down.is_wound_down(state):
        return False
    return not (await compute_winback_state(user)).should_back_off


async def release_after_daily_run(user_id: str, outcome: BriefingRunOutcome) -> None:
    """Release what is held once a daily run leaves it behind: gone silent, or no brief will carry it."""
    if outcome is BriefingRunOutcome.SILENT or not await brief_will_carry(user_id):
        await release_held_items(user_id)


@dataclass(frozen=True, slots=True)
class HeldSource:
    """What a held result came from: the workflow or todo that ran, and the conversation of the run."""

    kind: BriefItemSource
    id: str
    title: str
    conversation_id: str


async def hold_for_brief(user_id: str, source: HeldSource, texts: Iterable[str]) -> None:
    """Hold each non-blank text as one item of the user's next daily brief.

    The caller has checked brief_will_carry. A retry that holds a text twice is harmless:
    the brief carries one item per text.
    """
    for text in texts:
        if stripped := text.strip():
            await pending_brief_items_repository.create(
                PendingBriefItemDocument(
                    user_id=user_id,
                    source=source.kind,
                    source_id=source.id,
                    source_title=source.title,
                    conversation_id=source.conversation_id,
                    text=stripped,
                )
            )


async def held_items(user_id: str) -> list[PendingBriefItemDocument]:
    """Return what is held for the user's next daily brief, oldest first."""
    return await pending_brief_items_repository.list_for_user(user_id, sort=[("created_at", 1)])


def held_text(doc: PendingBriefItemDocument) -> str:
    """One line for a held result: where it came from and its report's first line, all of it ever shown."""
    first = opening_line(doc.text)
    return f"{doc.source_title}: {first}" if first else doc.source_title


async def release_held_items(user_id: str, *, source_ids: Collection[str] | None = None) -> None:
    """Send what is held (only what source_ids held, when given) as one notification now; clear it."""
    held = [
        doc
        for doc in await held_items(user_id)
        if source_ids is None or doc.source_id in source_ids
    ]
    if not held:
        return
    await notification_service.create_notification(
        NotificationRequest(
            user_id=user_id,
            source=NotificationSourceEnum.BACKGROUND_JOB,
            content=NotificationContent(
                title=HELD_RELEASE_TITLE, body="\n".join(held_text(doc) for doc in held)
            ),
        )
    )
    released = await pending_brief_items_repository.consume(user_id, [doc.id for doc in held])
    log.info("briefing.held_items_released", user_id=user_id, released=released)


async def release_on_tell_me_now(
    user_id: str, source_ids: Collection[str], delivery: WorkflowDelivery | None
) -> None:
    """Send what the workflows or todos held for the brief once their delivery moves to now."""
    if delivery is WorkflowDelivery.NOW:
        await release_held_items(user_id, source_ids=source_ids)
