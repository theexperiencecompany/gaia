"""Comms' read-only view of what its background work did, so "what exactly did you send?" needs no re-run."""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Annotated, Literal

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from app.agents.tools.task_record import latest_run_report, render_task_report
from app.constants.outbox import TODO_REPORT_PREFIX
from app.constants.run_trace import (
    WORK_RECORD_CALLS_PER_RUN,
    WORK_RECORD_DETAIL_CHARS,
    WORK_RECORD_RUNS,
    WORK_RECORD_SEARCH_RUNS,
)
from app.db.repositories.outbox_items import outbox_items_repository
from app.db.repositories.todos import todo_repository
from app.models.agent_config import get_user_id, read_agent_configurable
from app.models.run_trace_models import RunCallDocument, RunDocument
from app.services.analytics_service import capture
from app.services.executor_trace.reader import (
    CallDetail,
    get_call_detail,
    list_conversation_runs,
    list_run_calls,
    list_todo_runs,
)
from shared.py.analytics import UserId
from shared.py.analytics.catalog.tasks import TaskRead

NO_CONVERSATION = "No conversation context available."
NO_WORK_RECORDED = "No work has been recorded for this conversation."


def _call_line(call: RunCallDocument) -> str:
    return (
        f"[{call.call_id}] {call.effect.value} {call.tool_name} {call.status.value}: {call.summary}"
    )


async def _run_block(user_id: str, run: RunDocument) -> str:
    calls = await list_run_calls(user_id, run.run_id, limit=WORK_RECORD_CALLS_PER_RUN)
    header = f"Run {run.state.value}, started {run.started_at.isoformat(timespec='minutes')}:"
    return "\n".join([header, *(_call_line(call) for call in calls)])


def _detail_text(detail: CallDetail) -> str:
    cut = WORK_RECORD_DETAIL_CHARS
    clipped = len(detail.input_json) > cut or len(detail.output_text) > cut or detail.truncated
    text = (
        f"{_call_line(detail.call)}\n"
        f"Input:\n{detail.input_json[:cut]}\n"
        f"Output:\n{detail.output_text[:cut]}"
    )
    return f"{text}\n(cut: the stored call was longer)" if clipped else text


async def _find_call(user_id: str, runs: Sequence[RunDocument], call_id: str) -> CallDetail | None:
    for run in runs:
        if (detail := await get_call_detail(user_id, run.run_id, call_id)) is not None:
            return detail
    return None


@tool
async def read_work_record(config: RunnableConfig, call_id: str | None = None) -> str:
    """Read what GAIA's background work actually did in this conversation, for questions about it.

    Use it when the user asks what exactly was sent, written, found or changed, whether you are
    sure, or before they act on money, time or a send. Without call_id it lists the latest runs and
    their calls, each with its id. With a call_id from that list it returns that call's full input
    and output. Answer by quoting what it shows, never by guessing. Read-only; it never acts, and
    nothing in it is for the user's eyes as written: say what happened, never the tool names or ids.
    """
    conversation_id = read_agent_configurable(config).thread_id
    if not conversation_id:
        return NO_CONVERSATION
    user_id = get_user_id(config)
    if call_id is not None:
        runs = await list_conversation_runs(user_id, conversation_id, limit=WORK_RECORD_SEARCH_RUNS)
        detail = await _find_call(user_id, runs, call_id)
        return _detail_text(detail) if detail else f"No call {call_id} is recorded here."
    runs = await list_conversation_runs(user_id, conversation_id, limit=WORK_RECORD_RUNS)
    if not runs:
        return NO_WORK_RECORDED
    return "\n\n".join([await _run_block(user_id, run) for run in runs])


@tool
async def read_task(
    config: RunnableConfig,
    task_id: str,
    level: Annotated[
        Literal["report", "trace"],
        "report: the task's state and what its latest run reported, with its age. trace: the "
        "run's stored calls, for what exactly was said, sent or found.",
    ] = "report",
    call_id: str | None = None,
) -> str:
    """Read what a task did, to answer a follow-up about it without running it again.

    report is the first look: state, the latest report's facts and how old they are. trace is the
    second: with level trace it lists the latest runs' calls, each with its id; with a call_id
    from that list it returns that call's full input and output. Answer by quoting what it shows,
    never by guessing. Read-only; nothing in it is for the user's eyes as written: say what
    happened, never the tool names or ids.
    """
    user_id = get_user_id(config)
    task = await todo_repository.get(task_id, user_id=user_id)
    if task is None:
        return f"You have no task {task_id}. Find it with find_tasks."
    now = datetime.now(UTC)
    cross_conversation = task.source_conversation_id != read_agent_configurable(config).thread_id
    if level == "report":
        items = await outbox_items_repository.list_of_series(
            user_id, f"{TODO_REPORT_PREFIX}{task_id}", limit=WORK_RECORD_RUNS
        )
        run = latest_run_report(items)
        age = int((now - run.occurred_at).total_seconds()) if run else None
        capture(
            UserId(user_id),
            TaskRead(level="report", cross_conversation=cross_conversation, report_age_seconds=age),
        )
        return render_task_report(task, items, now)
    runs = await list_todo_runs(user_id, task_id, limit=WORK_RECORD_SEARCH_RUNS)
    capture(UserId(user_id), TaskRead(level="trace", cross_conversation=cross_conversation))
    if call_id is not None:
        detail = await _find_call(user_id, runs, call_id)
        return _detail_text(detail) if detail else f"No call {call_id} is recorded for this task."
    if not runs:
        return "No run of this task has been recorded."
    return "\n\n".join([await _run_block(user_id, run) for run in runs[:WORK_RECORD_RUNS]])
