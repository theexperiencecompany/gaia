"""The one runner for a subagent the executor delegates to, blocking or in the background.

spawn_subagent and the per-user MCP handoff only build a Delegation; everything
after — claiming the checkpoint thread in RunningSubagents, the start/end events,
the drive loop, background dispatch, landing the result in the executor inbox,
parking on an approval and resuming from it — happens here, once.

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
from langgraph.config import get_stream_writer
from langgraph.errors import GraphBubbleUp
from langgraph.types import Command
from pydantic import BaseModel, ConfigDict

from app.agents.core.background.bg_results import release_bg_dispatch, try_claim_bg_dispatch
from app.agents.core.background.executor_capture import drain_executor_tool_data
from app.agents.core.background.executor_queue import (
    close_detached_stream,
    open_detached_stream,
    safe_configurable,
)
from app.agents.core.background.executor_runner import deliver_to_executor
from app.agents.core.background.redis_writer import make_redis_stream_writer
from app.agents.core.background.running_registry import RunningSubagents
from app.agents.core.background.session import run_user_from_configurable
from app.agents.core.subagents.call_record import append_call_record
from app.agents.core.subagents.subagent_runner import (
    SubagentExecutionContext,
    SubagentOutcome,
    execute_subagent_stream,
    paused_approval_ids,
    recover_from_checkpoint,
    resume_for_gate,
)
from app.agents.prompts.delegation_prompts import (
    BACKGROUND_DELEGATION_ACK,
    SUBAGENT_FAILED_RESULT,
    SUBAGENT_PARKED_ENTRY,
    SUBAGENT_RESULT_ENTRY,
    SUBAGENT_UNRESUMABLE_PARK,
    THREAD_BUSY_REFUSAL,
)
from app.constants.agents import AgentTag
from app.constants.chat import SUBAGENT_GROUP_TOOL_NAME
from app.constants.hil import APPROVAL_REQUEST_TOOL_NAME, SUBAGENT_RESUME_CONFIG_KEY
from app.constants.log_tags import LogTag
from app.constants.streaming import DetachedStreamKind
from app.core.stream_manager import stream_manager
from app.db.repositories.conversations import conversation_repository
from app.models.agent_models import (
    AgentConfigurable,
    RunningSubagent,
    SubagentKind,
    SubagentResumeItem,
    agent_configurable,
)
from app.models.chat_models import SavedSubagentGroup, ToolDataEntry
from app.models.hil_models import HilInterruptPayload, HilResumeDecision
from app.services.hil.approvals_store import get_approval, mark_resumed
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
    agent_type: str
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
    kind: SubagentKind
    subagent_id: str
    tool_call_id: str
    task: str
    display: SubagentDisplay
    parent_configurable: AgentConfigurable
    context: str = ""
    integration_id: str = ""
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

    def resume_item(self) -> SubagentResumeItem:
        return {
            "kind": self.kind,
            "tool_call_id": self.tool_call_id,
            "task": self.task,
            "context": self.context,
            "integration_id": self.integration_id,
            "inherited_tool_names": list(self.inherited_tool_names),
            "parent_configurable": safe_configurable(self.parent_configurable),
        }


def runs_in_background(requested: bool, configurable: AgentConfigurable) -> bool:
    """Whether a delegation asked to run in the background can: only a live conversation can collect it."""
    return (
        requested
        and configurable.get("execution_mode") != "background"
        and bool(configurable.get("stream_id"))
        and bool(configurable.get("conversation_id"))
    )


async def delegate(delegation: Delegation, *, background: bool, probe_parked: bool) -> str:
    """Run the delegation — in the background when it can be, else blocking — and return the tool result."""
    if runs_in_background(background, delegation.ctx.configurable):
        return await _dispatch_background(delegation)
    return await _run_blocking(delegation, probe_parked=probe_parked)


async def _run_blocking(delegation: Delegation, *, probe_parked: bool) -> str:
    """Run to completion inside the calling tool, bubbling every HIL pause up to the parent."""
    registry = RunningSubagents(delegation.conversation_id)
    stream_id = delegation.ctx.stream_id
    record = delegation.running_record(stream_id=stream_id, dispatched_by=stream_id)
    if not await registry.claim(record):
        return THREAD_BUSY_REFUSAL.format(name=delegation.display.name)

    writer = get_stream_writer()
    _emit_start(writer, delegation)
    start_time = time.monotonic()
    paused = False
    try:
        outcome, run_messages = await _drive_blocking(delegation, writer, probe_parked)
    except GraphBubbleUp:
        paused = True
        raise
    finally:
        # A pause is not an ending: the row stays live until the resumed run closes
        # it, and the thread is released so that replay can claim it again.
        await registry.deregister(record)
        if not paused:
            _emit_end(writer, delegation, start_time)
    return _result_text(delegation, outcome.text, run_messages)


async def _drive_blocking(
    delegation: Delegation, writer: StreamWriterCallable, probe_parked: bool
) -> tuple[SubagentOutcome, list[AnyMessage]]:
    """Run the graph, re-raising each gate pause into the parent with interrupt().

    A LOOP, not an if: one task can gate several calls in sequence, each suspending
    the parent again. Only a resume replay can find a checkpoint, so fresh runs
    skip the probe.
    """
    ctx = delegation.ctx
    recovered = await recover_from_checkpoint(ctx) if probe_parked else None
    outcome = (
        recovered
        if recovered is not None
        else await execute_subagent_stream(
            ctx=ctx,
            stream_writer=writer,
            integration_metadata=delegation.integration_metadata,
            subagent_id=delegation.subagent_id,
        )
    )
    run_messages: list[AnyMessage] = list(outcome.run_messages)
    while outcome.paused:
        decision = resume_for_gate(outcome.interrupt or {})
        outcome = await execute_subagent_stream(
            ctx=ctx,
            stream_writer=writer,
            integration_metadata=delegation.integration_metadata,
            subagent_id=delegation.subagent_id,
            resume=Command(resume=decision),
        )
        run_messages.extend(outcome.run_messages)
    return outcome, run_messages


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
    _start_background_run(delegation, record, stream_id, resume=None)
    log.info(
        f"{LogTag.AGENT} Subagent dispatched to background",
        agent_name=delegation.ctx.agent_name,
        subagent_id=delegation.subagent_id,
    )
    return ack


async def resume_background(delegation: Delegation, decision: HilResumeDecision) -> bool:
    """Resume a parked background run with a decision; False when its thread is taken.

    A taken thread is a run still live (its own park resumes it once it exits) or a
    resume already in flight, which re-reads every decided record at its gates.
    """
    # No parent link: the decision is the user's own go-ahead, whatever they did
    # to the turn that dispatched this run.
    stream_id = _new_stream_id()
    record = delegation.running_record(stream_id=stream_id, dispatched_by=None)
    if not await RunningSubagents(delegation.conversation_id).claim(record):
        return False
    _start_background_run(delegation, record, stream_id, resume=Command(resume=decision))
    return True


def _new_stream_id() -> str:
    return f"{SUBAGENT_STREAM_ID_PREFIX}{uuid4()}"


def _start_background_run(
    delegation: Delegation, record: RunningSubagent, stream_id: str, *, resume: Command | None
) -> None:
    spawn_background_task(
        _run_background(delegation, record, stream_id, resume=resume),
        name=BACKGROUND_SUBAGENT_TASK_NAME,
    )


async def _run_background(
    delegation: Delegation, record: RunningSubagent, stream_id: str, *, resume: Command | None
) -> None:
    """Drive a detached run on its own stream to its result, its failure, or its park; never raises."""
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
        resumed=resume is not None,
    ):
        outcome: SubagentOutcome | None = None
        # Equivalent under mutation: read only after the except below has reassigned it.
        failure = ""  # pragma: no mutate
        try:
            outcome = await _execute_on_own_stream(
                delegation, stream_id, resume=resume, parent_stream_id=record.dispatched_by
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
            # Released before the park looks at its decisions, so a resume can claim it.
            await RunningSubagents(delegation.conversation_id).deregister(record)
            await _close_own_stream(delegation, stream_id)

        if outcome is None:
            await _land(delegation, failure)
        elif outcome.stopped:
            # The user stopped it; landing would start the executor they just stopped.
            log.info(
                f"{LogTag.AGENT} Background subagent stopped by the user", agent_name=ctx.agent_name
            )
        elif outcome.paused:
            await _park(delegation, outcome.interrupt or {})
        elif resume is not None and not outcome.text:
            # The thread had already applied this decision; the run that did landed it.
            log.info(f"{LogTag.HIL} Redundant subagent resume had nothing to deliver")
        else:
            log.info(f"{LogTag.AGENT} Background subagent completed", agent_name=ctx.agent_name)
            await _land(
                delegation, _result_text(delegation, outcome.text, list(outcome.run_messages))
            )


async def _execute_on_own_stream(
    delegation: Delegation,
    stream_id: str,
    *,
    resume: Command | None,
    parent_stream_id: str | None,
) -> SubagentOutcome:
    """Move the run onto a stream of its own, announced to the client, and drive it there.

    Its own stream outlives the turn that dispatched it, so an approval card raised
    after that turn ended — and a resumed run's tool cards — still reach the user.
    The recipe rides in the run's configurable so the HIL gate files it on every
    approval this run raises, which is what lets a decision resume it later.
    """
    ctx = delegation.ctx
    await open_detached_stream(
        stream_id,
        conversation_id=delegation.conversation_id,
        user_id=ctx.user_id or "",
        task_id=delegation.subagent_id,
        bot_message_id=_folds_into(delegation),
        kind=DetachedStreamKind.SUBAGENT,
    )
    ctx.stream_id = stream_id
    ctx.parent_stream_id = parent_stream_id
    item = delegation.resume_item()
    for configurable in (ctx.configurable, ctx.config.setdefault("configurable", {})):
        configurable["stream_id"] = stream_id
        configurable[SUBAGENT_RESUME_CONFIG_KEY] = item

    writer = make_redis_stream_writer(stream_id)
    _emit_start(writer, delegation)
    start_time = time.monotonic()
    outcome: SubagentOutcome | None = None
    try:
        outcome = await execute_subagent_stream(
            ctx=ctx,
            stream_writer=writer,
            integration_metadata=delegation.integration_metadata,
            subagent_id=delegation.subagent_id,
            resume=resume,
        )
    finally:
        # A pause is not an ending: the row stays open until the resumed run closes it.
        if outcome is None or not outcome.paused:
            _emit_end(writer, delegation, start_time)
    return outcome


def _folds_into(delegation: Delegation) -> str | None:
    """Return the message a background run's own stream folds into: the dispatching run's."""
    parent: AgentConfigurable = delegation.parent_configurable
    return parent.get("bot_message_id")


async def _close_own_stream(delegation: Delegation, stream_id: str) -> None:
    """Save what the run streamed into the message it folded into, then end its stream."""
    try:
        entries = drain_executor_tool_data(stream_id)
        message_id = _folds_into(delegation)
        if entries and message_id:
            await _save_frames(delegation, message_id, entries)
        elif entries:
            log.warning(
                f"{LogTag.AGENT} Background subagent has no message to save its cards into",
                conversation_id=delegation.conversation_id,
                entries=len(entries),
            )
    except Exception as e:  # unsaved cards must not also cost the run its result
        log.error(
            f"{LogTag.AGENT} Could not save a background subagent's cards",
            conversation_id=delegation.conversation_id,
            subagent_id=delegation.subagent_id,
            error_type=type(e).__name__,
            error=str(e),
        )
    finally:
        await close_detached_stream(
            stream_id, cancelled=await stream_manager.is_cancelled(stream_id)
        )


class _SavedCard(BaseModel):
    """The identity of a saved approval_request entry."""

    model_config = ConfigDict(extra="ignore")

    approval_id: str = ""


async def _save_frames(
    delegation: Delegation, message_id: str, entries: list[ToolDataEntry]
) -> None:
    """Persist a segment's frames by identity, so a reload shows one row and one card.

    A resumed segment's calls extend the row its park saved (in place, never read-
    modify-write), and a card already saved is settled there by the decision.
    """
    conversation_id, user_id = delegation.conversation_id, delegation.ctx.user_id or ""
    saved = await conversation_repository.get_message(conversation_id, message_id, user_id=user_id)
    if saved is None:
        log.error(
            f"{LogTag.AGENT} Background subagent cards matched no message; not saved",
            conversation_id=conversation_id,
            message_id=message_id,
            entries=len(entries),
        )
        return
    held: list[ToolDataEntry] = saved.tool_data or []
    held_groups = {
        SavedSubagentGroup.model_validate(e["data"]).subagent_id
        for e in held
        if e["tool_name"] == SUBAGENT_GROUP_TOOL_NAME
    }
    held_cards = {
        _SavedCard.model_validate(e["data"]).approval_id
        for e in held
        if e["tool_name"] == APPROVAL_REQUEST_TOOL_NAME
    }
    fresh: list[ToolDataEntry] = []
    for entry in entries:
        if entry["tool_name"] == SUBAGENT_GROUP_TOOL_NAME:
            group = SavedSubagentGroup.model_validate(entry["data"])
            if group.subagent_id in held_groups:
                await conversation_repository.extend_subagent_group(
                    conversation_id, user_id=user_id, message_id=message_id, group=group
                )
                continue
        elif (
            entry["tool_name"] == APPROVAL_REQUEST_TOOL_NAME
            and _SavedCard.model_validate(entry["data"]).approval_id in held_cards
        ):
            continue
        fresh.append(entry)
    if fresh and not await conversation_repository.append_message_tool_data(
        conversation_id, user_id=user_id, message_id=message_id, entries=fresh
    ):
        log.error(
            f"{LogTag.AGENT} Background subagent cards matched no message; not saved",
            conversation_id=conversation_id,
            message_id=message_id,
            entries=len(fresh),
        )


async def _park(delegation: Delegation, interrupt: HilInterruptPayload) -> None:
    """Leave the run checkpointed on its approval and say so; resume at once if it is already decided.

    A decision can land while the run is still draining, when its thread is claimed
    and resolution cannot start the resume — that decision is picked up here.
    """
    approval_ids = paused_approval_ids(interrupt)
    if not approval_ids:
        log.error(
            f"{LogTag.HIL} Background subagent paused with no approval id",
            agent_name=delegation.ctx.agent_name,
        )
        await _land(delegation, SUBAGENT_UNRESUMABLE_PARK.format(name=delegation.display.name))
        return
    for approval_id in approval_ids:
        record = await get_approval(approval_id)
        if record is None or not record.status.settled or record.resumed_at is not None:
            continue
        if await resume_background(delegation, record.resume_payload()):
            await mark_resumed(approval_id)
            log.info(f"{LogTag.HIL} Parked subagent resumed on a decision that beat its park")
        return
    log.info(
        f"{LogTag.HIL} Background subagent parked on approval",
        agent_name=delegation.ctx.agent_name,
        approval_ids=list(approval_ids),
    )
    await _announce(
        delegation,
        SUBAGENT_PARKED_ENTRY.format(
            name=delegation.display.name,
            subagent_id=delegation.subagent_id,
            summaries="; ".join(await _approval_summaries(approval_ids, interrupt)),
        ),
    )


async def _approval_summaries(
    approval_ids: tuple[str, ...], interrupt: HilInterruptPayload
) -> list[str]:
    summaries: list[str] = []
    for approval_id in approval_ids:
        record = await get_approval(approval_id)
        summary = record.summary if record is not None else interrupt.get("summary")
        summaries.append(f"{summary or 'an action'} (approval {approval_id})")
    return summaries


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
