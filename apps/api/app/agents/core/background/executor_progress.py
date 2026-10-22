"""What a running executor has done so far, kept for comms to read while it runs.

Pull, not push: nothing here reaches the conversation as a message, so the
run's final result stays its only answer. The record is part of the busy-lock
holder's state, keyed by the holder like its liveness key: the holder's beat
renews it, releasing or reclaiming the lock deletes it, and a new run is a new
holder, so a record can neither outlive its run nor be read by the next one.
Inputs only: a tool's output is never kept.
"""

import asyncio
from collections.abc import Callable
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from app.constants.cache import EXECUTOR_ALIVE_TTL, EXECUTOR_PROGRESS_PREFIX
from app.constants.executor import EXECUTOR_PROGRESS_MAX_CALLS
from app.constants.general import CALL_EXECUTOR_NAME
from app.constants.log_tags import LogTag
from app.db.redis import redis_cache
from app.utils.background_tasks import spawn_background_task
from shared.py.wide_events import log

#: Not progress: the plan tools are shown as the plan itself, and a live run's
#: stream also carries comms' own hand-off card.
_NOT_PROGRESS = frozenset({"plan_tasks", "update_tasks", CALL_EXECUTOR_NAME})
_TOOL_CALL_ENTRY = "tool_calls_data"
_MAX_VALUE_CHARS = 80

StreamWriter = Callable[[dict[str, object]], None]


class PlanItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    content: str
    status: Literal["pending", "in_progress", "completed", "cancelled"]


class _PlanFrame(BaseModel):
    model_config = ConfigDict(extra="ignore")

    todos: list[PlanItem]
    source: str = "executor"


class _CallData(BaseModel):
    model_config = ConfigDict(extra="ignore")

    tool_name: str
    message: str | None = None
    inputs: dict[str, object] = {}


class _ToolEntry(BaseModel):
    model_config = ConfigDict(extra="ignore")

    tool_name: str
    data: object = None


class _ProgressFrame(BaseModel):
    """The two parts of a stream frame that say what a run is doing; everything else is ignored."""

    model_config = ConfigDict(extra="ignore")

    tool_data: _ToolEntry | list[_ToolEntry] | None = None
    todo_progress: _PlanFrame | None = None


class RecordedCall(BaseModel):
    title: str
    call: str


class RunProgress(BaseModel):
    #: The latest plan per source (the executor, or the subagent that planned).
    plans: dict[str, list[PlanItem]] = {}
    #: Newest last.
    calls: list[RecordedCall] = []


def progress_key(conversation_id: str, lock_value: str) -> str:
    return f"{EXECUTOR_PROGRESS_PREFIX}{conversation_id}:{lock_value}"


def format_call(name: str, inputs: dict[str, object]) -> str:
    """Render a call as name(key="value", ...), each value cut short."""
    args = []
    for key, value in inputs.items():
        rendered = json.dumps(value, ensure_ascii=False, default=str)
        if len(rendered) > _MAX_VALUE_CHARS:
            rendered = f"{rendered[:_MAX_VALUE_CHARS]}..."
        args.append(f"{key}={rendered}")
    return f"{name}({', '.join(args)})"


def _calls_of(frame: _ProgressFrame) -> list[RecordedCall]:
    entries = frame.tool_data if isinstance(frame.tool_data, list) else [frame.tool_data]
    calls = []
    for entry in entries:
        if entry is None or entry.tool_name != _TOOL_CALL_ENTRY:
            continue
        data = _CallData.model_validate(entry.data)
        if data.tool_name in _NOT_PROGRESS:
            continue
        calls.append(
            RecordedCall(
                title=data.message or data.tool_name, call=format_call(data.tool_name, data.inputs)
            )
        )
    return calls


def apply_frame(progress: RunProgress, raw: dict[str, object]) -> bool:
    """Fold one stream frame into progress; return whether it changed anything.

    Raises ValidationError on a frame whose plan or tool entries are malformed.
    """
    frame = _ProgressFrame.model_validate(raw)
    if frame.todo_progress is not None:
        progress.plans[frame.todo_progress.source] = frame.todo_progress.todos
    calls = _calls_of(frame)
    progress.calls = [*progress.calls, *calls][-EXECUTOR_PROGRESS_MAX_CALLS:]
    return frame.todo_progress is not None or bool(calls)


class ProgressRecorder:
    """Keeps one run's progress record in step with the frames it streams.

    Folding is synchronous, in frame order; the Redis write is a single
    in-flight flush that writes until what it last wrote is the latest fold, so
    a burst of frames costs few writes and an older state never lands last.
    The record only describes the run, so neither a frame it cannot read nor a
    write it cannot make may fail the run: both are logged and the run goes on.
    """

    def __init__(self, conversation_id: str, lock_value: str) -> None:
        self._key = progress_key(conversation_id, lock_value)
        self._progress = RunProgress()
        self._flush: asyncio.Task[None] | None = None

    def wrap(self, writer: StreamWriter) -> StreamWriter:
        def recording(frame: dict[str, object]) -> None:
            writer(frame)
            try:
                changed = apply_frame(self._progress, frame)
            except ValidationError as e:
                log.error(
                    f"{LogTag.AGENT} Left an unreadable frame out of the executor's progress",
                    error_type=type(e).__name__,
                    error=str(e),
                )
                return
            if changed and (self._flush is None or self._flush.done()):
                self._flush = spawn_background_task(self._write_latest())

        return recording

    async def _write_latest(self) -> None:
        # Equivalent under mutation: a dump is never "", so None and "" both force the first write.
        written: str | None = None  # pragma: no mutate
        try:
            while (latest := self._progress.model_dump_json()) != written:
                if redis_cache.client:
                    await redis_cache.client.set(self._key, latest, ex=EXECUTOR_ALIVE_TTL)
                written = latest
        except Exception as e:  # advisory record: a lost write must not fail the run it describes
            log.error(
                f"{LogTag.AGENT} Could not write the executor's progress",
                error_type=type(e).__name__,
                error=str(e),
            )

    async def settle(self) -> None:
        """Wait for the last write, so a finalize that renews or deletes the record acts on the final one."""
        if self._flush is not None:
            await self._flush


async def read_progress(conversation_id: str, lock_value: str) -> RunProgress:
    if not redis_cache.client:
        return RunProgress()
    raw = await redis_cache.client.get(progress_key(conversation_id, lock_value))
    return RunProgress.model_validate_json(raw) if raw else RunProgress()


async def drop_progress(conversation_id: str, lock_value: str) -> None:
    if redis_cache.client:
        await redis_cache.client.delete(progress_key(conversation_id, lock_value))


def describe_progress(progress: RunProgress) -> str:
    """Render progress for comms; empty when the run has not planned or called anything yet."""
    lines: list[str] = []
    for source, items in progress.plans.items():
        lines.append(f"Plan ({source}):")
        lines.extend(f"- [{item.status}] {item.content}" for item in items)
    if progress.calls:
        lines.append("Latest tool calls (inputs only, results not shown):")
        lines.extend(f"- {call.title}: {call.call}" for call in progress.calls)
    return "\n".join(lines)
