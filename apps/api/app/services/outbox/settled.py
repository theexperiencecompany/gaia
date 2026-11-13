"""Telling an app how a run's report ended, for the status chip of the turn that started it.

The chip waits on the run, not on words: a report that is told on a chat app, recorded without
an alert, or fails delivers no message to the conversation, and the chip must still settle. A turn
can start several runs, so each run's outcome is kept on the turn's message under its own report id.
"""

from collections.abc import Iterable

from app.constants.log_tags import LogTag
from app.constants.websocket import ReportSettledOutcome
from app.db.repositories.conversations import conversation_repository
from app.db.repositories.outbox_items import outbox_items_repository
from app.models.chat_models import WorkRunOutcome
from app.models.outbox_models import OutboxItemDocument
from app.services.outbox.models import OutboxReport, RunReport
from app.services.outbox.transport.ws_speech import publish_report_settled
from shared.py.wide_events import log


async def announce_settled(report: OutboxReport, outcome: ReportSettledOutcome) -> None:
    """Record how a report ended on the turn whose chip waits on it and tell the user's open clients; nothing when no turn waits."""
    if not isinstance(report, RunReport) or report.turn_message_id is None:
        return
    conversation_id = report.subject.owner_conversation_id
    if conversation_id is None:
        return
    saved = await conversation_repository.record_work_outcome(
        conversation_id,
        user_id=report.recipient,
        message_id=report.turn_message_id,
        run=WorkRunOutcome(report_id=report.report_id, outcome=outcome),
    )
    if not saved:
        log.error(
            f"{LogTag.NOTIFICATION} Settled run names a turn its conversation does not hold",
            report_id=report.report_id,
            conversation_id=conversation_id,
            turn_message_id=report.turn_message_id,
        )
    await publish_report_settled(
        report.recipient, conversation_id, report.turn_message_id, report.report_id, outcome
    )


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
