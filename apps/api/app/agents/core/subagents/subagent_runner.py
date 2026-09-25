"""Shared logic for subagent invocation, used by handoff_tools.py and executor_tool.py.

Lives here (rather than in handoff_tools.py) so those modules import from it,
avoiding a cyclic dependency.
"""

from dataclasses import dataclass, field, replace
import time
from typing import Any, TypedDict, cast
from uuid import NAMESPACE_URL, uuid4, uuid5

from langchain_core.messages import (
    AIMessageChunk,
    AnyMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command, StateSnapshot, interrupt

from app.agents.context.assemble import assemble_context
from app.agents.context.section_context import SectionContext, SectionScope
from app.agents.context.tiers import AgentTier
from app.agents.core.background.session import claim_tool_output, note_tool_output_owner
from app.agents.core.background.subagent_channel import SubagentCancel
from app.agents.core.graph_manager import (
    CompiledAgentGraph,
    GraphManager,
    GraphUnavailableError,
)
from app.agents.core.subagents.registry import get_subagent_by_id
from app.agents.llm.lane import AgentRole, dev_option
from app.agents.llm.reasoning import extract_reasoning_delta
from app.agents.prompts.workflow_prompts import (
    WORKFLOW_AUTO_NOTIFY_SECTION,
    WORKFLOW_SILENT_NOTIFY_SECTION,
)
from app.constants.agents import DONE_EVIDENCE_RULE, AgentTag, wrap_agent_payload
from app.constants.general import (
    EXECUTOR_INTEGRATION_ID,
    EXECUTOR_THREAD_PREFIX,
    FINISH_TASK_NAME,
)
from app.constants.hil import LANGGRAPH_INTERRUPT_KEY
from app.constants.llm import EXECUTOR_RECURSION_LIMIT
from app.constants.log_tags import LogTag
from app.core.stream_manager import stream_manager
from app.helpers.agent_helpers import AgentIdentity, AgentLane, AgentThread, build_agent_config
from app.helpers.message_helpers import (
    build_current_time_message,
    create_system_message,
    format_files_list,
)
from app.models.agent_models import (
    AgentConfigurable,
    AgentRunnableConfig,
    AgentUserContext,
    StreamChunkMetadata,
    agent_configurable,
)
from app.models.hil_models import HilInterruptPayload, HilResumeDecision
from app.models.stream_events import ReasoningPayload, ToolOutputPayload
from app.services.chat.chunks import normalize_custom_event
from app.services.files import FileService
from app.services.latency_metrics import observe_subagent_run
from app.utils.agent_utils import IntegrationMetadata, StreamWriterCallable
from app.utils.multimodal import extract_text_content
from app.utils.stream_utils import extract_tool_entries_from_update
from shared.py.wide_events import log


def _capture_finish_task_content(chunk: ToolMessage, current_message: str) -> str:
    """Return the finish_task chunk's textual content if applicable.

    finish_task carries the final answer in its return value; capturing it makes
    the parent handoff return the actual content instead of the literal "Task
    completed" fallback. Subagents with include_finish_task=False never enter this branch.
    """
    if chunk.name == FINISH_TASK_NAME and isinstance(chunk.content, str):
        return chunk.content
    return current_message


class _MessagesChannel(TypedDict, total=False):
    """The messages channel of a State update or snapshot; its other channels ride along unread."""

    messages: list[AnyMessage]


class SubagentInitialState(TypedDict, total=False):
    """The State channels a subagent run is seeded with; the graph fills in the rest."""

    messages: list[AnyMessage]
    todos: list[object]
    intent: str | None
    integration_usernames: dict[str, str]
    selected_tool_ids: list[str]


@dataclass(frozen=True)
class SubagentOutcome:
    """One graph run's result: its text, or the HIL approval it paused on.

    interrupt carries the payload the gate passed to interrupt(). When it
    is set the graph is checkpointed mid-run and text is meaningless — the
    caller must bubble the pause up rather than treat it as an answer.

    run_messages are THIS run's tool-bearing messages captured off the
    stream — the agent node's AIMessages (complete tool_calls) and the
    ToolMessages answering them. Workflow handoffs render them into the call
    record the executor transcribes playbook steps from (see call_record).
    """

    text: str
    interrupt: HilInterruptPayload | None = None
    run_messages: tuple[AnyMessage, ...] = ()

    @property
    def paused(self) -> bool:
        return self.interrupt is not None


def subagent_row_id(tool_call_id: str) -> str:
    """Derive a UI subagent-row id that stays STABLE across replays of the same call.

    From tool_call_id (unique per generation, stable in the checkpoint), so a
    paused-and-resumed subagent reuses its row instead of orphaning it and
    emitting a duplicate. A blank id (defensive only) falls back to a fresh uuid.
    """
    if not tool_call_id:
        return str(uuid4())
    return str(uuid5(NAMESPACE_URL, f"subagent_row:{tool_call_id}"))


def resume_for_gate(interrupt_payload: HilInterruptPayload) -> object:
    """Return the decision belonging to the subagent gate now paused.

    Resume values replay positionally from zero even though recover_from_checkpoint
    fast-forwards to the LATEST parked gate, so skip any payload whose approval_id
    doesn't match this gate's (one without an id, or a match, delivers as-is).
    """
    target = interrupt_payload.get("approval_id") if isinstance(interrupt_payload, dict) else None
    decision = interrupt(interrupt_payload)
    while target is not None and isinstance(decision, dict):
        answered: HilResumeDecision = cast(HilResumeDecision, decision)
        answered_id = answered.get("approval_id")
        if answered_id is None or answered_id == target:
            break
        decision = interrupt(interrupt_payload)
    return decision


# eq/repr stay off: instances are compared and printed by identity (a generated
# repr would dump the whole message history in `initial_state`), and __hash__ must
# survive for anything holding a context in a set.
@dataclass(eq=False, repr=False)
class SubagentExecutionContext:
    """Container for all data needed to execute a subagent."""

    subagent_graph: CompiledAgentGraph
    agent_name: str
    config: AgentRunnableConfig
    configurable: AgentConfigurable
    integration_id: str
    initial_state: SubagentInitialState
    user_id: str | None = None
    stream_id: str | None = None
    #: The stream of the turn that dispatched a background run onto its own
    #: stream: a Stop on that turn stops the run too.
    parent_stream_id: str | None = None


@dataclass(frozen=True)
class ThreadSeed:
    """What a worker tier's opening thread is seeded from.

    The tier, the run's configurable, and the identifiers context sections retrieve against.
    """

    tier: AgentTier
    configurable: AgentConfigurable
    user_id: str | None = None
    subagent_id: str | None = None
    retrieval_query: str | None = None
    integration_id: str | None = None
    #: The comms turn's request this thread serves; see SectionContext.request_query.
    request_query: str | None = None


async def build_initial_messages(
    *,
    system_message: SystemMessage,
    agent_name: str,
    task: str,
    seed: ThreadSeed,
) -> list[AnyMessage]:
    """Seed a worker tier's thread, in canonical slot order.

    system_message must be STATIC (no per-user/per-time content) so the cache
    prefix stays shared across users. seed.retrieval_query defaults to task, but
    callers pass the unenhanced task when task carries hints that would pollute search.
    """
    configurable: AgentConfigurable = seed.configurable
    tier, user_id, subagent_id, retrieval_query, integration_id = (
        seed.tier,
        seed.user_id,
        seed.subagent_id,
        seed.retrieval_query,
        seed.integration_id,
    )

    log.set(agent_prep={"agent_name": agent_name, "task_length": len(task)})

    assembled = await assemble_context(
        SectionContext.from_configurable(
            tier,
            configurable,
            SectionScope(
                query=retrieval_query if retrieval_query is not None else task,
                request_query=seed.request_query,
                user_id=user_id,
                subagent_id=subagent_id,
                integration_id=integration_id,
            ),
        )
    )

    # Current time rides in a HumanMessage so the system_instruction prefix
    # stays stable — minute ticks would otherwise reset the cache boundary
    # at whatever byte position the timestamp occupies.
    time_message = build_current_time_message(
        user_timezone=configurable.get("user_timezone"),
    )

    return [
        system_message,
        *assembled.messages(),
        HumanMessage(
            content=task,
            additional_kwargs={"visible_to": {agent_name}},
        ),
        time_message,
    ]


def _with_current_time(resume: Command, configurable: AgentConfigurable) -> Command:
    """Re-clock a resumed run.

    A resume replaces initial_state, so the thread keeps the clock from when it
    STARTED — a HIL pause can leave it hours stale. Appending is safe mid
    tool-call: manage_system_prompts_node lifts the latest time message to the tail, untouched pairing.
    """
    update: _MessagesChannel = (
        cast(_MessagesChannel, {**resume.update}) if isinstance(resume.update, dict) else {}
    )
    update["messages"] = [
        *update.get("messages", []),
        build_current_time_message(user_timezone=configurable.get("user_timezone")),
    ]
    return Command(resume=resume.resume, update=update, goto=resume.goto, graph=resume.graph)


def _process_messages_payload(
    # "messages"-mode payloads are always (message chunk, metadata); the driver
    # above holds them as `object` only because the shape varies per stream mode.
    payload: tuple[BaseMessage, StreamChunkMetadata],
    complete_message: str,
    stream_writer: StreamWriterCallable | None,
    subagent_id: str | None,
    stream_id: str,
) -> str:
    """Handle one "messages"-mode stream event, returning the updated message.

    Emits tool_output for ToolMessages, gated by claim_tool_output: a nested
    subagent's chunks carry the SAME run metadata as ours, so ungated it would
    double-render the result — the claim goes to whichever run announced the call.
    """
    metadata: StreamChunkMetadata
    chunk, metadata = payload
    if metadata.get("silent"):
        return complete_message

    # Accumulate AI response content
    if chunk and isinstance(chunk, AIMessageChunk):
        content = chunk.text if hasattr(chunk, "text") else str(chunk.content)
        if content:
            complete_message += content

        # Stream reasoning token by token, carrying subagent_id for step nesting
        # (empty for non-reasoning models). Deltas are per chunk; the stream
        # writer coalesces them for the persistence collector, never for publish.
        if stream_writer:
            reasoning_delta = extract_reasoning_delta(chunk)
            if reasoning_delta:
                reasoning_payload = ReasoningPayload(
                    content=reasoning_delta, subagent_id=subagent_id
                )
                stream_writer({"reasoning": reasoning_payload.model_dump(exclude_none=True)})

    # Emit tool_output when ToolMessage arrives. Text-extract block content so
    # inline media (base64 image blocks) never streams to the frontend.
    elif chunk and isinstance(chunk, ToolMessage):
        content_str = extract_text_content(chunk.content)
        complete_message = _capture_finish_task_content(chunk, complete_message)
        if stream_writer and claim_tool_output(stream_id, chunk.tool_call_id, subagent_id):
            tool_output_payload = ToolOutputPayload(
                tool_call_id=chunk.tool_call_id,
                output=content_str,
                subagent_id=subagent_id,
            )
            stream_writer({"tool_output": tool_output_payload.model_dump(exclude_none=True)})

    return complete_message


@dataclass
class _StreamRun:
    """One drive of execute_subagent_stream: its emitters and its running state.

    Mutable and passed by reference to the per-stream-mode handlers, so the loop
    keeps a single copy of the state every branch accumulates into.
    """

    ctx: SubagentExecutionContext
    stream_writer: StreamWriterCallable | None
    integration_metadata: IntegrationMetadata | None
    subagent_id: str | None
    complete_message: str = ""
    emitted_tool_calls: set[str] = field(default_factory=set)
    tool_ran: bool = False
    pending_approvals: list[HilInterruptPayload] = field(default_factory=list)
    run_messages: list[AnyMessage] = field(default_factory=list)


async def _process_updates_payload(run: _StreamRun, payload: dict[str, object]) -> None:
    """Handle one "updates"-mode stream event: record a pause, or emit tool_data.

    Never break on a pause — keep draining. Under durability="exit", the run-exit
    save is the only checkpoint write, so abandoning early loses completed
    tasks' writes and they re-run on resume (break + "exit" is the only combination that loses them).
    """
    if LANGGRAPH_INTERRUPT_KEY in payload:
        # ONE event per paused task, so two gated calls in a message arrive as
        # two events. Accumulate: the caller stamps re-dispatch context onto
        # every id here, and an approval left out of that can never be applied.
        run.pending_approvals.extend(interrupt_values(payload[LANGGRAPH_INTERRUPT_KEY]))
        log.info(f"{LogTag.HIL} Subagent paused on approval", agent=run.ctx.agent_name)
        return
    for node_name, state_update in payload.items():
        # Only emit tool_data from the LLM ("agent") node — pre-model hooks
        # produce "updates" events with historical AIMessages from previous
        # checkpoint runs, and emitting those would replay stale tool cards.
        if node_name != "agent":
            continue
        # The agent node's update is the one place this run's complete
        # tool_calls (exact names + args) appear — "messages" mode only
        # streams them as partial chunks. Captured for the call record.
        if isinstance(state_update, dict):
            agent_update: _MessagesChannel = cast(_MessagesChannel, state_update)
            run.run_messages.extend(
                msg for msg in agent_update.get("messages", []) if getattr(msg, "tool_calls", None)
            )
        # Use shared helper to extract and format tool entries
        entries = await extract_tool_entries_from_update(
            state_update=state_update,
            emitted_tool_calls=run.emitted_tool_calls,
            integration_metadata=run.integration_metadata,
        )
        for tc_id, tool_entry in entries:
            # Announcing the call is what claims its result: "messages" mode
            # will replay this ToolMessage into the outer run's stream too.
            note_tool_output_owner(run.ctx.stream_id or "", tc_id, run.subagent_id)
            if run.stream_writer:
                chunk_data: dict[str, Any] = {"tool_data": tool_entry}
                if run.subagent_id:
                    chunk_data["tool_data"] = {**tool_entry, "subagent_id": run.subagent_id}
                run.stream_writer(chunk_data)


def _finalize_run(run: _StreamRun) -> SubagentOutcome:
    """Return the outcome a drained (or paused) stream produced."""
    # A pause is not a result: the narration-only heuristic below would misread a
    # half-finished run as "planning text" and tell the parent to re-issue it.
    if run.pending_approvals:
        return SubagentOutcome(
            text=run.complete_message,
            interrupt=merge_approvals(run.pending_approvals),
            run_messages=tuple(run.run_messages),
        )

    # A worker that only narrated did no work: say so, so its delegator re-issues it.
    # The executor is nobody's delegate; its words are its answer (collection runs report).
    if (
        run.ctx.integration_id != EXECUTOR_INTEGRATION_ID
        and not run.tool_ran
        and not run.emitted_tool_calls
        and run.complete_message
    ):
        log.warning("subagent_returned_narration_only", subagent_name=run.ctx.agent_name)
        final_message = (
            f"The {run.ctx.agent_name} subagent ended without running any tool; it only "
            f'produced planning text: "{run.complete_message}". Re-issue the handoff with an '
            "explicit instruction to perform the action."
        )
    else:
        final_message = run.complete_message or "Task completed"
    initial_state: SubagentInitialState = run.ctx.initial_state
    log.set(
        subagent={
            "name": run.ctx.agent_name,
            "provider": run.ctx.integration_id,
            "response_length": len(final_message),
            "messages_count": len(initial_state.get("messages", [])),
        }
    )
    return SubagentOutcome(text=final_message, run_messages=tuple(run.run_messages))


async def execute_subagent_stream(
    ctx: SubagentExecutionContext,
    stream_writer: StreamWriterCallable | None = None,
    integration_metadata: IntegrationMetadata | None = None,
    subagent_id: str | None = None,
    resume: Command | None = None,
) -> SubagentOutcome:
    """Execute (or resume) a subagent with streaming and tool tracking.

    Stream events: "updates" emits tool_data on a tool call, "messages" streams
    content and emits tool_output on a ToolMessage, "custom" forwards progress
    events to the parent. resume continues a thread already paused on a HIL
    interrupt(); a paused outcome carries the approval payload for the caller to bubble up.
    """
    log.set(subagent={"name": ctx.agent_name, "provider": ctx.integration_id})
    run = _StreamRun(
        ctx=ctx,
        stream_writer=stream_writer,
        integration_metadata=integration_metadata,
        subagent_id=subagent_id,
    )

    # Inject the UUID subagent_id into configurable so nested spawn_subagent
    # tool calls can read the correct parent_subagent_id via
    # configurable.get("subagent_id").
    run_config = ctx.config
    if subagent_id:
        base_configurable = agent_configurable(ctx.config)
        run_config = {
            **ctx.config,
            "configurable": {**base_configurable, "subagent_id": subagent_id},
        }

    if resume is not None:
        resume = await _address_resume(ctx.subagent_graph, cast(RunnableConfig, run_config), resume)
        if resume is None:
            # The thread has already consumed this decision. Running it would execute
            # nothing and return empty, which the caller cannot tell apart from a
            # finished task — an empty outcome says "nothing to deliver" outright.
            return SubagentOutcome(text="")

    # The executor addresses a cancel to this subagent by its own thread_id.
    run_configurable: AgentConfigurable = agent_configurable(ctx.config)
    subagent_thread_id = run_configurable.get("thread_id")
    cancel = SubagentCancel(subagent_thread_id) if subagent_thread_id else None

    # One span per segment; a pause ends its segment here, so the HIL wait that
    # follows never counts as active time. Labelled by integration id: per-call
    # uuids and user-made MCPs would each mint unbounded series.
    label = (
        "custom_mcp"
        if ctx.agent_name.startswith("custom_mcp_")
        else ctx.integration_id or ctx.agent_name or "unknown"
    )
    cancelled = False
    segment_start = time.perf_counter()
    try:
        async for event in ctx.subagent_graph.astream(
            _with_current_time(resume, ctx.configurable)
            if resume is not None
            else ctx.initial_state,
            stream_mode=["messages", "custom", "updates"],
            # build_agent_config returns an AgentRunnableConfig, but run_config may be
            # rebuilt above as a dict spread, which mypy widens back to a plain dict.
            config=cast(RunnableConfig, run_config),
            # Persist checkpoints only on run exit (this path is one unit of work),
            # collapsing O(steps) writes to one. The comms graph driver keeps
            # "async" — its mid-run checkpoints are needed.
            durability="exit",
        ):
            if await _stream_cancelled(ctx):
                log.info(
                    f"{LogTag.AGENT} Subagent stream cancelled by user", stream_id=ctx.stream_id
                )
                cancelled = True
                break

            # Handle 2-tuple format only (no subgraphs)
            if len(event) != 2:
                continue
            # A list `stream_mode` makes astream yield (mode, payload) tuples, which
            # langgraph's own overload return type does not express.
            stream_mode, payload = cast(tuple[str, object], event)

            # Targeted cancel from the executor, checked once per superstep (one
            # redis read per reasoning step). Returns a clean cancelled result so
            # the executor learns it stopped; the executor and siblings keep running.
            if (
                stream_mode == "updates"
                and ctx.stream_id
                and cancel
                and await cancel.is_requested()
            ):
                await cancel.clear()
                log.info(f"{LogTag.AGENT} Subagent cancelled by executor", stream_id=ctx.stream_id)
                outcome = _finalize_run(run)
                observe_subagent_run(
                    time.perf_counter() - segment_start, subagent_id=label, status="cancelled"
                )
                # What the run said so far, not the finished-run text: that one reads
                # "Task completed" or tells the executor to re-issue what it just stopped.
                return replace(
                    outcome,
                    text=wrap_agent_payload(
                        AgentTag.SUBAGENT_CANCELLED,
                        run.complete_message or "Stopped by the executor before finishing.",
                    ),
                )

            await _consume_stream_event(run, stream_mode, payload)
    except Exception:
        observe_subagent_run(time.perf_counter() - segment_start, subagent_id=label, status="error")
        raise

    outcome = _finalize_run(run)
    observe_subagent_run(
        time.perf_counter() - segment_start,
        subagent_id=label,
        status=_segment_status(outcome, cancelled=cancelled),
    )
    return outcome


async def _stream_cancelled(ctx: SubagentExecutionContext) -> bool:
    """Whether the user stopped this run's stream, or the turn that dispatched it."""
    for stream_id in (ctx.stream_id, ctx.parent_stream_id):
        if stream_id and await stream_manager.is_cancelled(stream_id):
            return True
    return False


def _segment_status(outcome: SubagentOutcome, *, cancelled: bool) -> str:
    """How this run segment ended, for the latency histogram's status label."""
    if outcome.paused:
        return "paused"
    return "cancelled" if cancelled else "success"


async def _consume_stream_event(run: _StreamRun, stream_mode: str, payload: object) -> None:
    """One (mode, payload) event off the subagent's stream, into the run's state.

    The payload's shape is decided by the mode, which is why the driver holds it
    untyped: each branch narrows it to the shape that mode is documented to carry.
    """
    if stream_mode == "updates":
        await _process_updates_payload(run, cast(dict[str, object], payload))
        return

    if stream_mode == "messages":
        chunk_and_metadata = cast(tuple[BaseMessage, StreamChunkMetadata], payload)
        run.complete_message = _process_messages_payload(
            chunk_and_metadata,
            run.complete_message,
            run.stream_writer,
            run.subagent_id,
            run.ctx.stream_id or "",
        )
        if isinstance(chunk_and_metadata[0], ToolMessage):
            run.tool_ran = True
            run.run_messages.append(chunk_and_metadata[0])
        return

    if stream_mode == "custom" and run.stream_writer:
        run.stream_writer(normalize_custom_event(cast(dict[str, object], payload)))


def _snapshot_messages(snapshot: StateSnapshot) -> list[AnyMessage]:
    """Return the messages a checkpoint holds. Empty means the thread has never run."""
    values = getattr(snapshot, "values", None) or {}
    if not isinstance(values, dict):
        return []
    state: _MessagesChannel = cast(_MessagesChannel, values)
    messages = state.get("messages")
    return messages if isinstance(messages, list) else []


async def thread_messages(ctx: SubagentExecutionContext) -> list[AnyMessage]:
    """Read back what this run's thread holds right now, from its checkpoint.

    The authoritative record of what actually reached the model: a run that died
    mid-call committed nothing, and only the checkpoint can tell that apart from
    a call that landed.
    """
    return _snapshot_messages(await ctx.subagent_graph.aget_state(cast(RunnableConfig, ctx.config)))


def _final_text_from_snapshot(snapshot: StateSnapshot) -> str:
    messages = _snapshot_messages(snapshot)
    if not messages:
        return ""
    content = getattr(messages[-1], "content", "")
    return content if isinstance(content, str) else str(content or "")


async def recover_from_checkpoint(ctx: SubagentExecutionContext) -> SubagentOutcome | None:
    """Return what this subagent's own thread already holds, or None if it never ran.

    Three states, conflating the last two re-drives a completed subagent: Parked
    (mid-run on a HIL interrupt) returns a paused outcome; Finished (state but no
    pending work) returns its checkpointed final answer, since re-running would
    repeat every action; Never ran (no state) returns None so the caller starts it.
    """
    snapshot = await ctx.subagent_graph.aget_state(cast(RunnableConfig, ctx.config))
    if snapshot.next:
        return SubagentOutcome(
            text="", interrupt=interrupt_payload(getattr(snapshot, "interrupts", ()) or ())
        )
    if not _snapshot_messages(snapshot):
        return None
    return SubagentOutcome(text=_final_text_from_snapshot(snapshot) or "Task completed.")


async def _address_resume(
    graph: CompiledAgentGraph, config: RunnableConfig, resume: Command
) -> Command | None:
    """Aim a resume at the one interrupt it answers, or None if the thread already consumed it.

    A bare resume is refused once two interrupts are pending (two destructive calls in one
    message): the approved action never runs and the second approval stays pending forever.
    None keeps a redundant sweep re-dispatch (list_decided_unresumed) from reading as success.
    Reads the live checkpoint; one interrupt, or no matching approval_id, falls through unchanged.
    """
    snapshot = await graph.aget_state(config)
    interrupts = getattr(snapshot, "interrupts", ()) or ()
    if not interrupts and not snapshot.next:
        log.error(
            f"{LogTag.HIL} Resume arrived for a thread with no pending work; "
            "the decision was already applied and this run has nothing to do",
            approval_id=str(_approval_id_of(resume) or ""),
        )
        return None

    approval_id = _approval_id_of(resume)
    if not approval_id or len(interrupts) < 2:
        return resume
    payload = resume.resume

    for item in interrupts:
        value = getattr(item, "value", None)
        interrupt_id = getattr(item, "id", None)
        if not (interrupt_id and isinstance(value, dict)):
            continue
        gate_payload: HilInterruptPayload = cast(HilInterruptPayload, value)
        if gate_payload.get("approval_id") == approval_id:
            log.info(
                f"{LogTag.HIL} Addressing resume to its interrupt",
                approval_id=str(approval_id),
                pending_interrupts=len(interrupts),
            )
            return Command(resume={interrupt_id: payload}, update=resume.update, goto=resume.goto)

    log.warning(
        f"{LogTag.HIL} No pending interrupt matches this decision",
        approval_id=str(approval_id),
        pending_interrupts=len(interrupts),
    )
    return resume


def _approval_id_of(resume: Command) -> str | None:
    """Which gate this decision answers, when the payload carries one."""
    payload = resume.resume
    if not isinstance(payload, dict):
        return None
    decision: HilResumeDecision = cast(HilResumeDecision, payload)
    approval_id = decision.get("approval_id")
    return str(approval_id) if approval_id else None


def interrupt_payload(raw: object) -> HilInterruptPayload:
    """Return the HIL payload inside LangGraph Interrupt object(s).

    Carries EVERY pending approval, not just the first — two destructive calls in
    one message park two tasks, and each id needs its own re-dispatch context. The
    first payload's own fields stay at the top level; approval_ids is what batch readers use.
    """
    return merge_approvals(interrupt_values(raw))


def interrupt_values(raw: object) -> list[HilInterruptPayload]:
    """Return the dict payloads inside one or more LangGraph Interrupt objects."""
    items = raw if isinstance(raw, (list, tuple)) else (raw,)
    return [
        cast(HilInterruptPayload, value)
        for value in (getattr(item, "value", item) for item in items)
        if isinstance(value, dict)
    ]


def merge_approvals(payloads: list[HilInterruptPayload]) -> HilInterruptPayload:
    """Fold several pending approvals into one payload carrying ALL their ids.

    The first payload's own fields stay at the top level, so callers reading a single
    approval (resume_for_gate) are unaffected; approval_ids is what the batch
    readers use (paused_approval_ids).
    """
    if not payloads:
        return {}
    ids = [str(payload["approval_id"]) for payload in payloads if payload.get("approval_id")]
    if len(ids) < 2:
        return payloads[0]
    merged = payloads[0].copy()
    merged["approval_ids"] = ids
    return merged


def paused_approval_ids(payload: HilInterruptPayload) -> tuple[str, ...]:
    """Every approval id a pause carries — the batch first, then the single id."""
    batch = payload.get("approval_ids")
    if isinstance(batch, list):
        ids = tuple(str(a) for a in batch if a)
        if ids:
            return ids
    single = payload.get("approval_id")
    return (str(single),) if single else ()


def compose_executor_brief(
    task: str,
    acceptance_criteria: list[str],
    *,
    verbatim_request: str | None = None,
    last_run: str | None = None,
    playbook_check: str | None = None,
) -> str:
    """Fold the definition-of-done (and verbatim request, previous run) into the brief.

    last_run is a workflow's rendered previous run — its memory now that
    checkpoint threads drop before each fire. playbook_check rides in the brief
    (not the result's narration, since comms can't reach write_playbook) and goes
    last so it reads as the closing instruction.
    """
    criteria = [c.strip() for c in acceptance_criteria if c and c.strip()]
    parts: list[str] = []
    if verbatim_request:
        parts.append(f"Original request (verbatim):\n{verbatim_request.strip()}")
    parts.append(task)
    if last_run:
        parts.append(last_run.strip())
    if criteria:
        lines = "\n".join(f"- {c}" for c in criteria)
        parts.append(
            "Definition of done (every item must be true before you finish):\n"
            f"{lines}\n{DONE_EVIDENCE_RULE}"
        )
    if playbook_check:
        parts.append(playbook_check.strip())
    return "\n\n".join(parts)


async def prepare_executor_execution(
    task: str,
    configurable: AgentConfigurable,
    stream_id: str | None = None,
) -> tuple[SubagentExecutionContext | None, str | None]:
    """Prepare execution context for the executor agent.

    Like the platform-subagent prepare flow but resolves the graph via
    GraphManager, uses executor-specific prompts, and injects direct handoff
    hints when selected_tool/tool_category is known. Returns (ctx, None), or
    (None, error) on failure.
    """
    user_id = configurable.get("user_id")
    thread_id = configurable.get("thread_id", "")

    # Deterministic executor thread, derived purely from the conversation thread
    # so it reconstructs from the conversation id alone — the executor (and its
    # spawned subagents) retains history across call_executor calls in this conversation.
    executor_thread_id = f"{EXECUTOR_THREAD_PREFIX}{thread_id}"

    # VFS session stays pinned to the conversation thread so files written by
    # one executor call are visible to the next.
    vfs_session_id = configurable.get("vfs_session_id") or thread_id

    # Load executor graph. Degrade contract: comms must still receive a
    # tool-result string, so log the real cause loudly and return the error.
    try:
        executor_graph = await GraphManager.get_graph("executor_agent")
    except GraphUnavailableError as e:
        log.error(
            f"{LogTag.AGENT} prepare_executor_execution: executor_agent graph unavailable",
            error=str(e),
        )
        return None, "Executor agent not available"

    # Build user dict for config
    user: AgentUserContext = {
        "user_id": user_id,
        "email": configurable.get("email"),
        "name": configurable.get("user_name"),
    }

    config = await build_agent_config(
        identity=AgentIdentity(
            conversation_id=thread_id,
            user=user,
            agent_name="executor_agent",
        ),
        lane=AgentLane(
            role=AgentRole.EXECUTOR,
            # DEV-ONLY: the switcher's executor pick, stashed by comms. Present only
            # in development; otherwise the executor inherits comms's lane.
            dev_option=dev_option(configurable.get("dev_executor_model")),
        ),
        thread=AgentThread(
            thread_id=executor_thread_id,
            base_configurable=configurable,
            subagent_id="executor_agent",  # Use agent_name as the memory namespace id
            vfs_session_id=vfs_session_id,
            recursion_limit=EXECUTOR_RECURSION_LIMIT,
        ),
    )
    new_configurable = agent_configurable(config)

    # Create system message (executor-specific).
    system_message = create_system_message(
        user_id=user_id,
        agent_type="executor",
        user_name=configurable.get("user_name"),
    )

    # When comms provides a known tool_category, hint the executor to go straight
    # to activate_integration(...) and skip the ChromaDB discovery call — removes
    # one redundant round-trip where comms already knows the category.
    enhanced_task = task
    tool_category = configurable.get("tool_category")
    selected_tool = configurable.get("selected_tool")
    resolved_category = get_subagent_by_id(tool_category) if tool_category else None
    if tool_category and resolved_category:
        tool_hint = f"the '{selected_tool}' tool" if selected_tool else "the user's request"
        if (
            resolved_category.managed_by == "mcp"
            and resolved_category.mcp_config
            and resolved_category.mcp_config.requires_auth
        ):
            enhanced_task = (
                f"{task}\n\n"
                f"DIRECT EXECUTION HINT: This request should be handled by "
                f"'{tool_category}'. Skip retrieve_tools discovery and directly "
                f'handoff(subagent_id="{tool_category}", task="...") with the full request, then '
                f"use its result for {tool_hint}."
            )
        else:
            enhanced_task = (
                f"{task}\n\n"
                f"DIRECT EXECUTION HINT: This request should be handled by "
                f"'{tool_category}'. Skip retrieve_tools discovery and directly "
                f'call activate_integration(integration_id="{tool_category}"), then '
                f"act on {tool_hint} yourself with its tools."
            )
        log.set(
            executor_prep={
                "direct_hint_applied": True,
                "tool_category": tool_category,
                "selected_tool": selected_tool,
            }
        )

    # The executor owns send_notification but only sees the task text comms
    # writes, so inject the notification mode here (keyed off this run's own
    # configurable) rather than depend on comms forwarding the rule. Skip if already present.
    if configurable.get("workflow_id") and "NOTIFICATIONS:" not in enhanced_task:
        notification_section = (
            WORKFLOW_AUTO_NOTIFY_SECTION
            if configurable.get("workflow_notify_on_completion", True)
            else WORKFLOW_SILENT_NOTIFY_SECTION
        )
        enhanced_task = f"{enhanced_task}\n{notification_section}"

    # Surface uploaded files so the executor (which holds the file tools) can act
    # on them directly, rather than depending on comms to hand-copy paths —
    # comms has no file tools of its own.
    if user_id and thread_id:
        uploaded_files = await FileService.list_conversation_files(thread_id, user_id)
        if uploaded_files and (
            files_block := format_files_list(uploaded_files, conversation_id=thread_id)
        ):
            enhanced_task = f"{enhanced_task}\n\n{files_block}"

    # The unenhanced task keeps the DIRECT EXECUTION HINT out of semantic search;
    # request_query lets the executor reuse the recall comms made on the same message.
    messages = await build_initial_messages(
        system_message=system_message,
        agent_name="executor_agent",
        task=enhanced_task,
        seed=ThreadSeed(
            tier=AgentTier.EXECUTOR,
            configurable=new_configurable,
            user_id=user_id,
            retrieval_query=task,
            request_query=configurable.get("user_request"),
        ),
    )

    return SubagentExecutionContext(
        subagent_graph=executor_graph,
        agent_name="executor_agent",
        config=config,
        configurable=new_configurable,
        integration_id=EXECUTOR_INTEGRATION_ID,
        initial_state={"messages": messages, "todos": []},
        user_id=user_id,
        stream_id=stream_id,
    ), None
