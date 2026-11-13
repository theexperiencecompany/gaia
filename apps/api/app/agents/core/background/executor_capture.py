"""Shared lifecycle for capturing background-executor tool events.

The executor runs as a detached asyncio task (spawned by call_executor).
Its tool events, and those of any subagent it spawns, are appended to
the stream's StreamSession.tool_events by make_redis_stream_writer.

Both the live chat path and the silent path (workflows, background tasks)
register the session, wait for the executor, drain the collected events into
grouped tool_data, and tear it down. Centralizing it here keeps one
implementation so chat and workflow runs render identically.
"""

import asyncio
from pathlib import Path
from types import CoroutineType, FrameType

from app.agents.core.background.session import (
    RunKind,
    create_session,
    get_session,
    teardown_session,
)
from app.constants.cache import EXECUTOR_WAIT_TIMEOUT
from app.constants.log_tags import LogTag
from app.models.chat_models import ToolDataEntry
from app.services.chat.chunks import normalize_custom_event
from app.utils.stream_utils import (
    ToolDataEnvelope,
    absorb_collector_event,
    apply_outputs_to_tool_data,
    reconstruct_subagent_groups,
)
from shared.py.wide_events import log


def register_executor_capture(stream_id: str) -> asyncio.Event:
    """Register the stream session that captures executor tool events.

    Must run before the comms agent executes so call_executor's background
    task can append events to the session. Returns the done-event.
    """
    return create_session(stream_id, RunKind.LIVE).done_event


# The timeout cannot move to callers: this function owns the graceful
# catch-and-drain semantics (log + return so collected events still flush).
async def await_executor_done(
    stream_id: str,
    timeout: float = EXECUTOR_WAIT_TIMEOUT,  # NOSONAR python:S7483
) -> bool:
    """Block until the background executor for this stream signals completion.

    True when it finished (or none was spawned). On timeout only the waiting
    stops: the tasks still running are logged so the stall can be read, False
    comes back so the caller can drain what was collected, and the executor
    goes on to deliver its result as a message of its own.
    """
    session = get_session(stream_id)
    if session is None or not session.executor_spawned:
        return True
    log.info(f"{LogTag.AGENT} Waiting for executor completion", stream_id=stream_id)
    try:
        async with asyncio.timeout(timeout):
            await session.done_event.wait()
    except TimeoutError:
        log.error(
            f"{LogTag.AGENT} Timed out waiting for executor; draining what it produced",
            stream_id=stream_id,
            timeout_seconds=int(timeout),
            stuck_tasks=_running_task_stacks(),
        )
        return False
    return True


#: Tasks worth naming when the executor stalls: the executor's own run and
#: the subagent runs it dispatched. Everything else is the loop's plumbing.
_AGENT_TASK_MARKERS = ("run_executor", "run_subagent")
_STACK_FRAMES = 6


def _running_task_stacks() -> list[str]:
    """One line per agent task still running, with its innermost frames.

    A thread dump shows only the idle event loop; the stall is in a coroutine,
    and this is the only view of where it sits.
    """
    return [
        f"{name}: {_innermost_frames(task)}"
        for task in asyncio.all_tasks()
        if not task.done() and (name := _agent_task_name(task)) is not None
    ]


def _agent_task_name(task: asyncio.Task[object]) -> str | None:
    """Return the task's coroutine name when it is an agent run, else None."""
    coro = task.get_coro()
    name = getattr(coro, "__qualname__", type(coro).__name__)
    return name if any(marker in name for marker in _AGENT_TASK_MARKERS) else None


def _innermost_frames(task: asyncio.Task[object]) -> str:
    """Where the task is suspended, innermost await first.

    Task.get_stack stops at the task's own coroutine; the stall is down the
    chain of awaits, so the chain is walked to its end and its tail kept.
    """
    frames: list[FrameType] = []
    coro: object = task.get_coro()
    while isinstance(coro, CoroutineType) and coro.cr_frame is not None:
        frames.append(coro.cr_frame)
        coro = coro.cr_await
    return " <- ".join(
        f"{frame.f_code.co_name}({Path(frame.f_code.co_filename).name}:{frame.f_lineno})"
        for frame in reversed(frames[-_STACK_FRAMES:])
    )


def drain_executor_tool_data(stream_id: str) -> list[ToolDataEntry]:
    """Drain the session's tool events into reconstructed tool_data.

    Non-destructive read. Mirrors the comms-graph accumulation path:
    tool_calls_data outputs are merged in, and subagent start/end pairs are
    grouped via reconstruct_subagent_groups. Only tool_calls_data entries
    get their output backfilled.
    """
    session = get_session(stream_id)
    if session is None or not session.tool_events:
        return []
    entries: list[ToolDataEntry] = []
    # The accumulator envelope is an open bag; only "tool_data" has a fixed
    # shape, and it's this list object throughout, rebound by
    # reconstruct_subagent_groups, hence the re-read at the end.
    accumulated: dict[str, object] = {"tool_data": entries}
    outputs: dict[str, str] = {}
    for evt in session.tool_events:
        # Hooks emit raw field payloads like {"email_fetch_data": [...]};
        # normalize to {"tool_data": {...}} or absorb_collector_event drops
        # them and the list card never persists.
        absorb_collector_event(normalize_custom_event(evt), accumulated, outputs)
    apply_outputs_to_tool_data(entries, outputs, only_tool_name="tool_calls_data")
    reconstruct_subagent_groups(accumulated)
    return ToolDataEnvelope.model_validate(accumulated).tool_data


def teardown_executor_capture(stream_id: str) -> None:
    """Drop the stream's session and everything it holds.

    Safe to call multiple times.
    """
    teardown_session(stream_id)
