"""Write the trace of an executor run: its state, one record per tool call, and the todo's activity lines.

A run is owned by a tracked todo when it ran on one (its calls then also reach the todo's
activity log), else it is a hidden record keyed by its conversation and run id. Nothing
here is decided by a model: the owner comes from the run's configurable and the effect of
a call from the tool registry.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import json
from uuid import uuid4

from langchain_core.runnables import RunnableConfig
from pymongo.errors import PyMongoError

from app.agents.core.background.executor_queue import parse_lock_value, read_executor_activity
from app.agents.tools.core.registry import get_tool_registry
from app.constants.agents import COMMS_AGENT_NAME
from app.constants.log_tags import LogTag
from app.constants.run_trace import (
    CALL_PAYLOAD_MAX_CHARS,
    CALL_SUMMARY_MAX_CHARS,
    RUN_ABANDONED_AFTER_SECONDS,
    RUN_REAP_BATCH_LIMIT,
)
from app.constants.todos import TodoActivityEvent
from app.db.repositories.run_traces import (
    call_payload_repository,
    run_call_repository,
    run_repository,
)
from app.models.agent_config import read_agent_configurable
from app.models.executor_activity_models import ExecutorActivity
from app.models.run_trace_models import (
    CallEffect,
    CallPayloadDocument,
    CallStatus,
    RunCallDocument,
    RunDocument,
    RunState,
    RunUpdate,
)
from app.services.executor_trace.metrics import TraceWrite, count_trace_write_failed
from app.services.todo_activity import activity_line
from app.services.todo_canvas_storage import append_activity
from shared.py.wide_events import log

#: Longest a single argument value may run in a call's one-line summary.
_SUMMARY_VALUE_MAX_CHARS = 40
_ELLIPSIS = "..."
#: States a run can end in; a paused run has not ended.
_ENDED_STATES = frozenset({RunState.FINISHED, RunState.FAILED, RunState.CANCELLED})


@dataclass(frozen=True, slots=True)
class RunOwner:
    """Whose trace a run belongs to: the user and conversation, the run, and its todo when it has one."""

    user_id: str
    conversation_id: str
    run_id: str
    todo_id: str | None = None
    #: The run that dispatched this one (a background subagent's executor); None for a top-level run.
    parent_run_id: str | None = None

    @classmethod
    def of(
        cls,
        *,
        user_id: str | None,
        conversation_id: str | None,
        run_id: str | None,
        todo_id: str | None,
        parent_run_id: str | None = None,
    ) -> "RunOwner | None":
        """Return the owner, or None when the run has no user, conversation or id to key a trace by."""
        if not user_id or not conversation_id or not run_id:
            return None
        return cls(user_id, conversation_id, run_id, todo_id, parent_run_id)

    @classmethod
    def from_config(cls, config: RunnableConfig | None) -> "RunOwner | None":
        """Return the owner of the executor-tree run a call belongs to, or None when it belongs to none.

        The comms tier has no work tools and its calls are never a run's; a call with no
        stream, user or conversation (a bare lookup) belongs to no run either.
        """
        view = read_agent_configurable(config)
        if view.agent_name == COMMS_AGENT_NAME:
            return None
        return cls.of(
            user_id=view.user_id,
            conversation_id=view.conversation_id,
            run_id=view.stream_id,
            todo_id=view.active_todo_id,
        )


@dataclass(frozen=True, slots=True)
class TracedCall:
    """A finished tool call, as the invocation layer saw it."""

    tool_name: str
    tool_call_id: str | None
    args: dict[str, object]
    output_text: str
    failed: bool
    started_at: datetime
    finished_at: datetime


async def begin_run(owner: RunOwner) -> None:
    """Open the run, or reopen a paused one that resumed, as running; a store failure is logged, not raised."""
    try:
        await run_repository.open_run(
            _run_document(owner, datetime.now(UTC)), state=RunState.RUNNING
        )
    except PyMongoError as exc:
        # The run itself carries on untraced; raising would fail work the user asked for.
        _log_unrecorded(TraceWrite.RUN_START, owner, exc)


async def end_run(owner: RunOwner, state: RunState) -> None:
    """Move the run to the state it stopped in and put its calls in its todo's activity log."""
    now = datetime.now(UTC)
    try:
        ended = await run_repository.update(
            owner.run_id,
            user_id=owner.user_id,
            update=RunUpdate(
                state=state,
                last_activity_at=now,
                **({"finished_at": now} if state in _ENDED_STATES else {}),
            ),
        )
        if ended is not None:
            await flush_activity(ended)
    except PyMongoError as exc:
        _log_unrecorded(TraceWrite.RUN_END, owner, exc)


