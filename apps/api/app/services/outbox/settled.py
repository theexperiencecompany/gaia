"""Telling an app how a run's report ended, for the status chip of the turn that started it.

The chip waits on the run, not on words: a report that is told on a chat app, recorded without
an alert, or fails delivers no message to the conversation, and the chip must still settle.
"""

from collections.abc import Iterable

from app.constants.websocket import ReportSettledOutcome
from app.db.repositories.outbox_items import outbox_items_repository
from app.models.outbox_models import OutboxItemDocument
from app.services.outbox.models import OutboxReport, RunReport
from app.services.outbox.transport.ws_speech import publish_report_settled


async def announce_settled(report: OutboxReport, outcome: ReportSettledOutcome) -> None:
    """Tell the user's open clients how a report ended; nothing when no turn's chip waits on it."""
    if not isinstance(report, RunReport) or report.turn_message_id is None:
        return
    conversation_id = report.subject.owner_conversation_id
    if conversation_id is None:
        return
    await publish_report_settled(report.recipient, conversation_id, report.turn_message_id, outcome)


async def announce_items_settled(
    items: Iterable[OutboxItemDocument], outcome: ReportSettledOutcome
) -> None:
    """Tell how each of the items' reports ended."""
    for item in items:
        await announce_settled(item.report, outcome)


async def announce_attempt_settled(
    user_id: str, attempt_id: str, outcome: ReportSettledOutcome
) -> None:
    """Tell how the reports of one compose attempt ended."""
    await announce_items_settled(
        await outbox_items_repository.list_of_attempt(user_id, attempt_id), outcome
    )
