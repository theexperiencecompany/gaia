"""The one runner for a subagent the executor delegates to, blocking or in the background.

spawn_subagent only builds a Delegation; everything
after — claiming the checkpoint thread in RunningSubagents, the start/end events,
the drive, background dispatch and landing the result in the executor inbox —
happens here, once.

Background needs a live conversation (interactive, with a stream). A headless run
(workflow, scheduled todo) delivers its result exactly once, so its subagents run
blocking and finish inside it; parallel calls in one message still run concurrently.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
import time
from uuid import uuid4

from langchain_core.messages import AnyMessage
from langchain_core.runnables.config import var_child_runnable_config

from app.agents.core.background.bg_results import release_bg_dispatch, try_claim_bg_dispatch
from app.agents.core.background.executor_runner import deliver_to_executor
from app.agents.core.background.folded_stream import close_folded_stream, open_folded_stream
from app.agents.core.background.redis_writer import make_redis_stream_writer
from app.agents.core.background.running_registry import RunningSubagents
from app.agents.core.background.session import run_user_from_configurable
from app.agents.core.subagents.call_record import append_call_record
from app.agents.core.subagents.subagent_runner import (
    SubagentExecutionContext,
    SubagentOutcome,
    execute_subagent_stream,
)
from app.agents.prompts.delegation_prompts import (
    BACKGROUND_DELEGATION_ACK,
    STOPPED_BEFORE_START,
    SUBAGENT_FAILED_RESULT,
    SUBAGENT_RESULT_ENTRY,
    THREAD_BUSY_REFUSAL,
)
from app.constants.agents import AgentTag
from app.constants.log_tags import LogTag
from app.core.stream_manager import stream_manager
from app.models.agent_models import (
    AgentConfigurable,
    RunningSubagent,
    agent_configurable,
    current_stream_writer,
)
from app.models.stream_events import SubagentAgentType
from app.utils.agent_utils import (
    IntegrationMetadata,
    StreamWriterCallable,
    SubagentStartDetails,
    format_subagent_end_event,
    format_subagent_start_event,
)
from app.utils.background_tasks import spawn_background_task
from shared.py.wide_events import get_trace_id, log, wide_task

#: Task name for a background subagent run. Tests drain by this name to wait out
#: exactly the subagents a turn dispatched, not every background task in the process.
BACKGROUND_SUBAGENT_TASK_NAME = "background-subagent-run"

#: Cosmetic prefix for a background subagent's own stream — log greppability only.
SUBAGENT_STREAM_ID_PREFIX = "subagent_"

#: Longest task text kept on the running-subagent record.
_TASK_SUMMARY_CHARS = 200


@dataclass(frozen=True)
class SubagentDisplay:
    """How the subagent's row presents itself on the user's stream."""

    name: str
    agent_type: SubagentAgentType
    tool_category: str | None = None
    icon_url: str | None = None
    integration: str | None = None
    parent_subagent_id: str | None = None


@dataclass(frozen=True)
class Delegation:
    """One delegated subagent run: its prepared context and everything that rebuilds it.

    subagent_id is the stable row/registry id (subagent_row_id of the tool call);
    parent_configurable is the executor's, which the resume recipe rebuilds from.
    """

    ctx: SubagentExecutionContext
    subagent_id: str
    tool_call_id: str
    task: str
    display: SubagentDisplay
    parent_configurable: AgentConfigurable
    context: str = ""
    inherited_tool_names: tuple[str, ...] = field(default_factory=tuple)
    integration_metadata: IntegrationMetadata | None = None

    @property
    def conversation_id(self) -> str:
        configurable: AgentConfigurable = self.ctx.configurable
        return str(configurable.get("conversation_id") or "")

    @property
    def thread_id(self) -> str:
        run_configurable: AgentConfigurable = agent_configurable(self.ctx.config)
        return str(run_configurable.get("thread_id") or "")

    @property
    def record_calls(self) -> bool:
        # Workflow runs append the subagent's calls so write_playbook transcribes
        # real tool names/args; chat runs pay no extra text or tokens.
        parent: AgentConfigurable = self.parent_configurable
        return bool(parent.get("workflow_id"))

    def running_record(
        self, *, stream_id: str | None, dispatched_by: str | None
    ) -> RunningSubagent:
        return RunningSubagent(
            subagent_id=self.subagent_id,
            subagent_thread_id=self.thread_id,
            integration_id=self.ctx.integration_id,
            agent_name=self.ctx.agent_name,
            task_summary=self.task[:_TASK_SUMMARY_CHARS],
            started_at=datetime.now(UTC).isoformat(),
            stream_id=stream_id,
            dispatched_by=dispatched_by,
        )


def runs_in_background(requested: bool, configurable: AgentConfigurable) -> bool:
    """Whether a delegation asked to run in the background can: only a live conversation can collect it."""
    return (
        requested
        and configurable.get("execution_mode") != "background"
        and bool(configurable.get("stream_id"))
        and bool(configurable.get("conversation_id"))
    )


async def delegate(delegation: Delegation, *, background: bool) -> str:
    """Run the delegation — in the background when it can be, else blocking — and return the tool result."""
    if runs_in_background(background, delegation.ctx.configurable):
        return await _dispatch_background(delegation)
    return await _run_blocking(delegation)


async def _run_blocking(delegation: Delegation) -> str:
    """Run to completion inside the calling tool."""
    registry = RunningSubagents(delegation.conversation_id)
    stream_id = delegation.ctx.stream_id
    record = delegation.running_record(stream_id=stream_id, dispatched_by=stream_id)
    if not await registry.claim(record):
        return THREAD_BUSY_REFUSAL.format(name=delegation.display.name)

    writer = current_stream_writer()
    _emit_start(writer, delegation)
    start_time = time.monotonic()
    try:
        outcome = await execute_subagent_stream(
            ctx=delegation.ctx,
            stream_writer=writer,
            integration_metadata=delegation.integration_metadata,
            subagent_id=delegation.subagent_id,
        )
    finally:
        await registry.deregister(record)
        _emit_end(writer, delegation, start_time)
    return _result_text(delegation, outcome.text, list(outcome.run_messages))


async def _dispatch_background(delegation: Delegation) -> str:
    """Start the run as a detached task and return the acknowledgement the executor keeps working from."""
    conversation_id, tool_call_id = delegation.conversation_id, delegation.tool_call_id
    ack = BACKGROUND_DELEGATION_ACK.format(
        name=delegation.display.name, subagent_id=delegation.subagent_id
    )
    # A replay of the node that dispatched this call must not dispatch it twice.
    if tool_call_id and not await try_claim_bg_dispatch(conversation_id, tool_call_id):
        return ack
    stream_id = _new_stream_id()
    record = delegation.running_record(stream_id=stream_id, dispatched_by=delegation.ctx.stream_id)
    if not await RunningSubagents(conversation_id).claim(record):
        if tool_call_id:
            await release_bg_dispatch(conversation_id, tool_call_id)
        return THREAD_BUSY_REFUSAL.format(name=delegation.display.name)
    # Read after the claim: a stop that read the registry before it could not see this run.
    dispatcher = delegation.ctx.stream_id
    if dispatcher and await stream_manager.is_cancelled(dispatcher):
        await RunningSubagents(conversation_id).deregister(record)
        return STOPPED_BEFORE_START.format(name=delegation.display.name)
    _start_background_run(delegation, record, stream_id)
    log.info(
        f"{LogTag.AGENT} Subagent dispatched to background",
        agent_name=delegation.ctx.agent_name,
        subagent_id=delegation.subagent_id,
    )
    return ack


def _new_stream_id() -> str:
    return f"{SUBAGENT_STREAM_ID_PREFIX}{uuid4()}"


def _start_background_run(delegation: Delegation, record: RunningSubagent, stream_id: str) -> None:
    spawn_background_task(
        _run_background(delegation, record, stream_id),
        name=BACKGROUND_SUBAGENT_TASK_NAME,
    )


async def _run_background(delegation: Delegation, record: RunningSubagent, stream_id: str) -> None:
    """Drive a detached run on its own stream to its result or its failure; never raises."""
    # The task copies the dispatching tool's context, making the subagent graph a child
    # of the executor's run whose stream would echo its messages. Clears only the copy.
    var_child_runnable_config.set(None)
    ctx = delegation.ctx
    # This task outlives the dispatching executor turn, so it needs its own
    # wide-event boundary or every log.set() is silently discarded.
    async with wide_task(
        "subagent_run",
        trace_id=get_trace_id() or None,
        agent_name=ctx.agent_name,
        conversation_id=delegation.conversation_id,
        stream_id=stream_id,
        subagent_id=delegation.subagent_id,
        integration_id=ctx.integration_id,
    ):
        outcome: SubagentOutcome | None = None
        # Equivalent under mutation: read only after the except below has reassigned it.
        failure = ""  # pragma: no mutate
        try:
            outcome = await _execute_on_own_stream(
                delegation, stream_id, parent_stream_id=record.dispatched_by
            )
        except Exception as e:  # the executor must learn its subagent failed
            log.error(
                f"{LogTag.AGENT} Background subagent failed",
                agent_name=ctx.agent_name,
                error_type=type(e).__name__,
                error=str(e),
            )
            failure = SUBAGENT_FAILED_RESULT.format(name=delegation.display.name, error=e)
        finally:
            await RunningSubagents(delegation.conversation_id).deregister(record)
            await close_folded_stream(
                stream_id,
                conversation_id=delegation.conversation_id,
                user_id=delegation.ctx.user_id or "",
            )

        if outcome is None:
            await _land(delegation, failure)
        elif outcome.stopped:
            # The user stopped it; landing would start the executor they just stopped.
            log.info(
                f"{LogTag.AGENT} Background subagent stopped by the user", agent_name=ctx.agent_name
            )
        else:
            log.info(f"{LogTag.AGENT} Background subagent completed", agent_name=ctx.agent_name)
            await _land(
                delegation, _result_text(delegation, outcome.text, list(outcome.run_messages))
            )


async def _execute_on_own_stream(
    delegation: Delegation,
    stream_id: str,
    *,
    parent_stream_id: str | None,
) -> SubagentOutcome:
    """Move the run onto a stream of its own, announced to the client, and drive it there.

    Its own stream outlives the turn that dispatched it, so its tool cards still
    reach the user after that turn ended.
    """
    ctx = delegation.ctx
    if not await open_folded_stream(
        stream_id, conversation_id=delegation.conversation_id, user_id=ctx.user_id or ""
    ):
        # A Stop landed before the run could start: it is as stopped as one the user ended mid-run.
        return SubagentOutcome(text="", stopped=True)
    ctx.stream_id = stream_id
    ctx.parent_stream_id = parent_stream_id
    for configurable in (ctx.configurable, ctx.config.setdefault("configurable", {})):
        configurable["stream_id"] = stream_id

    writer = make_redis_stream_writer(stream_id)
    _emit_start(writer, delegation)
    start_time = time.monotonic()
    try:
        return await execute_subagent_stream(
            ctx=ctx,
            stream_writer=writer,
            integration_metadata=delegation.integration_metadata,
            subagent_id=delegation.subagent_id,
        )
    finally:
        _emit_end(writer, delegation, start_time)


async def _land(delegation: Delegation, result: str) -> None:
    await _announce(
        delegation,
        SUBAGENT_RESULT_ENTRY.format(
            name=delegation.display.name, subagent_id=delegation.subagent_id, result=result
        ),
    )


async def _announce(delegation: Delegation, text: str) -> None:
    """Put an entry in the executor inbox, starting a run to read it when none is live."""
    try:
        await deliver_to_executor(
            delegation.conversation_id,
            run_user_from_configurable(delegation.parent_configurable),
            text,
            tag=AgentTag.SUBAGENT_RESULT,
        )
    except Exception as e:  # a detached task has no caller to raise to
        log.error(
            f"{LogTag.AGENT} Could not deliver a background subagent's landing",
            conversation_id=delegation.conversation_id,
            subagent_id=delegation.subagent_id,
            error_type=type(e).__name__,
            error=str(e),
        )


def _result_text(delegation: Delegation, text: str, run_messages: list[AnyMessage]) -> str:
    return append_call_record(text, run_messages) if delegation.record_calls else text


def _emit_start(writer: StreamWriterCallable, delegation: Delegation) -> None:
    display = delegation.display
    writer(
        {
            "subagent_start": format_subagent_start_event(
                subagent_name=display.name,
                agent_type=display.agent_type,
                subagent_id=delegation.subagent_id,
                subagent=display.integration,
                details=SubagentStartDetails(
                    icon_url=display.icon_url,
                    tool_category=display.tool_category,
                    parent_subagent_id=display.parent_subagent_id,
                ),
            )
        }
    )


def _emit_end(writer: StreamWriterCallable, delegation: Delegation, start_time: float) -> None:
    writer(
        {
            "subagent_end": format_subagent_end_event(
                subagent_id=delegation.subagent_id,
                duration_ms=int((time.monotonic() - start_time) * 1000),
            )
        }
    )
