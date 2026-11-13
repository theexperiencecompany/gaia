"""Comms' read-only view of what its background work did, so "what exactly did you send?" needs no re-run."""

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from app.constants.run_trace import (
    WORK_RECORD_CALLS_PER_RUN,
    WORK_RECORD_DETAIL_CHARS,
    WORK_RECORD_RUNS,
    WORK_RECORD_SEARCH_RUNS,
)
from app.models.agent_config import get_user_id, read_agent_configurable
from app.models.run_trace_models import RunCallDocument, RunDocument
from app.services.executor_trace.reader import (
    CallDetail,
    get_call_detail,
    list_conversation_runs,
    list_run_calls,
)

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


async def _find_call(user_id: str, conversation_id: str, call_id: str) -> CallDetail | None:
    runs = await list_conversation_runs(user_id, conversation_id, limit=WORK_RECORD_SEARCH_RUNS)
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
        detail = await _find_call(user_id, conversation_id, call_id)
        return _detail_text(detail) if detail else f"No call {call_id} is recorded here."
    runs = await list_conversation_runs(user_id, conversation_id, limit=WORK_RECORD_RUNS)
    if not runs:
        return NO_WORK_RECORDED
    return "\n\n".join([await _run_block(user_id, run) for run in runs])
