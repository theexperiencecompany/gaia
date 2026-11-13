"""The work-state block: what is going on for the user beside this chat, as comms reads it each turn.

Comms does no work itself, so without this it cannot tell "still running" from "finished and not
yet told", nor answer "what did you tell me earlier". Everything here is labels in the user's
words: no ids, tool names, inputs or product machinery, so nothing in it can leak into a reply.
"""

import asyncio
from datetime import UTC, datetime, timedelta

from app.agents.context.live_work import build_executor_status_block
from app.agents.context.section_context import SectionContext
from app.constants.log_tags import LogTag
from app.constants.todos import WaitingOn
from app.constants.work_state import (
    WORK_STATE_LIST_MAX,
    WORK_STATE_TOLD_ELSEWHERE_MAX,
    WORK_STATE_TOLD_ELSEWHERE_WINDOW_SECONDS,
    WORK_STATE_TOLD_EXCERPT_CHARS,
)
from app.db.repositories.approval_ledger import approval_ledger_repository
from app.db.repositories.outbox_items import outbox_items_repository
from app.db.repositories.outbox_messages import outbox_messages_repository
from app.db.repositories.todos import todo_repository
from app.models.hil_models import ApprovalLedgerDocument, LedgerState
from app.models.todo_models import TodoDocument
from app.services.outbox.models import ItemState, NoticeReport, OutboxReport, RunReport
from shared.py.wide_events import log

_UNTOLD_STATE_TEXT = {
    ItemState.RECEIVED: "finished, not told yet",
    ItemState.QUEUED: "finished, waiting for a good moment to tell",
}


def _outcome_of(report: OutboxReport) -> str:
    match report:
        case RunReport(report=task_report):
            return task_report.outcome.value if task_report.outcome else ""
        case NoticeReport(outcome=outcome):
            return outcome.value


def _bulleted(heading: str, lines: list[str]) -> str:
    return "\n".join([heading, *(f"- {line}" for line in lines)]) if lines else ""


def _ongoing_follow_ups(todos: list[TodoDocument]) -> list[str]:
    return [todo.title for todo in todos if todo.waiting_on is not WaitingOn.USER][
        :WORK_STATE_LIST_MAX
    ]


def _waiting_on_user(
    todos: list[TodoDocument], approvals: list[ApprovalLedgerDocument]
) -> list[str]:
    undecided = [a.summary for a in approvals if a.state is LedgerState.PENDING]
    asks = [f"{todo.title}: {todo.question}" for todo in todos if todo.waiting_on is WaitingOn.USER]
    return [*undecided, *asks][:WORK_STATE_LIST_MAX]


async def _untold_results(user_id: str) -> list[str]:
    items = await outbox_items_repository.list_unsettled(user_id, limit=WORK_STATE_LIST_MAX)
    return [
        f"{item.report.subject.label} ({_outcome_of(item.report)}): {_UNTOLD_STATE_TEXT[item.state]}"
        for item in items
    ]


async def _told_elsewhere(user_id: str, conversation_id: str, now: datetime) -> list[str]:
    """Return what GAIA recently told the user on another surface, numbered so they can refer to one."""
    since = now - timedelta(seconds=WORK_STATE_TOLD_ELSEWHERE_WINDOW_SECONDS)
    sent = await outbox_messages_repository.sent_since(
        user_id, since, limit=WORK_STATE_LIST_MAX * 4
    )
    elsewhere = [m for m in sent if conversation_id not in m.recorded_in]
    return [
        f"{ordinal}. {' '.join(message.parts)[:WORK_STATE_TOLD_EXCERPT_CHARS]}"
        for ordinal, message in enumerate(elsewhere[:WORK_STATE_TOLD_ELSEWHERE_MAX], start=1)
    ]


async def build_work_state_block(ctx: SectionContext) -> str:
    """Return the work-state block: the chat's running work, then, on an interactive turn, the user's wider picture.

    A background turn has nobody to answer, so it gets the running state alone. A source that
    cannot be read is logged and left out; the turn never fails over context.
    """
    running = await build_executor_status_block(ctx)
    if ctx.execution_mode == "background" or not ctx.user_id or not ctx.conversation_id:
        return running
    user_id, conversation_id = ctx.user_id, ctx.conversation_id
    try:
        todos, approvals, untold, told = await asyncio.gather(
            todo_repository.find_running_tracked_for_user(user_id),
            approval_ledger_repository.list_open(conversation_id),
            _untold_results(user_id),
            _told_elsewhere(user_id, conversation_id, datetime.now(UTC)),
        )
    except Exception as e:
        log.error(
            f"{LogTag.AGENT} Work state unavailable beyond this chat",
            error_type=type(e).__name__,
            error=str(e),
        )
        return running
    sections = [
        running,
        _bulleted("Ongoing follow-ups you keep for them:", _ongoing_follow_ups(todos)),
        _bulleted("Waiting on the user:", _waiting_on_user(todos, approvals)),
        _bulleted("Results the user has not been told yet:", untold),
        "\n".join(["Told on another surface recently:", *told]) if told else "",
    ]
    return "\n\n".join(section for section in sections if section)