async def record_call(owner: RunOwner, call: TracedCall) -> None:
    """Store one finished call: its input and output in the payload collection, its record behind a reference."""
    registry = await get_tool_registry()
    effect = (
        CallEffect.READ
        if registry.is_tool_destructive(call.tool_name) is False
        else CallEffect.WRITE
    )
    input_json = json.dumps(call.args, default=str, ensure_ascii=False)
    truncated = max(len(input_json), len(call.output_text)) > CALL_PAYLOAD_MAX_CHARS
    await run_repository.open_run(_run_document(owner, call.started_at))
    payload = await call_payload_repository.create(
        CallPayloadDocument(
            user_id=owner.user_id,
            input_json=input_json[:CALL_PAYLOAD_MAX_CHARS],
            output_text=call.output_text[:CALL_PAYLOAD_MAX_CHARS],
            truncated=truncated,
        )
    )
    await run_call_repository.create(
        RunCallDocument(
            user_id=owner.user_id,
            run_id=owner.run_id,
            call_id=uuid4().hex,
            tool_call_id=call.tool_call_id,
            tool_name=call.tool_name,
            effect=effect,
            status=CallStatus.ERROR if call.failed else CallStatus.OK,
            started_at=call.started_at,
            finished_at=call.finished_at,
            summary=summarize_call(call),
            payload_ref=payload.id,
        )
    )


def summarize_call(call: TracedCall) -> str:
    """Describe a call in one short line from its arguments, and from its error when it failed."""
    parts = [f"{key}={_short(value)}" for key, value in call.args.items()]
    summary = ", ".join(parts)
    if call.failed:
        summary = (
            f"{_first_line(call.output_text)} ({summary})"
            if summary
            else _first_line(call.output_text)
        )
    if len(summary) <= CALL_SUMMARY_MAX_CHARS:
        return summary
    return summary[: CALL_SUMMARY_MAX_CHARS - len(_ELLIPSIS)] + _ELLIPSIS


async def flush_activity(run: RunDocument) -> int:
    """Append one activity line per call not yet logged to the run's todo; return how many.

    Written in one append when the run stops, not per call: every append re-embeds the
    todo's canvas and activity for search.
    """
    if run.todo_id is None:
        return 0
    calls = await run_call_repository.list_finished_after(
        run.user_id, run.run_id, run.activity_logged_through
    )
    if not calls:
        return 0
    lines = [
        activity_line(
            TodoActivityEvent.TOOL_CALLED,
            f"{call.effect.value} {call.tool_name} {call.status.value}: {call.summary}",
            at=call.finished_at,
        )
        for call in calls
    ]
    if not await append_activity(run.todo_id, run.user_id, "\n".join(lines)):
        return 0
    await run_repository.update(
        run.run_id,
        user_id=run.user_id,
        update=RunUpdate(activity_logged_through=calls[-1].finished_at),
    )
    return len(calls)


async def reap_abandoned_runs(now: datetime | None = None) -> int:
    """Mark every run left running past the timeout, with no live executor behind it, abandoned.

    A run is alive while it holds its conversation's executor busy lock, whose liveness
    the executor renews; only a run past the timeout that holds nothing is closed.
    Returns how many this sweep closed.
    """
    at = now or datetime.now(UTC)
    cutoff = at - timedelta(seconds=RUN_ABANDONED_AFTER_SECONDS)
    stale = await run_repository.list_stale_running(cutoff, limit=RUN_REAP_BATCH_LIMIT)
    closed = 0
    for run in stale:
        if await _holds_live_executor(run):
            continue
        abandoned = await run_repository.abandon_if_stale(run.run_id, run.user_id, cutoff, at=at)
        if abandoned is None:
            continue
        log.warning(
            f"{LogTag.AGENT} Executor run abandoned: no activity and no live executor",
            run_id=run.run_id,
            conversation_id=run.conversation_id,
            last_activity_at=run.last_activity_at.isoformat(),
        )
        await flush_activity(abandoned)
        closed += 1
    return closed


async def _holds_live_executor(run: RunDocument) -> bool:
    """Whether the run's conversation busy lock is held, and kept alive, by this very run."""
    snapshot = await read_executor_activity(run.conversation_id)
    if snapshot.activity is not ExecutorActivity.RUNNING:
        return False
    return parse_lock_value(snapshot.holder)[0] == run.run_id


def _run_document(owner: RunOwner, at: datetime) -> RunDocument:
    return RunDocument(
        user_id=owner.user_id,
        run_id=owner.run_id,
        conversation_id=owner.conversation_id,
        todo_id=owner.todo_id,
        parent_run_id=owner.parent_run_id,
        state=RunState.RUNNING,
        started_at=at,
        last_activity_at=at,
    )


def _short(value: object) -> str:
    """Render one argument value on one line: a scalar cut short, a container as its type."""
    if isinstance(value, str | int | float | bool) or value is None:
        text = " ".join(str(value).split())
        if len(text) <= _SUMMARY_VALUE_MAX_CHARS:
            return text
        return text[: _SUMMARY_VALUE_MAX_CHARS - len(_ELLIPSIS)] + _ELLIPSIS
    return type(value).__name__


def _first_line(text: str) -> str:
    return text.strip().splitlines()[0] if text.strip() else ""


def _log_unrecorded(write: TraceWrite, owner: RunOwner, exc: PyMongoError) -> None:
    count_trace_write_failed(write)
    log.error(
        f"{LogTag.AGENT} Run trace: a state change was not recorded",
        change=write.value,
        run_id=owner.run_id,
        conversation_id=owner.conversation_id,
        error_type=type(exc).__name__,
        exc_info=True,
    )
